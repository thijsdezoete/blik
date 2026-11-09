/**
 * Org chart editor: chart view (zoom, pan, collapse) and outline view (expand,
 * drag units onto units), sharing person drag and drop and the unit dialogs.
 *
 * Every change returns both views and the unplaced pool rendered again; the
 * page swaps them in and re-applies what the user had open, collapsed or zoomed.
 * Events are delegated from `document`, so new HTML needs no binding.
 */
(function () {
    'use strict';

    const PLACEHOLDER_UUID = '00000000-0000-0000-0000-000000000000';
    const ENDPOINTS = window.OC_ENDPOINTS;
    const board = document.querySelector('.oc-board');
    const chart = document.getElementById('ocChart');
    const outline = document.getElementById('ocOutline');
    const pool = document.getElementById('ocUnplaced');
    const errorBox = board.querySelector('.oc-error');
    const STORE = 'blik.orgchart.v1';

    // ------------------------------------------------------------ view state

    let state = { view: 'chart', zoom: 1, open: [], collapsed: [] };
    try { Object.assign(state, JSON.parse(localStorage.getItem(STORE)) || {}); } catch (_) {}
    const open = new Set(state.open);            // outline rows and member lists that are open
    const collapsed = new Set(state.collapsed);  // chart nodes whose children are hidden

    function save() {
        state.open = [...open];
        state.collapsed = [...collapsed];
        try { localStorage.setItem(STORE, JSON.stringify(state)); } catch (_) {}
    }

    function applyState() {
        board.dataset.view = state.view;
        board.querySelectorAll('[data-oc-view]').forEach(tab => {
            if (tab.dataset.ocView === state.view) tab.setAttribute('aria-current', 'true');
            else tab.removeAttribute('aria-current');
        });
        board.querySelectorAll('[data-view-panel], [data-for-view]').forEach(el => {
            el.hidden = (el.dataset.viewPanel || el.dataset.forView) !== state.view;
        });
        chart.querySelectorAll('.oc-node').forEach(node => {
            const isCollapsed = collapsed.has(node.dataset.key);
            node.classList.toggle('oc-collapsed', isCollapsed);
            const btn = node.querySelector(':scope > .oc-unit .oc-collapse');
            if (btn) btn.setAttribute('aria-expanded', String(!isCollapsed));
        });
        chart.querySelectorAll('details.oc-members').forEach(d => { d.open = open.has(d.dataset.key); });
        outline.querySelectorAll('.oc-branch').forEach(setRow);
        setZoom(state.zoom);
    }

    function setRow(branch) {
        const isOpen = open.has(branch.dataset.key);
        branch.querySelector(':scope > .oc-row-detail').hidden = !isOpen;
        branch.querySelector(':scope > .oc-row .oc-toggle').setAttribute('aria-expanded', String(isOpen));
    }

    // ------------------------------------------------------------ server calls

    function csrf() {
        const el = document.querySelector('[name=csrfmiddlewaretoken]');
        return el ? el.value : '';
    }

    async function post(url, params) {
        const resp = await fetch(url, {
            method: 'POST',
            credentials: 'same-origin',
            headers: { 'X-CSRFToken': csrf(), 'Accept': 'application/json' },
            body: new URLSearchParams(params || {}),
        });
        const data = await resp.json().catch(() => ({}));
        if (!resp.ok) throw new Error(data.error || resp.statusText);
        chart.innerHTML = data.chart_html;
        outline.innerHTML = data.outline_html;
        pool.innerHTML = data.unplaced_html;
        errorBox.hidden = true;
        applyState();
        return data;
    }

    function showError(err) {
        errorBox.textContent = err.message || String(err);
        errorBox.hidden = false;
    }

    const unitUrl = (key, uuid) => ENDPOINTS[key].replace(PLACEHOLDER_UUID, uuid);

    // ------------------------------------------------------------ dialogs

    let current = null;  // {uuid, name} of the unit a dialog acts on

    function openDialog(id, unit) {
        const dialog = document.getElementById(id);
        current = unit || null;
        dialog.querySelectorAll('.oc-dialog-error').forEach(el => { el.hidden = true; });
        dialog.querySelectorAll('[data-oc-unit-label]').forEach(el => { el.textContent = unit ? unit.name : ''; });
        dialog.showModal();
        return dialog;
    }

    function dialogError(dialog, err) {
        const box = dialog.querySelector('.oc-dialog-error');
        box.textContent = err.message;
        box.hidden = false;
    }

    function openUnitDialog(unit) {
        const dialog = openDialog('ocUnitDialog', unit);
        dialog.querySelector('.card-title').textContent = unit ? dialog.dataset.titleRename : dialog.dataset.titleCreate;
        const input = dialog.querySelector('input[name=name]');
        input.value = unit ? unit.name : '';
        input.focus();
        input.select();
    }

    function openPersonDialog(unit, role) {
        const dialog = openDialog('ocPersonDialog', unit);
        dialog.querySelector('.card-title').textContent = role === 'manager' ? dialog.dataset.titleManager : dialog.dataset.titleMember;
        const holder = dialog.querySelector('.oc-picker-holder');
        holder.innerHTML = '<div data-reviewee-picker data-field-name="_unused"></div>';
        const el = holder.firstChild;
        new window.RevieweePicker(el);
        el.addEventListener('reviewee-picker:change', async (e) => {
            const person = (e.detail.selected || [])[0];
            if (!person) return;
            try {
                await post(ENDPOINTS.membershipCreate, { unit_uuid: unit.uuid, reviewee_uuid: person.uuid, role });
                dialog.close();
            } catch (err) {
                dialogError(dialog, err);
            }
        });
        const input = el.querySelector('input');
        if (input) input.focus();
    }

    function openParentDialog(unit) {
        const dialog = openDialog('ocParentDialog', unit);
        const select = dialog.querySelector('select');
        select.innerHTML = '';
        [...chart.querySelectorAll('.oc-unit')]
            .filter(el => el.dataset.unitUuid !== unit.uuid)
            .sort((a, b) => a.dataset.unitName.localeCompare(b.dataset.unitName))
            .forEach(el => select.add(new Option(el.dataset.unitName, el.dataset.unitUuid)));
    }

    document.addEventListener('submit', async (e) => {
        const form = e.target.closest('[data-oc-form]');
        if (!form) return;
        e.preventDefault();
        const dialog = form.closest('dialog');
        const values = Object.fromEntries(new FormData(form));
        try {
            const kind = form.dataset.ocForm;
            if (kind === 'unit') {
                await post(current ? unitUrl('unitUpdate', current.uuid) : ENDPOINTS.unitCreate, values);
            } else if (kind === 'parent') {
                await post(unitUrl('unitSetParent', current.uuid), values);
            } else if (kind === 'delete') {
                await post(unitUrl('unitDelete', current.uuid));
            }
            dialog.close();
        } catch (err) {
            dialogError(dialog, err);
        }
    });

    // ------------------------------------------------------------ clicks

    const unitOf = (el) => {
        const host = el.closest('[data-unit-uuid][data-unit-name]');
        return host && { uuid: host.dataset.unitUuid, name: host.dataset.unitName };
    };

    document.addEventListener('click', async (e) => {
        const t = e.target;
        let el;
        if (t.matches('dialog[open]')) {
            // A click on the backdrop targets the dialog itself, outside its box.
            const r = t.getBoundingClientRect();
            if (e.clientX < r.left || e.clientX > r.right || e.clientY < r.top || e.clientY > r.bottom) t.close();
        } else if ((el = t.closest('[data-oc-close]'))) {
            el.closest('dialog').close();
        } else if ((el = t.closest('[data-oc-open]'))) {
            openDialog(el.dataset.ocOpen);
        } else if (t.closest('[data-oc-new-unit]')) {
            openUnitDialog(null);
        } else if ((el = t.closest('[data-oc-view]'))) {
            state.view = el.dataset.ocView;
            save();
            applyState();
        } else if ((el = t.closest('[data-oc-zoom]'))) {
            const how = el.dataset.ocZoom;
            setZoom(how === 'fit' ? fitZoom() : state.zoom + (how === 'in' ? 0.1 : -0.1));
            save();
        } else if ((el = t.closest('[data-oc-expand]'))) {
            outline.querySelectorAll('.oc-branch').forEach(b => {
                if (el.dataset.ocExpand === 'all') open.add(b.dataset.key); else open.delete(b.dataset.key);
            });
            save();
            applyState();
        } else if ((el = t.closest('.oc-toggle'))) {
            const branch = el.closest('.oc-branch');
            if (open.has(branch.dataset.key)) open.delete(branch.dataset.key); else open.add(branch.dataset.key);
            save();
            setRow(branch);
        } else if ((el = t.closest('.oc-collapse'))) {
            const node = el.closest('.oc-node');
            if (collapsed.has(node.dataset.key)) collapsed.delete(node.dataset.key); else collapsed.add(node.dataset.key);
            save();
            applyState();
        } else if ((el = t.closest('[data-oc-action]'))) {
            const unit = unitOf(el);
            el.closest('[popover]').hidePopover();
            const action = el.dataset.ocAction;
            if (action === 'add') openPersonDialog(unit, el.dataset.role);
            else if (action === 'rename') openUnitDialog(unit);
            else if (action === 'parent') openParentDialog(unit);
            else if (action === 'delete') openDialog('ocDeleteDialog', unit);
        } else if ((el = t.closest('.oc-person-remove'))) {
            const id = el.closest('.oc-person').dataset.membershipId;
            post(ENDPOINTS.membershipDelete.replace('/0/', `/${id}/`)).catch(showError);
        }
    });

    // Remember which member lists are open. `toggle` does not bubble: capture it.
    document.addEventListener('toggle', (e) => {
        const t = e.target;
        if (t.matches && t.matches('details.oc-members')) {
            if (t.open) open.add(t.dataset.key); else open.delete(t.dataset.key);
            save();
        } else if (t.matches && t.matches('.reviewee-popover') && e.newState === 'open') {
            placePopover(t);
        }
    }, true);

    function placePopover(panel) {
        const button = document.querySelector(`[popovertarget="${panel.id}"]`);
        if (!button) return;
        const b = button.getBoundingClientRect();
        panel.style.left = Math.max(8, Math.min(b.right - panel.offsetWidth, innerWidth - panel.offsetWidth - 8)) + 'px';
        panel.style.top = (b.bottom + panel.offsetHeight + 8 <= innerHeight
            ? b.bottom + 8 : Math.max(8, b.top - panel.offsetHeight - 8)) + 'px';
    }

    // Close menus on scroll; their fixed position would otherwise drift away.
    document.addEventListener('scroll', () => {
        document.querySelectorAll('.reviewee-popover:popover-open').forEach(p => p.hidePopover());
    }, true);

    // ------------------------------------------------------------ zoom and pan

    function tree() { return chart.querySelector('.oc-tree'); }

    function setZoom(z) {
        state.zoom = Math.round(Math.min(1.5, Math.max(0.3, z)) * 10) / 10;
        if (tree()) tree().style.zoom = state.zoom;
        board.querySelector('.oc-zoom-level').textContent = Math.round(state.zoom * 100) + '%';
    }

    function fitZoom() {
        const t = tree();
        if (!t) return 1;
        const before = t.style.zoom;
        t.style.zoom = 1;
        const z = Math.min(1, (chart.clientWidth - 16) / t.scrollWidth, (chart.clientHeight - 16) / t.scrollHeight);
        t.style.zoom = before;
        return z;
    }

    let pan = null;
    chart.addEventListener('pointerdown', (e) => {
        // Pointer capture would retarget the click to the viewport, so never pan from a control.
        if (e.button !== 0 || e.target.closest('.oc-unit, button, a, input, select')) return;
        pan = { x: e.clientX, y: e.clientY, left: chart.scrollLeft, top: chart.scrollTop };
        chart.setPointerCapture(e.pointerId);
        chart.classList.add('oc-panning');
    });
    chart.addEventListener('pointermove', (e) => {
        if (!pan) return;
        chart.scrollLeft = pan.left - (e.clientX - pan.x);
        chart.scrollTop = pan.top - (e.clientY - pan.y);
    });
    const endPan = () => { pan = null; chart.classList.remove('oc-panning'); };
    chart.addEventListener('pointerup', endPan);
    chart.addEventListener('pointercancel', endPan);

    // ------------------------------------------------------------ drag and drop

    // People: onto a zone (manager or members), onto a unit (as member), or onto
    // the pool (out of the unit). Units, in the outline: onto another unit.
    let drag = null;

    document.addEventListener('dragstart', (e) => {
        const person = e.target.closest && e.target.closest('.oc-person');
        const row = e.target.closest && e.target.closest('.oc-row');
        if (person) {
            drag = { kind: 'person', el: person, reviewee: person.dataset.revieweeUuid,
                     source: person.dataset.unitUuid || null, membership: person.dataset.membershipId || null };
        } else if (row) {
            drag = { kind: 'unit', el: row, unit: row.closest('.oc-branch').dataset.unitUuid };
        } else {
            return;
        }
        e.stopPropagation();
        drag.el.classList.add('oc-dragging');
        e.dataTransfer.effectAllowed = 'copyMove';
        e.dataTransfer.setData('text/plain', '');
    });

    document.addEventListener('dragend', () => {
        if (drag) drag.el.classList.remove('oc-dragging');
        drag = null;
        markTarget(null);
    });

    function dropTarget(el) {
        if (!drag || !el.closest) return null;
        if (drag.kind === 'unit') {
            const branch = el.closest('.oc-branch');
            return branch && branch.dataset.unitUuid !== drag.unit ? branch.querySelector(':scope > .oc-row') : null;
        }
        if (el.closest('[data-pool]')) return drag.source ? el.closest('[data-pool]') : null;
        return el.closest('.oc-zone') || el.closest('.oc-unit') || el.closest('.oc-row');
    }

    let marked = null;
    function markTarget(el) {
        if (marked === el) return;
        if (marked) marked.classList.remove('oc-drop-target');
        marked = el;
        if (el) el.classList.add('oc-drop-target');
    }

    document.addEventListener('dragover', (e) => {
        const target = dropTarget(e.target);
        markTarget(target);
        if (!target) return;
        e.preventDefault();
        e.dataTransfer.dropEffect = (drag.kind === 'person' && drag.source && !copying(e)) ? 'move' : 'copy';
    });

    const copying = (e) => e.altKey || e.ctrlKey;

    document.addEventListener('drop', (e) => {
        const target = dropTarget(e.target);
        markTarget(null);
        if (!target) return;
        e.preventDefault();
        const d = drag;
        if (d.kind === 'unit') {
            post(unitUrl('unitSetParent', d.unit), { parent_unit_uuid: target.closest('.oc-branch').dataset.unitUuid }).catch(showError);
            return;
        }
        if (target.matches('[data-pool]')) {
            post(ENDPOINTS.membershipDelete.replace('/0/', `/${d.membership}/`)).catch(showError);
            return;
        }
        const unit = target.closest('[data-unit-uuid]').dataset.unitUuid;
        const role = target.dataset.role || 'member';
        const params = { unit_uuid: unit, reviewee_uuid: d.reviewee, role };
        if (d.source && !copying(e)) {
            params.mode = 'move';
            params.source_unit_uuid = d.source;
        }
        post(ENDPOINTS.membershipCreate, params).catch(showError);
    });

    // ------------------------------------------------------------ pool search

    document.addEventListener('input', (e) => {
        if (!e.target.matches('.oc-pool-search')) return;
        const q = e.target.value.trim().toLowerCase();
        pool.querySelectorAll('.oc-person').forEach(p => { p.hidden = q && !p.dataset.search.includes(q); });
    });

    applyState();
    // A tree wider than the screen opens centred on its top, not on its left edge.
    chart.scrollLeft = (chart.scrollWidth - chart.clientWidth) / 2;
})();
