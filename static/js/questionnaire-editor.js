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
    };

    window.Editor = Editor;

    /* ---------- The save queue ---------- */

    // The fields of a request: an object, or a function that reads them from the page when the request is sent
    function fieldsOf(request) {
        return typeof request.fields === 'function' ? request.fields() : request.fields;
    }

    // A field with a list of values (the rows of answers) is sent once per value
    function formData(request, fields = fieldsOf(request)) {
        const data = new FormData();
        data.append('csrfmiddlewaretoken', csrfToken);
        data.append('action', request.action);
        data.append('shown', Editor.shown.join(','));
        data.append('topic', Editor.topic);
        data.append('open', Editor.open);
        Object.entries(fields).forEach(([name, value]) => [].concat(value).forEach(item => data.append(name, item)));

        return data;
    }

    function queueOf(key) {
        if (!queues.has(key)) {
            queues.set(key, {running: false, waiting: null, failed: false});
        }

        return queues.get(key);
    }

    /*
     * Send an action. Requests with the same key run one after the other; a newer request that is still waiting
     * replaces an older waiting one, whose callers get the newer answer. The promise resolves with the answer, also
     * with a refusal ({ok: false, message}); a request that fails (network, server error) is sent again after 3
     * seconds and with the next change, and its promise waits for that.
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

        queue.waiting = null;
        queue.running = true;
        request.built = fieldsOf(request);

        try {
            const response = await fetch(url, {
                method: 'POST',
                body: formData(request, request.built),
                headers: {'X-Requested-With': 'XMLHttpRequest', 'X-CSRFToken': csrfToken},
                credentials: 'same-origin',
                // The request still arrives when the page is left meanwhile
                keepalive: true,
            });
            answer = await response.json();
        } catch (error) {
            answer = null;
        }

        queue.running = false;

        if (!answer || typeof answer.ok !== 'boolean') {
            // Sent again, unless a newer request of the same key took its place
            queue.failed = true;

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

        if (answer.ok) {
            refusals.delete(key);
            safely(() => applyAnswer(answer, number));
        } else {
            refusals.set(key, answer.message);
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

        if (states.some(queue => queue.failed)) {
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

    function afterSlot(slot) {
        slot.querySelectorAll('[data-state="mixed"]').forEach(checkbox => { checkbox.indeterminate = true; });

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
        back.addEventListener('click', close);
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

    function editTopic(card) {
        setEditing(card, true);
        const title = card.querySelector('[data-topic-edit] [name="title"]');
        title.focus();
        title.select();
        showTopic(card);
    }

    function closeTopic(card) {
        const group = card.querySelector('[data-topic-edit]');

        if (!group.querySelector('[data-dirty]')) {
            setEditing(card, false);
            return;
        }

        // A title that is refused stays open, with the message in the save state
        saveGroup(group.dataset.saveKey).then(function(answer) {
            if (answer.ok) {
                setEditing(card, false);
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

        // Its open question goes with it
        if (openItem && card.contains(openItem)) {
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
            span.textContent = `${span.dataset.text} ${numbers.format(score)}`;
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
    function openQuestion(item) {
        if (item === openItem) {
            return;
        }

        const ticket = ++openTicket;

        closeQuestion().then(function(closed) {
            if (!closed || ticket !== openTicket || !item.isConnected) {
                return null;
            }

            Editor.topic = item.closest('[data-section]').dataset.section;
            Editor.open = item.dataset.question;

            return load({question: item.dataset.question}).then(function(answer) {
                if (ticket !== openTicket) {
                    return;
                }

                if (answer && item.isConnected) {
                    showForm(item, answer.html);
                } else {
                    Editor.open = '';
                }
            });
        });
    }

    // "Add a question" opens an empty question at the end of the topic; it is stored with its first text
    function addQuestion(card) {
        const ticket = ++openTicket;

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

        if (!item) {
            return Promise.resolve(true);
        }

        const form = questionForm(item);
        const key = form.dataset.saveKey;

        if (openAsk && form.contains(openAsk)) {
            openAsk.remove();
            openAsk = null;
        }

        // A new question without a text was never stored
        if (!field(form, 'question_id').value && !typing.has(key) && !queues.has(key)) {
            closeForm(item, form);
            return Promise.resolve(true);
        }

        refusals.delete(key);
        showState();

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

    function closeForm(item, form) {
        const row = item.querySelector(':scope > [data-slot]');

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
            showState();
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
    }, true);

    /* ---------- Order: drag a handle or use the arrows; each move saves the order of everything ---------- */

    function layout() {
        return Array.from(topicsList.querySelectorAll(':scope > [data-section]:not([hidden])'), card => ({
            section: Number(card.dataset.section),
            // A new question that is not stored yet has no id
            questions: Array.from(card.querySelectorAll('.question-list > [data-question]'), q => +q.dataset.question)
                .filter(Boolean),
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

    /* ---------- The right column ---------- */

    function showTab(name) {
        const panels = root.querySelectorAll('[data-panel]');

        if (!Array.from(panels).some(panel => panel.dataset.panel === name && panel.hidden)) {
            return;
        }

        root.querySelectorAll('[data-tab]').forEach(function(tab) {
            tab.toggleAttribute('aria-current', tab.dataset.tab === name);
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
        // A language tab loads the page again: the open question is saved and closed first, unless that is refused
        const language = event.target.closest('[data-slot="langs"] a[href]');

        if (language && openItem) {
            event.preventDefault();
            closeQuestion().then(ok => ok && Editor.flush().then(() => { window.location.href = language.href; }));
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
            closed.then(function(ok) {
                if (!ok) {
                    opened?.close();
                    return null;
                }

                return Editor.flush();
            }).then(function(saved) {
                if (saved === null) {
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
            closed.then(ok => ok && Editor.flush().then(() => { window.location.href = button.dataset.href; }));
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
        case 'remove-advice':
            button.closest('[data-advice-row]').remove();
            saveQuestion(form);
            break;
        }
    });

    root.querySelectorAll('[data-state="mixed"]').forEach(checkbox => { checkbox.indeterminate = true; });
})();
