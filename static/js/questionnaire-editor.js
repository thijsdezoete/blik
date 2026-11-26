/*
 * The questionnaire editor (templates/admin_dashboard/questionnaire_editor.html).
 *
 * Every change goes to the server by itself: a typed text 600 ms after the last key or when the field is left, any
 * other change at once. The server answers JSON with the parts of the page to show again, by slot name
 * (data-slot), and the data of the example chart. The texts of this script come from data- attributes of the page,
 * so they are translated in the templates.
 */
(function() {
    'use strict';

    const root = document.getElementById('questionnaire-editor');

    if (!root) {
        return;
    }

    const TYPING_DELAY = 600;
    const RETRY_DELAY = 3000;
    const url = root.dataset.url;
    const csrfToken = root.querySelector('[name="csrfmiddlewaretoken"]').value;
    const saveState = root.querySelector('[data-save-state]');
    const topicsList = document.getElementById('topics');

    // Per key: the request on its way, the one waiting behind it, and whether the last attempt failed
    const queues = new Map();
    // Per key: a group of fields that was typed in and saves when the typing stops
    const typing = new Map();
    // Per key: the message of a refused change, until a change with that key is accepted
    const refusals = new Map();
    // The keys of groups that are gone for good (a removed new question, the open question of a deleted topic): a
    // refusal for them could never be cleared by a later save, so it is not kept
    const gone = new Set();
    // Per slot: the number of the request whose answer filled it last, so an older answer never replaces a newer one
    const applied = {};
    const idleWaiters = [];
    let requestCount = 0;
    let onceCount = 0;
    let retryTimer = null;
    let chart = JSON.parse(document.getElementById('editor-chart').textContent);
    let openAsk = null;

    const Editor = {
        // The report models ticked in this visit, the topic the reviewer tab shows, the open question
        shown: [],
        topic: root.querySelector('[data-slot="reviewer"] [data-topic]')?.dataset.topic || '',
        open: '',
        // The language of the translate mode, empty in the original language
        lang: root.dataset.lang || '',
    };

    window.Editor = Editor;

    /* ---------- The save queue ---------- */

    // The fields of a request: an object, or a function that reads them from the page when the request is sent
    function fieldsOf(request) {
        return typeof request.fields === 'function' ? request.fields() : request.fields;
    }

    // A login in another tab (after the old one ended) gives a new token, which only the cookie has
    function currentToken() {
        const cookie = document.cookie.split('; ').find(item => item.startsWith('csrftoken='));

        return cookie ? decodeURIComponent(cookie.slice('csrftoken='.length)) : csrfToken;
    }

    // A field with a list of values (the rows of answers) is sent once per value
    function formData(request, fields = fieldsOf(request)) {
        const data = new FormData();
        data.append('csrfmiddlewaretoken', currentToken());
        data.append('action', request.action);
        data.append('shown', Editor.shown.join(','));
        data.append('topic', Editor.topic);
        data.append('open', Editor.open);

        // The server refuses every change of the structure in the translate mode
        if (Editor.lang) {
            data.append('lang', Editor.lang);
        }

        Object.entries(fields).forEach(([name, value]) => [].concat(value).forEach(item => data.append(name, item)));

        return data;
    }

    function queueOf(key) {
        if (!queues.has(key)) {
            queues.set(key, {running: false, waiting: null, failed: false, loggedOut: false});
        }

        return queues.get(key);
    }

    /*
     * Send an action. Requests with the same key run one after the other; a newer request that is still waiting
     * replaces an older waiting one, whose callers get the newer answer. The promise resolves with the answer, also
     * with a refusal ({ok: false, message}); a request that fails (network, server error, an ended login) is sent again
     * after 3 seconds and with the next change, and its promise waits for that.
     *
     * fields may be a function: it is called when the request is sent, so a request that waited sends what the page
     * holds then. options.after(answer, number) runs with the answer (also a refusal) before the next request of the
     * key is sent, so it can write what the answer brings (the id of a new question) into the fields of that request.
     */
    Editor.send = function(action, fields = {}, options = {}) {
        const key = options.key || `once-${++onceCount}`;

        return new Promise(function(resolve) {
            const queue = queueOf(key);
            const request = {action, fields, resolvers: [resolve], afters: options.after ? [options.after] : []};

            if (queue.waiting) {
                takePlace(request, queue.waiting);
            }

            queue.waiting = request;

            if (!queue.running) {
                run(key, queue);
            }

            retryFailed();
            showState();
        });
    };

    /*
     * A newer request takes the place of an older waiting one: the callers of the older one get the newer answer. Its
     * after hooks come along only for the same action; they read the answer of their own action (a delete answers no
     * save).
     */
    function takePlace(newer, older) {
        newer.resolvers.push(...older.resolvers);

        if (newer.action === older.action) {
            newer.afters.push(...older.afters);
        }
    }

    // A part of the page that fails to update must not stop the queue, the save state or the waiting flush
    function safely(run) {
        try {
            run();
        } catch (error) {
            console.error(error);
        }
    }

    async function run(key, queue) {
        const request = queue.waiting;
        const number = ++requestCount;
        let answer = null;
        let loggedOut = false;

        queue.waiting = null;
        queue.running = true;
        request.built = fieldsOf(request);

        try {
            const response = await fetch(url, {
                method: 'POST',
                body: formData(request, request.built),
                headers: {'X-Requested-With': 'XMLHttpRequest', 'X-CSRFToken': currentToken()},
                credentials: 'same-origin',
                // The request still arrives when the page is left meanwhile
                keepalive: true,
            });
            // An ended login answers a redirect to the login page, which fetch follows; a lost right answers 403
            loggedOut = response.redirected || response.status === 401 || response.status === 403;
            answer = await response.json();
        } catch (error) {
            answer = null;
        }

        queue.running = false;

        if (!answer || typeof answer.ok !== 'boolean') {
            // Sent again, unless a newer request of the same key took its place
            queue.failed = true;
            queue.loggedOut = loggedOut;

            if (queue.waiting) {
                takePlace(queue.waiting, request);
            } else {
                queue.waiting = request;
            }

            scheduleRetry();
            showState();
            return;
        }

        queue.failed = false;
        queue.loggedOut = false;

        if (answer.ok) {
            refusals.delete(key);
            safely(() => applyAnswer(answer, number));
        } else {
            if (!gone.has(key)) {
                refusals.set(key, answer.message);
            }
        }

        // The callers learn which fields were stored: those of the newest request, which took the place of theirs
        answer.fields = request.built;
        request.afters.forEach(after => safely(() => after(answer, number)));
        request.resolvers.forEach(resolve => resolve(answer));

        if (queue.waiting) {
            run(key, queue);
        } else {
            queues.delete(key);

            if (answer.ok && !typing.has(key)) {
                // What was typed is stored now
                root.querySelectorAll(`[data-save-key="${key}"] [data-dirty]`).forEach(function(field) {
                    field.removeAttribute('data-dirty');
                });
            }
        }

        showState();
        notifyIdle();
    }

    function scheduleRetry() {
        if (!retryTimer) {
            retryTimer = setTimeout(retryFailed, RETRY_DELAY);
        }
    }

    function retryFailed() {
        clearTimeout(retryTimer);
        retryTimer = null;

        queues.forEach(function(queue, key) {
            if (queue.failed && !queue.running && queue.waiting) {
                run(key, queue);
            }
        });
    }

    function isIdle() {
        return typing.size === 0 && Array.from(queues.values()).every(queue => !queue.running && !queue.waiting);
    }

    function notifyIdle() {
        if (isIdle()) {
            idleWaiters.splice(0).forEach(resolve => resolve());
        }
    }

    // A group that goes away for good: its refusal goes, and a late one is not kept
    function forget(key) {
        gone.add(key);
        refusals.delete(key);
        showState();
    }

    // Resolves when every change is stored: typed texts are sent at once, then the queue is waited for
    Editor.flush = function() {
        Array.from(typing.values()).forEach(entry => entry.save());

        return new Promise(function(resolve) {
            idleWaiters.push(resolve);
            notifyIdle();
        });
    };

    function showState() {
        const states = Array.from(queues.values());
        const refusal = refusals.values().next().value;
        let text = saveState.dataset.saved;
        let color = 'var(--success)';

        if (states.some(queue => queue.loggedOut)) {
            [text, color] = [saveState.dataset.loggedOut, 'var(--danger)'];
        } else if (states.some(queue => queue.failed)) {
            [text, color] = [saveState.dataset.failed, 'var(--danger)'];
        } else if (typing.size || states.some(queue => queue.running || queue.waiting)) {
            [text, color] = [saveState.dataset.saving, 'var(--text-secondary)'];
        } else if (refusal) {
            [text, color] = [refusal, 'var(--danger)'];
        }

        saveState.textContent = text;
        saveState.style.color = color;
    }

    // Changes that are still waiting go out with the page. Per key only the newest goes: the typed text if there is
    // any, else the waiting request; with both, the older one could arrive last and be stored
    window.addEventListener('pagehide', function() {
        new Set([...typing.keys(), ...queues.keys()]).forEach(function(key) {
            const queue = queues.get(key);
            const request = typing.has(key) ? groupRequest(key) : queue?.waiting;
            const fields = request && fieldsOf(request);

            clearTimeout(typing.get(key)?.timer);

            // A new question whose first save is on its way has no id yet; a second save would add it twice
            if (fields && !(fields.question_id === '' && queue?.running)) {
                navigator.sendBeacon(url, formData(request, fields));
            }

            if (queue) {
                queue.waiting = null;
            }
        });
        typing.clear();
    });

    /* ---------- Slots ---------- */

    function focusSelector(element) {
        // The weight selects of one model share a name in the table of the report card
        if (element.dataset.weight) {
            return `[data-weight="${element.dataset.weight}"][data-question-id="${element.dataset.questionId}"]`;
        }

        if (element.name) {
            return `[name="${element.name}"]`;
        }

        if (element.dataset.move) {
            return `[data-move="${element.dataset.move}"]`;
        }

        return element.dataset.act ? `[data-act="${element.dataset.act}"]` : null;
    }

    /*
     * Put the HTML into the slot. The parts of the open question wait while it has a change that was not sent yet
     * (see hasUnsentChange), unless force: the labels after a new number of options must show what is stored.
     */
    function applySlot(name, html, force = false) {
        const slot = root.querySelector(`[data-slot="${name}"]`);

        if (!slot) {
            return false;
        }

        const part = /^question-\d+-(labels|report)$/.test(name);

        if (!force && part && hasUnsentChange(slot.closest('[data-question-form]'))) {
            return false;
        }

        // Fields typed in after the request was sent keep their text, and the focus stays where it was
        const kept = force ? [] : Array.from(slot.querySelectorAll('[data-dirty]'), f => [f.name, f.value, f.checked]);
        const active = slot.contains(document.activeElement) ? document.activeElement : null;
        const selector = active && focusSelector(active);
        const selection = active && 'selectionStart' in active ? [active.selectionStart, active.selectionEnd] : null;

        slot.querySelectorAll('canvas').forEach(canvas => window.Chart?.getChart(canvas)?.destroy());
        slot.innerHTML = html;

        kept.forEach(function([fieldName, value, checked]) {
            const field = slot.querySelector(`[name="${fieldName}"]`);

            if (field) {
                field.value = value;
                field.checked = checked;
                field.setAttribute('data-dirty', '');
            }
        });

        const focus = selector && slot.querySelector(selector);

        if (focus) {
            focus.focus();

            if (selection && focus.setSelectionRange) {
                focus.setSelectionRange(...selection);
            }
        }

        afterSlot(slot);
        return true;
    }

    // Whether "Which questions count, and how much?" is unfolded: the card is filled again after every change
    let weightsOpen = false;

    function afterSlot(slot) {
        slot.querySelectorAll('[data-state="mixed"]').forEach(checkbox => { checkbox.indeterminate = true; });
        slot.querySelectorAll('[data-weights]').forEach(details => { details.open = weightsOpen; });

        const card = slot.closest('[data-section]');

        if (card && card.hasAttribute('data-editing')) {
            setEditing(card, true);
        }

        const form = slot.closest('[data-question-form]');

        if (form) {
            questionSlotApplied(form, slot);
        }

        if (slot.dataset.slot === 'reviewer') {
            outlineOpenQuestion();
        }
    }

    function applyAnswer(answer, number) {
        Object.entries(answer.slots || {}).forEach(function([name, html]) {
            if ((applied[name] || 0) < number && applySlot(name, html)) {
                applied[name] = number;
            }
        });

        if (answer.chart && (applied.chart || 0) < number) {
            applied.chart = number;
            chart = answer.chart;
            drawChart();
        }
    }

    function drawChart() {
        const canvas = document.getElementById('editorRadar');

        // A hidden canvas has no size; the chart is drawn when the report tab opens
        if (!canvas || canvas.closest('[hidden]') || !window.renderSectionRadarChart) {
            return;
        }

        window.Chart.getChart(canvas)?.destroy();
        window.renderSectionRadarChart('editorRadar', chart.data, chart.axes);
    }

    /* ---------- Fields that save themselves ---------- */

    /*
     * The fields of a group (data-save-action) go together; a checkbox sends "on" or nothing. A group that is a form
     * (the open question) sends what the form would: the checked radio and boxes, no disabled field, a list of values
     * for a name that repeats (the rows of answers).
     */
    function groupFields(group) {
        const fields = {};

        if (group.tagName === 'FORM') {
            new FormData(group).forEach(function(value, name) {
                fields[name] = name in fields ? [].concat(fields[name], value) : value;
            });

            return fields;
        }

        group.querySelectorAll('[name]').forEach(function(field) {
            fields[field.name] = field.type === 'checkbox' ? (field.checked ? 'on' : '') : field.value;
        });

        return fields;
    }

    // What a kind of group does besides sending its fields: ready(group) tells whether it can be saved,
    // sent(group) runs when its request is sent, after(group, answer, number) with the answer (see Editor.send)
    const groupHooks = {};

    function findGroup(key) {
        return root.querySelector(`[data-save-key="${key}"]`);
    }

    /*
     * The request that saves the group of fields with this key. The fields are read from the group that is in the page
     * now: a slot that came back replaced the elements that were there when the typing started.
     */
    function groupRequest(key) {
        const group = findGroup(key);
        const hooks = group && groupHooks[group.dataset.saveAction];

        if (!group || (hooks?.ready && !hooks.ready(group))) {
            return null;
        }

        return {action: group.dataset.saveAction, fields: groupFields(group)};
    }

    function saveGroup(key) {
        clearTimeout(typing.get(key)?.timer);
        typing.delete(key);

        const request = groupRequest(key);

        if (!request) {
            showState();
            notifyIdle();
            return Promise.resolve({ok: false, message: ''});
        }

        const hooks = groupHooks[request.action] || {};
        // Read when the request is sent: a request that waits behind another one sends the newest values. The
        // fields read now stand in for a group that is gone by then.
        const fields = function() {
            const group = findGroup(key);

            if (!group) {
                return request.fields;
            }

            hooks.sent?.(group);
            return groupFields(group);
        };
        const after = hooks.after && function(answer, number) {
            const group = findGroup(key);

            if (group) {
                hooks.after(group, answer, number);
            }
        };

        return Editor.send(request.action, fields, {key, after}).then(function(answer) {
            // The header shows the name and description that were stored
            if (answer.ok && answer.fields && request.action === 'save_info') {
                ['name', 'description'].forEach(function(name) {
                    root.querySelector(`[data-header="${name}"]`).textContent = answer.fields[name].trim();
                });
            }

            return answer;
        });
    }

    function saveLater(key) {
        const entry = typing.get(key) || {save: () => saveGroup(key)};

        clearTimeout(entry.timer);
        entry.timer = setTimeout(entry.save, TYPING_DELAY);
        typing.set(key, entry);
        showState();
    }

    root.addEventListener('input', function(event) {
        const group = event.target.closest('[data-save-action]');

        if (group && event.target.name) {
            event.target.setAttribute('data-dirty', '');
            questionInput(event.target);

            if (event.target.matches('input[type="text"], textarea')) {
                saveLater(group.dataset.saveKey);
            }
        }
    });

    root.addEventListener('change', function(event) {
        const group = event.target.closest('[data-save-action]');

        // A change of the open question's answer type or number of options may ask first; it saves by itself
        if (group && event.target.name && !questionChange(event.target)) {
            event.target.setAttribute('data-dirty', '');
            saveGroup(group.dataset.saveKey);
        }
    });

    // The open question is a form without a submit button; Enter never sends it
    root.addEventListener('submit', event => event.preventDefault());

    /* ---------- Questions to the creator ---------- */

    // Show the template as a box after the anchor; its first button runs run, its second closes the box
    Editor.ask = function(template, anchor, run) {
        openAsk?.remove();

        // The control that opened the box gets the focus back when the creator keeps things as they are
        const opener = document.activeElement;
        const box = document.createElement('div');
        const content = document.createElement('div');
        box.className = 'alert alert-warning';
        box.setAttribute('role', 'alert');
        box.style.margin = '0.75rem 1.5rem';
        content.append(template.content.cloneNode(true));
        box.append(content);

        const [action, back] = content.querySelectorAll('button');
        const close = function() {
            box.remove();

            if (openAsk === box) {
                openAsk = null;
            }
        };

        action.addEventListener('click', function() {
            close();
            run();
        });
        back.addEventListener('click', function() {
            close();

            if (opener?.isConnected && opener !== document.body) {
                opener.focus();
            }
        });
        anchor.after(box);
        openAsk = box;
        box.scrollIntoView({block: 'nearest'});
        back.focus();

        return box;
    };

    /* ---------- Topics ---------- */

    function setEditing(card, on) {
        card.toggleAttribute('data-editing', on);
        card.querySelector('[data-topic-edit]').hidden = !on;
        card.querySelectorAll('[data-topic-view]').forEach(element => { element.style.display = on ? 'none' : ''; });
    }

    function showTopic(card) {
        if (Editor.topic !== card.dataset.section) {
            Editor.topic = card.dataset.section;
            Editor.send('refresh', {}, {key: 'refresh'});
        }
    }

    // The creator went on to something else: a topic whose fields are still open closes as with "Done"
    function closeTopics(keep) {
        topicsList.querySelectorAll('[data-section][data-editing]').forEach(function(card) {
            if (card !== keep) {
                closeTopic(card, false);
            }
        });
    }

    function editTopic(card) {
        closeTopics(card);
        setEditing(card, true);
        const title = card.querySelector('[data-topic-edit] [name="title"]');
        title.focus();
        title.select();
        showTopic(card);
    }

    // focus false: the focus goes to what the creator opened next, not back to the "Edit" button
    function closeTopic(card, focus = true) {
        const group = card.querySelector('[data-topic-edit]');
        const close = function() {
            setEditing(card, false);

            if (focus) {
                card.querySelector('[data-act="edit-topic"]').focus();
            }
        };

        if (!group.querySelector('[data-dirty]')) {
            close();
            return;
        }

        // A title that is refused stays open, with the message in the save state
        saveGroup(group.dataset.saveKey).then(function(answer) {
            if (answer.ok) {
                close();
            }
        });
    }

    function deleteTopic(card) {
        const id = card.dataset.section;
        const key = `topic-${id}`;
        const entry = typing.get(key);

        if (entry) {
            clearTimeout(entry.timer);
            typing.delete(key);
        }

        if (Editor.topic === id) {
            Editor.topic = '';
        }

        // Its open question goes with it; a save of it on its way is refused, as the question is gone
        if (openItem && card.contains(openItem)) {
            const questionKey = questionForm(openItem).dataset.saveKey;

            clearTimeout(typing.get(questionKey)?.timer);
            typing.delete(questionKey);
            forget(questionKey);
            openItem = null;
            Editor.open = '';
        }

        // Same key as the topic's texts: a waiting save of them is dropped, one on its way is stored first
        card.hidden = true;
        Editor.send('delete_section', {section_id: id}, {key}).then(function(answer) {
            if (answer.ok) {
                card.remove();
            } else {
                card.hidden = false;
            }
        });
    }

    function addTopic() {
        closeTopics();
        Editor.send('add_section').then(function(answer) {
            if (!answer.ok) {
                return;
            }

            topicsList.insertAdjacentHTML('beforeend', answer.html);
            const card = topicsList.lastElementChild;
            sortQuestions(card.querySelector('.question-list'));
            editTopic(card);
        });
    }

    /* ---------- The open question: opens in place of its row; every change saves by itself ---------- */

    // The <li> of the open question; the newest request to open one (openTicket)
    let openItem = null;
    // The close on its way: a promise of true (closed) or false (kept open by a refusal)
    let closing = null;
    let openTicket = 0;
    let newCount = 0;
    // "More options" stays open for the next question once it was opened
    let moreOpen = false;
    // The rows of answers each type sends
    const ROW_GROUPS = {likert: 'likert', single_choice: 'choice', multiple_choice: 'choice'};
    // The types a question with answers can only keep, never get: its answers would be read as other numbers
    const KEEP_ONLY = ['rating', 'scale'];
    const numbers = (function() {
        try {
            return new Intl.NumberFormat(document.documentElement.lang || undefined, {maximumFractionDigits: 1});
        } catch (error) {
            return new Intl.NumberFormat(undefined, {maximumFractionDigits: 1});
        }
    })();

    function questionForm(item) {
        return item?.querySelector(':scope > [data-question-form]');
    }

    function field(form, name) {
        return form.querySelector(`[name="${name}"]`);
    }

    function currentType(form) {
        return form.querySelector('[name="question_type"]:checked')?.value || '';
    }

    // The answer rows of the group (likert or choice) that have a text: the ones a save stores, in their order
    function answerRows(form, group) {
        return Array.from(form.querySelectorAll(`[data-answer-rows="${group}"] > [data-answer-row]`))
            .filter(row => row.querySelector('[name$="_option_label"]').value.trim());
    }

    /*
     * Each change of the open question counts up form.changes, and a request of the question takes form.sent =
     * form.changes when it is sent. While a change was not sent, the answers do not replace the parts of the question
     * (labels, report): such an answer was made before the change, and the change would be undone in the page. The
     * request with the change brings the parts again.
     */
    function markChanged(form) {
        form.changes += 1;
    }

    function hasUnsentChange(form) {
        return Boolean(form) && form.changes > form.sent;
    }

    function saveQuestion(form) {
        markChanged(form);
        refreshForm(form);
        return saveGroup(form.dataset.saveKey);
    }

    groupHooks.save_question = {
        // A new question is stored from its first text on
        ready: form => Boolean(field(form, 'question_id').value || field(form, 'question_text').value.trim()),
        sent: function(form) {
            form.sent = form.changes;
            // The rows with a text are stored, in this order; the answer gives their ids
            form.postedRows = answerRows(form, ROW_GROUPS[currentType(form)]);
        },
        after: questionSaved,
    };

    // The switch for every question stored the open question as well: its own box shows what is stored now. Not a
    // change of the question, so it sends nothing; a later save of the question sends the box as it is then
    groupHooks.set_did_not_observe = {
        after: function(group, answer) {
            const form = questionForm(openItem);
            const box = form && field(form, 'did_not_observe');

            if (answer.ok && box && ['rating', 'likert'].includes(currentType(form))) {
                box.checked = answer.fields.on === 'on';
            }
        },
    };

    // The answer to a save of the question, before its next save is sent
    function questionSaved(form, answer, number) {
        const item = form.closest('[data-question]');
        const id = answer.ok ? (field(form, 'question_id').value || storeNew(form, item, answer, number)) : '';

        if (answer.ok) {
            form.dataset.storedType = answer.fields.question_type;

            // The rows that were sent get the ids of their stored answers, so the next save keeps them
            if (form.postedRows.length === answer.option_ids.length) {
                form.postedRows.forEach(function(row, index) {
                    row.querySelector('[name$="_option_id"]').value = answer.option_ids[index];
                });
            }
        }

        // The answer to the save with a new number of options: the labels are the stored ones of that number
        if (form.lockedAt !== undefined && form.sent >= form.lockedAt) {
            const select = field(form, 'rating_count');
            const name = `question-${id}-labels`;

            form.lockedAt = undefined;
            lockLabels(form, false);

            if (answer.ok) {
                select.dataset.value = select.value;

                if (name in answer.slots && applySlot(name, answer.slots[name], true)) {
                    applied[name] = number;
                }
            } else {
                select.value = select.dataset.value;
            }
        }

        refreshForm(form);
    }

    // The first save of a new question: it gets its id, its slots and its row
    function storeNew(form, item, answer, number) {
        const id = `${answer.question_id}`;
        const row = document.createElement('div');

        field(form, 'question_id').value = id;
        item.dataset.question = id;
        form.querySelectorAll('[data-slot^="question-new-"]').forEach(function(slot) {
            slot.dataset.slot = slot.dataset.slot.replace('question-new-', `question-${id}-`);
        });

        row.dataset.slot = `question-${id}-row`;
        // Shown when the question was closed while it was saved
        row.hidden = !form.hidden;
        row.innerHTML = answer.row_html;
        item.prepend(row);

        if (item === openItem) {
            Editor.open = id;
            outlineOpenQuestion();
        }

        // The answer named the parts of the question by its id, which they did not have yet
        ['labels', 'report'].forEach(function(part) {
            const name = `question-${id}-${part}`;

            if (name in answer.slots && (applied[name] || 0) < number && applySlot(name, answer.slots[name])) {
                applied[name] = number;
            }
        });

        return id;
    }

    // The type and the number of options are handled on change, as they may ask first
    function questionInput(target) {
        const form = target.closest('[data-question-form]');

        if (form && target.name !== 'question_type' && target.name !== 'rating_count') {
            markChanged(form);
            refreshForm(form);
        }
    }

    // A change in the open question; true when it saves by itself (a new type or number of options may ask first)
    function questionChange(target) {
        const form = target.closest('[data-question-form]');

        if (!form) {
            return false;
        }

        if (target.name === 'question_type') {
            changeType(form, target.value);
            return true;
        }

        if (target.name === 'rating_count') {
            changeCount(form, target);
            return true;
        }

        if (target.name === 'enable_scoring') {
            form.scoring = target.checked;
        }

        markChanged(form);
        refreshForm(form);
        return false;
    }

    function checkType(form, type) {
        form.querySelector(`[name="question_type"][value="${type}"]`).checked = true;
    }

    // Fill a box that asks first: the current type's name and the given values, and the parts for the current type
    function fillAsk(form, box, values = {}) {
        const type = form.dataset.type;
        const radio = form.querySelector(`[name="question_type"][value="${type}"]`);
        const fills = {type: radio.closest('label').querySelector('[data-type-name]').textContent.trim(), ...values};

        box.querySelectorAll('[data-fill]').forEach(function(element) {
            element.textContent = fills[element.dataset.fill] ?? '';
        });
        showTypes(box, type);
    }

    // The old type stays checked until the creator says yes
    function changeType(form, type) {
        const ask = form.querySelector('template[data-ask="type"]');
        const run = function() {
            checkType(form, type);
            form.dataset.type = type;
            saveQuestion(form);
        };

        if (!ask) {
            run();
            return;
        }

        checkType(form, form.dataset.type);
        fillAsk(form, Editor.ask(ask, form.querySelector('[data-type-choice]'), run));
    }

    function lockLabels(form, locked) {
        // inert, not disabled: the number is still sent
        field(form, 'rating_count').inert = locked;
        form.querySelectorAll('[data-slot$="-labels"] input').forEach(input => { input.readOnly = locked; });
    }

    /*
     * A new number of options saves at once. Until its answer comes the number and the labels cannot change: the
     * answer brings the labels the server stored for the new number (see questionSaved), which replace the fields.
     */
    function changeCount(form, select) {
        const count = Number(select.value);
        const ask = form.querySelector('template[data-ask="count"]');
        const run = function() {
            select.value = count;
            markChanged(form);
            refreshForm(form);

            if (groupHooks.save_question.ready(form)) {
                form.lockedAt = form.changes;
                lockLabels(form, true);
            } else {
                select.dataset.value = count;
            }

            saveGroup(form.dataset.saveKey);
        };

        if (!ask || count >= Number(select.dataset.value)) {
            run();
            return;
        }

        select.value = select.dataset.value;
        fillAsk(form, Editor.ask(ask, select, run), {count});
    }

    function removeAnswer(form, row) {
        const ask = form.querySelector('template[data-ask="answer"]');
        // A refused save (a Likert without answers) puts the row back where it was; the refusal shows in the save state
        const run = function() {
            const [list, next] = [row.parentElement, row.nextElementSibling];

            row.remove();
            saveQuestion(form).then(function(answer) {
                if (!answer.ok && answer.message && !row.isConnected && list.isConnected) {
                    // Back as stored: not a change of its own
                    list.insertBefore(row, next?.parentElement === list ? next : null);
                    refreshForm(form);
                }
            });
        };

        // Only a stored answer can have answers from reviewers or a translation
        if (!ask || !row.querySelector('[name$="_option_id"]').value) {
            run();
            return;
        }

        const label = row.querySelector('[name$="_option_label"]').value.trim();
        fillAsk(form, Editor.ask(ask, row, run), {label});
    }

    function addAnswer(form, button) {
        const group = button.parentElement;
        const rows = group.querySelector('[data-answer-rows]');

        rows.append(group.querySelector('template[data-new-row]').content.cloneNode(true));

        const row = rows.lastElementChild;
        const weight = row.querySelector('[name="choice_option_weight"]');

        // A new answer scores one more than the one before, as a start
        if (weight) {
            weight.value = rows.querySelectorAll(':scope > [data-answer-row]').length;
        }

        refreshForm(form);
        row.querySelector('[name$="_option_label"]').focus();
    }

    // The index of a new advice follows the highest one, so the advice keeps its order
    function addAdvice(form) {
        const rows = form.querySelector('[data-advice-rows]');
        const texts = rows.querySelectorAll('[name$="[text]"]');
        const indices = Array.from(texts, text => Number(text.name.match(/\d+/)[0]));
        const index = indices.length ? Math.max(...indices) + 1 : 0;

        rows.append(form.querySelector('template[data-new-advice]').content.cloneNode(true));

        const row = rows.lastElementChild;
        row.querySelectorAll('[name], [id], [for]').forEach(function(element) {
            ['name', 'id', 'htmlFor'].forEach(function(property) {
                if (element[property]) {
                    element[property] = element[property].replace('[new]', `[${index}]`).replace(/-new$/, `-${index}`);
                }
            });
        });
        row.querySelector('[name$="[text]"]').focus();
    }

    function insertName(form) {
        const text = field(form, 'question_text');

        text.setRangeText('{name}', text.selectionStart, text.selectionEnd, 'end');
        text.focus();
        text.dispatchEvent(new Event('input', {bubbles: true}));
    }

    function showTypes(container, type) {
        container.querySelectorAll('[data-types]').forEach(function(element) {
            element.style.display = element.dataset.types.split(' ').includes(type) ? '' : 'none';
        });
    }

    /*
     * "counts as": the score an answer gets on the report's scale of 1 to 5, by the rule of reports/scoring.py
     * (score_on_five) and likert_score() in reports/services.py. Row i of n Likert answers: 1 + i / (n - 1) * 4, from
     * the other end for a negative statement. Pick one with scores: 1 + (score - lowest) / (highest - lowest) * 4.
     */
    function showCountsAs(form, type, scoring) {
        const rows = group => answerRows(form, group);
        const show = function(row, score) {
            const span = row.querySelector('[data-counts-as]');
            // One translated sentence with the place of the score in it
            span.textContent = span.dataset.text.replace('%(score)s', numbers.format(score));
        };

        form.querySelectorAll('[data-counts-as]').forEach(span => { span.textContent = ''; });

        if (type === 'likert') {
            const list = rows('likert');
            const last = list.length - 1;
            const reverse = field(form, 'reverse_scored').checked;

            if (last > 0) {
                list.forEach((row, index) => show(row, 1 + (reverse ? last - index : index) / last * 4));
            }
        } else if (type === 'single_choice' && scoring) {
            const list = rows('choice')
                .map(row => [row, parseFloat(row.querySelector('[name="choice_option_weight"]').value)])
                .filter(([, score]) => Number.isFinite(score));
            const scores = list.map(([, score]) => score);
            const [lowest, highest] = [Math.min(...scores), Math.max(...scores)];

            if (highest > lowest) {
                list.forEach(([row, score]) => show(row, 1 + (score - lowest) / (highest - lowest) * 4));
            }
        }
    }

    // The sentence as a reviewer reads it, or the tip to use the name
    function showName(form) {
        const text = field(form, 'question_text').value;
        const sentence = form.querySelector('[data-sentence]');
        const named = text.includes('{name}');

        sentence.textContent = text.replaceAll('{name}', sentence.dataset.name);
        form.querySelector('[data-with-name]').hidden = !named;
        form.querySelector('[data-without-name]').hidden = named;
    }

    // Show the fields of the chosen type and of what is ticked; hidden fields are sent too
    function refreshForm(form) {
        const type = currentType(form);
        const scoring = Boolean(field(form, 'enable_scoring')?.checked);
        const count = Number(field(form, 'rating_count').value);

        showTypes(form, type);
        const describe = field(form, 'rating_descriptions').checked;

        form.querySelectorAll('[data-scored-field]').forEach(function(element) {
            element.style.display = scoring ? '' : 'none';
        });
        form.querySelector('[data-descriptions]').style.display = describe ? '' : 'none';
        form.querySelectorAll('[data-up-to]').forEach(function(element) {
            element.style.display = Number(element.dataset.upTo) > count ? 'none' : '';
        });

        // A question with answers keeps a Score or Slider only while it is one (the server refuses the change)
        if ('answered' in form.dataset) {
            form.querySelectorAll('[name="question_type"]').forEach(function(radio) {
                if (KEEP_ONLY.includes(radio.value)) {
                    radio.disabled = radio.value !== form.dataset.storedType;
                }
            });
        }

        showCountsAs(form, type, scoring);
        showName(form);
    }

    function questionSlotApplied(form, slot) {
        const box = slot.querySelector('[name="enable_scoring"]');

        // A question stored as another type has no scores; the box stays as the creator left it for a switch back
        if (box && box.hasAttribute('data-keep')) {
            box.checked = form.scoring;
        } else if (box) {
            form.scoring = box.checked;
        }

        refreshForm(form);
    }

    // Outline the open question in "What the reviewer sees" and scroll the right column, not the page, to it
    function outlineOpenQuestion() {
        const panel = root.querySelector('[data-slot="reviewer"]');
        const element = Editor.open && panel.querySelector(`[data-question="${Editor.open}"]`);

        panel.querySelectorAll('[data-question]').forEach(question => { question.style.outline = ''; });

        if (!element) {
            return;
        }

        element.style.outline = '2px solid var(--primary)';
        element.style.outlineOffset = '4px';

        if (!panel.hidden) {
            const column = panel.closest('.editor-preview');
            const box = element.getBoundingClientRect();
            const top = box.top - column.getBoundingClientRect().top;

            if (top < 0 || top + box.height > column.clientHeight) {
                column.scrollTop += top - 16;
            }
        }
    }

    // GET a part of the page (the open question); its slots are applied as those of any answer
    async function load(params) {
        const number = ++requestCount;
        const shown = Editor.shown.join(',');
        const query = new URLSearchParams({...params, shown, topic: Editor.topic, open: Editor.open});
        let answer = null;

        try {
            const response = await fetch(`${url}?${query}`, {
                headers: {'X-Requested-With': 'XMLHttpRequest'},
                credentials: 'same-origin',
            });
            answer = await response.json();
        } catch (error) {
            answer = null;
        }

        if (answer?.ok) {
            refusals.delete('open');
            applyAnswer(answer, number);
        } else if (answer) {
            refusals.set('open', answer.message);
        }

        showState();
        return answer?.ok ? answer : null;
    }

    function showForm(item, html) {
        const template = document.createElement('template');
        template.innerHTML = html;

        const form = template.content.querySelector('[data-question-form]');
        const row = item.querySelector(':scope > [data-slot]');

        // The saves of a new question share one key, also after it got its id
        if (!field(form, 'question_id').value) {
            form.dataset.saveKey = `question-new-${++newCount}`;
        }

        form.changes = 0;
        form.sent = 0;
        form.postedRows = [];
        form.dataset.type = form.dataset.storedType = currentType(form);
        form.scoring = Boolean(field(form, 'enable_scoring')?.checked);
        form.querySelector('[data-more]').open = moreOpen;

        if (row) {
            row.hidden = true;
        }

        item.append(form);
        refreshForm(form);
        item.style.borderColor = 'var(--primary)';
        openItem = item;
        outlineOpenQuestion();
        item.scrollIntoView({block: 'nearest'});
    }

    // Opening another question first saves and closes the open one; the newest click wins
    // Resolves to the form of the question when it is open, null when it did not open
    function openQuestion(item) {
        if (item === openItem) {
            return Promise.resolve(questionForm(item));
        }

        const ticket = ++openTicket;

        closeTopics();

        return closeQuestion().then(function(closed) {
            if (!closed || ticket !== openTicket || !item.isConnected) {
                return null;
            }

            Editor.topic = item.closest('[data-section]').dataset.section;
            Editor.open = item.dataset.question;

            return load({question: item.dataset.question}).then(function(answer) {
                if (ticket !== openTicket) {
                    return null;
                }

                if (answer && item.isConnected) {
                    showForm(item, answer.html);
                    field(questionForm(item), 'question_text').focus();

                    return questionForm(item);
                }

                Editor.open = '';

                return null;
            });
        });
    }

    // From the table of the report card: open the question at its advice, with an empty line when it has none
    function showAdvice(questionId) {
        const item = root.querySelector(`.question-list > [data-question="${questionId}"]`);

        if (!item) {
            return;
        }

        openQuestion(item).then(function(form) {
            const rows = form?.querySelector('[data-advice-rows]');

            if (!rows) {
                return;
            }

            moreOpen = form.querySelector('[data-more]').open = true;

            if (rows.children.length) {
                rows.querySelector('[name$="[text]"]').focus();
            } else {
                addAdvice(form);
            }

            rows.closest('.form-group').scrollIntoView({block: 'center'});
        });
    }

    // "Add a question" opens an empty question at the end of the topic; it is stored with its first text
    function addQuestion(card) {
        const ticket = ++openTicket;

        closeTopics();
        closeQuestion().then(function(closed) {
            if (!closed || ticket !== openTicket) {
                return null;
            }

            Editor.topic = card.dataset.section;
            Editor.open = '';

            return load({new_in: card.dataset.section}).then(function(answer) {
                if (!answer || ticket !== openTicket || !card.isConnected) {
                    return;
                }

                const item = card.querySelector('template[data-new-question]').content.firstElementChild
                    .cloneNode(true);
                card.querySelector('.question-list').append(item);
                showForm(item, answer.html);
                field(questionForm(item), 'question_text').focus();
            });
        });
    }

    /*
     * Close the open question after its last changes are stored. Resolves true when it closed (or none was open), false
     * when a change sent by this close was refused: the question then stays open with the refusal in the save state,
     * so a refused change is never dropped unseen. A refusal shown before is dropped first; only this close's saves
     * decide.
     */
    function closeQuestion() {
        const item = openItem;

        if (closing) {
            return closing;
        }

        // The translate mode has no open question, but its translations must be stored
        if (!item) {
            return Editor.lang ? closeTranslations() : Promise.resolve(true);
        }

        const form = questionForm(item);
        const key = form.dataset.saveKey;

        if (openAsk && form.contains(openAsk)) {
            openAsk.remove();
            openAsk = null;
        }

        // A refusal shown before is dropped: only the saves of this close decide
        refusals.delete(key);
        showState();

        // A new question without a stored text, and nothing on its way, was never stored
        if (!field(form, 'question_id').value && !typing.has(key) && !queues.has(key)) {
            forget(key);
            closeForm(item, form);
            return Promise.resolve(true);
        }

        closing = Editor.flush().then(function() {
            closing = null;

            // Deleted meanwhile
            if (openItem !== item) {
                return true;
            }

            if (refusals.has(key)) {
                field(form, 'question_text').focus();
                return false;
            }

            closeForm(item, form);
            return true;
        });

        return closing;
    }

    /*
     * Before the page is left: every change is stored. Resolves false while a refusal of a group of fields in the page
     * is left (an empty name, an empty topic title): the page stays, the save state shows it, and the focus goes to its
     * field. A refusal of a single action has no field to correct and does not keep the page.
     */
    function readyToLeave() {
        return Editor.flush().then(function() {
            const key = Array.from(refusals.keys()).find(name => findGroup(name));

            if (!key) {
                return true;
            }

            saveState.textContent = refusals.get(key);
            saveState.style.color = 'var(--danger)';

            const group = findGroup(key);
            const input = group.querySelector('[data-dirty]') || group.querySelector('[name]');

            input?.focus();
            return false;
        });
    }

    function closeForm(item, form) {
        const row = item.querySelector(':scope > [data-slot]');
        // A close by another control (a header button, another question) leaves the focus there
        const focused = form.contains(document.activeElement);

        openItem = null;
        Editor.open = '';
        outlineOpenQuestion();
        form.remove();

        // A new question that was never stored goes with its form
        if (!item.dataset.question) {
            item.remove();
            return;
        }

        item.style.borderColor = 'var(--border)';

        if (row) {
            row.hidden = false;

            if (focused) {
                row.querySelector('[data-act="open-question"]')?.focus();
            }
        }
    }

    function deleteQuestion(form) {
        const item = form.closest('[data-question]');
        const key = form.dataset.saveKey;
        const id = field(form, 'question_id');

        clearTimeout(typing.get(key)?.timer);
        typing.delete(key);
        openItem = null;
        Editor.open = '';
        item.hidden = true;
        outlineOpenQuestion();

        if (!id.value && !queues.has(key)) {
            item.remove();
            forget(key);
            notifyIdle();
            return;
        }

        // Same key as the saves of the question: a waiting save is dropped, one on its way is stored first and gives a
        // new question its id
        Editor.send('delete_question', () => ({question_id: id.value}), {key}).then(function(answer) {
            if (answer.ok) {
                item.remove();
            } else if (!openItem) {
                item.hidden = false;
                openItem = item;
                Editor.open = id.value;
            }
        });
    }

    root.addEventListener('toggle', function(event) {
        if (event.target.matches('[data-more]') && event.target.closest('[data-question-form]:not([hidden])')) {
            moreOpen = event.target.open;
        }

        if (event.target.matches('[data-weights]')) {
            weightsOpen = event.target.open;
        }
    }, true);

    /* ---------- Order: drag a handle or use the arrows; each move saves the order of everything ---------- */

    function layout() {
        return Array.from(topicsList.querySelectorAll(':scope > [data-section]:not([hidden])'), card => ({
            section: Number(card.dataset.section),
            // A new question that is not stored yet has no id
            // A question whose delete is on its way is hidden and has no place any more
            questions: Array.from(
                card.querySelectorAll('.question-list > [data-question]:not([hidden])'), q => +q.dataset.question,
            ).filter(Boolean),
        }));
    }

    function saveLayout() {
        Editor.send('reorder', {layout: JSON.stringify(layout())}, {key: 'reorder'});
    }

    function moveItem(button) {
        const item = button.closest('[data-question]') || button.closest('[data-section]');
        const up = button.dataset.move === 'up';
        const sibling = up ? item.previousElementSibling : item.nextElementSibling;

        if (sibling) {
            up ? sibling.before(item) : sibling.after(item);
        } else if (item.matches('[data-question]')) {
            // At the edge of its topic a question moves on into the neighbouring topic
            const card = item.closest('[data-section]');
            const neighbour = up ? card.previousElementSibling : card.nextElementSibling;

            if (!neighbour) {
                return;
            }

            const list = neighbour.querySelector('.question-list');
            up ? list.append(item) : list.prepend(item);
        } else {
            return;
        }

        item.querySelector(`[data-move="${button.dataset.move}"]`)?.focus();
        item.scrollIntoView({block: 'nearest'});
        saveLayout();
    }

    function sortQuestions(list) {
        Sortable.create(list, {
            group: 'questions',
            handle: '.question-handle',
            animation: 150,
            onEnd: function(event) {
                if (event.from !== event.to || event.oldIndex !== event.newIndex) {
                    saveLayout();
                }
            },
        });
    }

    // The translate mode has no topics to move
    if (topicsList) {
        Sortable.create(topicsList, {
            handle: '.section-handle',
            animation: 150,
            onEnd: function(event) {
                if (event.oldIndex !== event.newIndex) {
                    saveLayout();
                }
            },
        });
        topicsList.querySelectorAll('.question-list').forEach(sortQuestions);
    }

    /* ---------- The right column ---------- */

    function showTab(name) {
        const panels = root.querySelectorAll('[data-panel]');

        if (!Array.from(panels).some(panel => panel.dataset.panel === name && panel.hidden)) {
            return;
        }

        root.querySelectorAll('[data-tab]').forEach(function(tab) {
            const selected = tab.dataset.tab === name;

            tab.setAttribute('aria-selected', `${selected}`);
            // The look main.css gives a selected stage tab by aria-current
            tab.style.color = selected ? 'var(--primary)' : '';
            tab.style.borderBottomColor = selected ? 'var(--primary)' : '';
        });
        panels.forEach(panel => { panel.hidden = panel.dataset.panel !== name; });
        drawChart();
        outlineOpenQuestion();
    }

    root.addEventListener('focusin', function(event) {
        const part = event.target.closest('[data-follow]');

        if (part) {
            showTab(part.dataset.follow);
        }
    });

    /* ---------- Buttons ---------- */

    root.addEventListener('click', function(event) {
        // A language tab loads the page again: the open question is saved and closed first, and every other change is
        // stored, unless one is refused. In the translate mode its translations are stored first
        const language = event.target.closest('[data-slot="langs"] a[href]');

        // Only a plain left click: one with a modifier key or the middle button opens a new tab, which the browser does
        const plain = event.button === 0 && !(event.ctrlKey || event.metaKey || event.shiftKey || event.altKey);

        if (language && plain) {
            event.preventDefault();
            closeQuestion().then(ok => ok && readyToLeave()).then(function(ready) {
                if (ready) {
                    window.location.href = language.href;
                }
            });
            return;
        }

        // A click next to an open help dialog (on its backdrop) closes it
        if (event.target.matches('dialog[open]')) {
            event.target.close();
            return;
        }

        const move = event.target.closest('[data-move]');

        if (move) {
            moveItem(move);
            return;
        }

        const tab = event.target.closest('[data-tab]');

        if (tab) {
            showTab(tab.dataset.tab);
            return;
        }

        // A click on the row of a question opens it, except on its drag handle
        const row = event.target.closest('.question-list > [data-question] > [data-slot$="-row"]');

        if (row && !event.target.closest('.drag-handle')) {
            openQuestion(row.parentElement);
            return;
        }

        const button = event.target.closest('[data-act]');
        const card = button?.closest('[data-section]');
        const form = button?.closest('[data-question-form]');

        if (!button) {
            return;
        }

        // The buttons of the header save and close the open question first; a refused change keeps the page here
        const closed = button.closest('.page-header') ? closeQuestion() : Promise.resolve(true);

        switch (button.dataset.act) {
        case 'settings': {
            const settings = root.querySelector('[data-slot="settings"]');
            settings.hidden = !settings.hidden;
            button.setAttribute('aria-expanded', `${!settings.hidden}`);
            break;
        }
        case 'open-tab': {
            // A tab opened after waiting counts as a pop-up, so it opens now and gets its address after the save
            const opened = window.open('', '_blank');
            closed.then(ok => ok && readyToLeave()).then(function(ready) {
                if (!ready) {
                    opened?.close();
                    return;
                }

                if (opened) {
                    opened.opener = null;
                    opened.location = button.dataset.href;
                } else {
                    window.open(button.dataset.href, '_blank', 'noopener');
                }
            });
            break;
        }
        case 'leave':
            closed.then(ok => ok && readyToLeave()).then(function(ready) {
                if (ready) {
                    window.location.href = button.dataset.href;
                }
            });
            break;
        case 'add-topic':
            addTopic();
            break;
        case 'edit-topic':
            editTopic(card);
            break;
        case 'topic-done':
            closeTopic(card);
            break;
        case 'delete-topic':
            Editor.ask(card.querySelector('[data-ask="delete-topic"]'), card.querySelector('.card-header'), () => {
                deleteTopic(card);
            });
            break;
        case 'add-question':
            addQuestion(card);
            break;
        case 'question-done':
            closeQuestion();
            break;
        case 'delete-question':
            Editor.ask(form.querySelector('[data-ask="delete"]'), form.querySelector('[data-question-actions]'), () => {
                deleteQuestion(form);
            });
            break;
        case 'insert-name':
            insertName(form);
            break;
        case 'add-answer':
            addAnswer(form, button);
            break;
        case 'remove-answer':
            removeAnswer(form, button.closest('[data-answer-row]'));
            break;
        case 'add-advice':
            addAdvice(form);
            break;
        case 'row-advice':
            showAdvice(button.dataset.questionId);
            break;
        case 'advice-help': {
            const help = document.getElementById('adviceHelp');

            // Back to the "i" when the dialog closes, also with Escape
            help.addEventListener('close', () => button.focus(), {once: true});
            help.showModal();
            help.querySelector('.card-body').scrollTop = 0;
            break;
        }
        case 'close-dialog':
            button.closest('dialog').close();
            break;
        case 'remove-advice':
            button.closest('[data-advice-row]').remove();
            saveQuestion(form);
            break;
        }
    });

    /* ---------- The report card: the models of the report and how much each question counts for them ---------- */

    const reportCard = root.querySelector('[data-slot="report-card"]');

    // A model that is on when the page opens stays on in this visit, also when its last question stops counting. The
    // translate mode has no card: the report shows the models that have weights
    Editor.shown = Array.from(reportCard?.querySelectorAll('[data-model]:checked') || [], box => box.dataset.model);

    // Scroll the right column, not the page, to the block of the model in "What the report shows"
    function showLevel(model) {
        const column = root.querySelector('.editor-preview');
        const block = root.querySelector(`[data-slot="report"] [data-level="${model}"]`);

        if (block && !block.closest('[hidden]')) {
            column.scrollTop += block.getBoundingClientRect().top - column.getBoundingClientRect().top - 16;
        }
    }

    function refreshModels() {
        return Editor.send('refresh', {}, {key: 'refresh'});
    }

    /*
     * Ticking a model shows its column, its select in the open question and its block on the right. What unticking does
     * the server tells in data-untick, from the stored weights: "ask" when a question with a score counts for the model
     * (the box stays ticked until the creator says yes, then its weights go); "clear" when only questions without a
     * score have a weight for it (older data that never counted, so nothing is lost); "refresh" when it is on only
     * because it was ticked in this visit, so no weight is removed, also not one that is still on its way.
     */
    function toggleModel(box) {
        const model = box.dataset.model;
        const off = function() {
            Editor.shown = Editor.shown.filter(item => item !== model);
        };

        if (box.checked) {
            Editor.shown = [...new Set([...Editor.shown, model])];
            // The creator sees at once what the tick brought: the table of questions
            weightsOpen = true;
            showTab('report');
            refreshModels().then(answer => answer.ok && showLevel(model));
            return;
        }

        const clear = function() {
            off();
            Editor.send('clear_model', {model}, {key: `model-${model}`});
        };

        if (box.dataset.untick === 'refresh') {
            off();
            refreshModels();
            return;
        }

        if (box.dataset.untick === 'clear') {
            clear();
            return;
        }

        box.checked = true;
        Editor.ask(reportCard.querySelector(`template[data-ask="model-${model}"]`), box.closest('label'), clear);
    }

    /*
     * A weight in the table or in part 3 of the open question stores at once, by itself: it is never part of a save of
     * the question, so an older select in an open question cannot undo a choice made in the table. The value is the one
     * chosen; a newer choice for the same question and model takes the place of a waiting one.
     */
    function setWeight(select) {
        const {weight: model, questionId} = select.dataset;

        Editor.send('set_weight', {question_id: questionId, model, weight: select.value}, {
            key: `weight-${questionId}-${model}`,
        });
    }

    root.addEventListener('change', function(event) {
        const box = event.target.closest('[data-model]');
        const select = event.target.closest('select[data-weight]');

        if (box && reportCard.contains(box)) {
            toggleModel(box);
        } else if (select && select.dataset.questionId) {
            setWeight(select);
        }
    });

    /*
     * ---------- The translate mode (?lang=): a field per text of the questionnaire ----------
     *
     * Each field is a group of its own (data-save-action="save_translation", key text-<field_name>), so it saves like
     * every other field of the page. Its slot holds only the state of the text, never the field.
     */

    // Before the page is left: every translation is stored. A refused one keeps the page, with its text in the field
    // and the message in the save state
    function closeTranslations() {
        return Editor.flush().then(function() {
            const key = Array.from(refusals.keys()).find(name => name.startsWith('text-'));

            if (!key) {
                return true;
            }

            findGroup(key)?.querySelector('[name="value"]')?.focus();
            return false;
        });
    }

    // "Still correct" stores the text of the field as it is now, as a translation of the current original text
    function stillCorrect(button) {
        // The group and its field are outside the slot, so no answer replaces them
        const group = button.closest('[data-save-action="save_translation"]');
        const key = group.dataset.saveKey;
        const field = group.querySelector('[name="value"]');

        // The typed text goes with this request
        clearTimeout(typing.get(key)?.timer);
        typing.delete(key);

        const fields = () => ({...groupFields(group), still_correct: 'on'});

        Editor.send('save_translation', fields, {key}).then(function(answer) {
            // The button is gone with the answer; the focus goes back to the field
            if (answer.ok && !root.contains(document.activeElement)) {
                field.focus();
            }
        });
    }

    // "Show only texts that are missing or outdated" hides the other rows when it is ticked. A row translated after
    // that stays until the box is ticked again, so it never moves away under the cursor
    function filterTexts(only) {
        const rows = Array.from(root.querySelectorAll('[data-text-row]'));

        rows.forEach(row => { row.hidden = only && !row.querySelector('[data-state]'); });
        root.querySelectorAll('[data-text-card]').forEach(function(card) {
            card.hidden = only && !card.querySelector('[data-text-row]:not([hidden])');
        });
        root.querySelector('[data-all-done]').hidden = !only || rows.some(row => !row.hidden);
    }

    if (Editor.lang) {
        root.addEventListener('click', function(event) {
            const button = event.target.closest('[data-act="still-correct"]');

            if (button) {
                stillCorrect(button);
            }
        });

        root.addEventListener('change', function(event) {
            if (event.target.matches('[data-only-open]')) {
                filterTexts(event.target.checked);
            }
        });

        // The reviewer tab follows the field with the focus: the topic of its text, with its question outlined. The
        // name and description of the questionnaire have no topic, so the tab keeps what it shows
        root.addEventListener('focusin', function(event) {
            const row = event.target.closest('[data-text-row][data-section]');

            if (!row) {
                return;
            }

            Editor.open = row.dataset.question || '';

            if (Editor.topic !== row.dataset.section) {
                Editor.topic = row.dataset.section;
                Editor.send('refresh', {}, {key: 'refresh'});
            }

            outlineOpenQuestion();
        });
    }

    root.querySelectorAll('[data-state="mixed"]').forEach(checkbox => { checkbox.indeterminate = true; });
})();
