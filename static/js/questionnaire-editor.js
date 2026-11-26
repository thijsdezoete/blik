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

    function formData(request) {
        const data = new FormData();
        data.append('csrfmiddlewaretoken', csrfToken);
        data.append('action', request.action);
        data.append('shown', Editor.shown.join(','));
        data.append('topic', Editor.topic);
        data.append('open', Editor.open);
        Object.entries(request.fields).forEach(([name, value]) => data.append(name, value));

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
     */
    Editor.send = function(action, fields = {}, options = {}) {
        const key = options.key || `once-${++onceCount}`;

        return new Promise(function(resolve) {
            const queue = queueOf(key);
            const request = {action, fields, resolvers: [resolve]};

            if (queue.waiting) {
                request.resolvers.push(...queue.waiting.resolvers);
            }

            queue.waiting = request;

            if (!queue.running) {
                run(key, queue);
            }

            retryFailed();
            showState();
        });
    };

    async function run(key, queue) {
        const request = queue.waiting;
        const number = ++requestCount;
        let answer = null;

        queue.waiting = null;
        queue.running = true;

        try {
            const response = await fetch(url, {
                method: 'POST',
                body: formData(request),
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
                queue.waiting.resolvers.push(...request.resolvers);
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
            applyAnswer(answer, number);
        } else {
            refusals.set(key, answer.message);
        }

        // The callers learn which fields were stored: those of the newest request, which took the place of theirs
        answer.fields = request.fields;
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

            clearTimeout(typing.get(key)?.timer);

            if (request) {
                navigator.sendBeacon(url, formData(request));
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

    function applySlot(name, html) {
        const slot = root.querySelector(`[data-slot="${name}"]`);

        if (!slot) {
            return false;
        }

        // The parts of the open question wait while it has a change that is not stored yet
        const question = slot.closest('[data-question]');

        if (/^question-\d+-(labels|report)$/.test(name) && question?.querySelector('[data-dirty]')) {
            return false;
        }

        // Fields typed in after the request was sent keep their text, and the focus stays where it was
        const kept = Array.from(slot.querySelectorAll('[data-dirty]'), f => [f.name, f.value, f.checked]);
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

    // The fields of a group (data-save-action) go together; a checkbox sends "on" or nothing
    function groupFields(group) {
        const fields = {};

        group.querySelectorAll('[name]').forEach(function(field) {
            fields[field.name] = field.type === 'checkbox' ? (field.checked ? 'on' : '') : field.value;
        });

        return fields;
    }

    /*
     * The request that saves the group of fields with this key. The fields are read from the group that is in the page
     * now: a slot that came back replaced the elements that were there when the typing started.
     */
    function groupRequest(key) {
        const group = root.querySelector(`[data-save-key="${key}"]`);

        return group && {action: group.dataset.saveAction, fields: groupFields(group)};
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

        return Editor.send(request.action, request.fields, {key}).then(function(answer) {
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

            if (event.target.matches('input[type="text"], textarea')) {
                saveLater(group.dataset.saveKey);
            }
        }
    });

    root.addEventListener('change', function(event) {
        const group = event.target.closest('[data-save-action]');

        if (group && event.target.name) {
            event.target.setAttribute('data-dirty', '');
            saveGroup(group.dataset.saveKey);
        }
    });

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

    /* ---------- Order: drag a handle or use the arrows; each move saves the order of everything ---------- */

    function layout() {
        return Array.from(topicsList.querySelectorAll(':scope > [data-section]:not([hidden])'), card => ({
            section: Number(card.dataset.section),
            questions: Array.from(card.querySelectorAll('.question-list > [data-question]'), q => +q.dataset.question),
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
    }

    root.addEventListener('focusin', function(event) {
        const part = event.target.closest('[data-follow]');

        if (part) {
            showTab(part.dataset.follow);
        }
    });

    /* ---------- Buttons ---------- */

    root.addEventListener('click', function(event) {
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

        const button = event.target.closest('[data-act]');
        const card = button?.closest('[data-section]');

        if (!button) {
            return;
        }

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
            Editor.flush().then(function() {
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
            Editor.flush().then(() => { window.location.href = button.dataset.href; });
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
        }
    });

    root.querySelectorAll('[data-state="mixed"]').forEach(checkbox => { checkbox.indeterminate = true; });
})();
