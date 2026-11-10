/**
 * RevieweePicker — autocomplete chip component for selecting existing
 * Reviewee records (or creating new ones inline).
 *
 * Markup contract:
 *   <div data-reviewee-picker
 *        data-field-name="self_reviewees"
 *        data-initial='[{"uuid":"...","name":"...","email":"..."}]'
 *        data-placeholder="Add a peer..."></div>
 *
 * For each selected reviewee the picker emits a hidden input:
 *   <input type="hidden" name="self_reviewees" value="<uuid>">
 * so the form submits a multi-valued field readable with getlist().
 *
 * Requires a single CSRF token available on the page (any element with
 * name=csrfmiddlewaretoken, e.g. from {% csrf_token %}).
 */
(function () {
    'use strict';

    const API_SEARCH_URL = '/api/v1/reviewees/';
    const QUICK_CREATE_URL = '/dashboard/reviewees/quick-create/';
    const DEBOUNCE_MS = 250;
    const MIN_QUERY = 1;

    function getCookie(name) {
        const match = document.cookie.match(new RegExp('(^| )' + name + '=([^;]+)'));
        return match ? decodeURIComponent(match[2]) : null;
    }

    function getCsrfToken() {
        const input = document.querySelector('[name=csrfmiddlewaretoken]');
        if (input) return input.value;
        return getCookie('csrftoken') || '';
    }

    function escapeHtml(s) {
        return String(s || '').replace(/[&<>"']/g, c => ({
            '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
        }[c]));
    }

    function debounce(fn, ms) {
        let t;
        return function (...args) {
            clearTimeout(t);
            t = setTimeout(() => fn.apply(this, args), ms);
        };
    }

    class RevieweePicker {
        constructor(root) {
            this.root = root;
            this.fieldName = root.dataset.fieldName || 'reviewees';
            this.placeholder = root.dataset.placeholder || gettext('Add a person…');
            this.selected = new Map(); // uuid -> {uuid, name, email}

            let initial = [];
            if (root.dataset.initial) {
                try { initial = JSON.parse(root.dataset.initial); } catch (e) { initial = []; }
            }

            this._buildDom();
            initial.forEach(p => this.add(p, { silent: true }));
            this._renderHidden();
            this._bind();
        }

        _buildDom() {
            this.root.classList.add('reviewee-picker');
            this.root.innerHTML = `
                <div class="rp-chips" role="list"></div>
                <div class="rp-input-row">
                    <input type="text" class="rp-input" placeholder="${escapeHtml(this.placeholder)}"
                           autocomplete="off" aria-label="${escapeHtml(gettext('Search for a person'))}">
                    <div class="rp-dropdown" hidden></div>
                </div>
                <div class="rp-hidden"></div>
            `;
            this.$chips = this.root.querySelector('.rp-chips');
            this.$input = this.root.querySelector('.rp-input');
            this.$dropdown = this.root.querySelector('.rp-dropdown');
            this.$hidden = this.root.querySelector('.rp-hidden');
        }

        _bind() {
            const search = debounce(() => this._search(), DEBOUNCE_MS);
            this.$input.addEventListener('input', search);
            this.$input.addEventListener('focus', () => {
                if (this.$input.value.trim().length >= MIN_QUERY) this._search();
            });
            this.$input.addEventListener('keydown', e => this._onKey(e));
            document.addEventListener('click', e => {
                // The path, not the target: a click that re-renders the dropdown has detached its target by now
                if (!e.composedPath().includes(this.root)) this._closeDropdown();
            });
            this.$chips.addEventListener('click', e => {
                const btn = e.target.closest('.rp-chip-remove');
                if (btn) {
                    const uuid = btn.closest('.rp-chip').dataset.uuid;
                    this.remove(uuid);
                }
            });
        }

        _onKey(e) {
            const items = this.$dropdown.querySelectorAll('.rp-option');
            const current = this.$dropdown.querySelector('.rp-option.active');
            if (e.key === 'ArrowDown') {
                e.preventDefault();
                this._moveActive(items, current, 1);
            } else if (e.key === 'ArrowUp') {
                e.preventDefault();
                this._moveActive(items, current, -1);
            } else if (e.key === 'Enter') {
                if (current) { e.preventDefault(); current.click(); }
            } else if (e.key === 'Escape') {
                this._closeDropdown();
            } else if (e.key === 'Backspace' && !this.$input.value) {
                // remove last chip
                const last = [...this.selected.values()].pop();
                if (last) { e.preventDefault(); this.remove(last.uuid); }
            }
        }

        _moveActive(items, current, step) {
            if (!items.length) return;
            let idx = current ? [...items].indexOf(current) : -1;
            idx = (idx + step + items.length) % items.length;
            items.forEach(i => i.classList.remove('active'));
            items[idx].classList.add('active');
            items[idx].scrollIntoView({ block: 'nearest' });
        }

        _closeDropdown() {
            this.$dropdown.hidden = true;
            this.$dropdown.innerHTML = '';
        }

        async _search() {
            const q = this.$input.value.trim();
            if (q.length < MIN_QUERY) { this._closeDropdown(); return; }

            let results = [];
            try {
                const resp = await fetch(`${API_SEARCH_URL}?search=${encodeURIComponent(q)}`, {
                    headers: { 'Accept': 'application/json' },
                    credentials: 'same-origin',
                });
                if (resp.ok) {
                    const data = await resp.json();
                    results = Array.isArray(data) ? data : (data.results || []);
                }
            } catch (e) {
                // Network error — just show the create option.
            }

            const filtered = results.filter(r => !this.selected.has(r.uuid));
            this._renderDropdown(q, filtered);
        }

        _renderDropdown(query, results) {
            const frag = document.createElement('div');
            results.slice(0, 10).forEach(r => {
                const opt = document.createElement('div');
                opt.className = 'rp-option';
                opt.dataset.uuid = r.uuid;
                opt.innerHTML = `
                    <span class="rp-opt-name">${escapeHtml(r.name)}</span>
                    <span class="rp-opt-email">${escapeHtml(r.email)}</span>
                `;
                opt.addEventListener('click', () => {
                    this.add({ uuid: r.uuid, name: r.name, email: r.email });
                    this.$input.value = '';
                    this._closeDropdown();
                    this.$input.focus();
                });
                frag.appendChild(opt);
            });

            const create = document.createElement('div');
            create.className = 'rp-option rp-option-create';
            create.innerHTML = `
                <span class="rp-opt-plus">＋</span>
                <span class="rp-opt-name">${escapeHtml(query
                    ? interpolate(gettext('Create new reviewee “%(name)s”'), {name: query}, true)
                    : gettext('Create new reviewee'))}</span>
            `;
            create.addEventListener('click', () => this._openCreateForm(query));
            frag.appendChild(create);

            this.$dropdown.innerHTML = '';
            this.$dropdown.appendChild(frag);
            this.$dropdown.hidden = false;
            const first = this.$dropdown.querySelector('.rp-option');
            if (first) first.classList.add('active');
        }

        _openCreateForm(prefilled) {
            // Guess: if prefilled looks like an email, use it as email; otherwise as name.
            const looksLikeEmail = /@/.test(prefilled);
            const name = looksLikeEmail ? '' : prefilled;
            const email = looksLikeEmail ? prefilled : '';

            this.$dropdown.innerHTML = `
                <div class="rp-create-form">
                    <div class="rp-create-row">
                        <input type="text" class="rp-cf-name" placeholder="${escapeHtml(gettext('Full name'))}"
                               value="${escapeHtml(name)}">
                    </div>
                    <div class="rp-create-row">
                        <input type="email" class="rp-cf-email" placeholder="email@example.com" value="${escapeHtml(email)}">
                    </div>
                    <div class="rp-create-error" hidden></div>
                    <div class="rp-create-actions">
                        <button type="button" class="btn btn-primary btn-sm rp-cf-add">
                            ${escapeHtml(gettext('Add'))}
                        </button>
                        <button type="button" class="btn btn-secondary btn-sm rp-cf-cancel">
                            ${escapeHtml(gettext('Cancel'))}
                        </button>
                    </div>
                </div>
            `;
            this.$dropdown.hidden = false;
            // No <form> of its own: the picker usually sits inside one, and HTML drops a nested form
            const form = this.$dropdown.querySelector('.rp-create-form');
            const $name = form.querySelector('.rp-cf-name');
            const $email = form.querySelector('.rp-cf-email');
            const $err = form.querySelector('.rp-create-error');

            ($name.value ? $email : $name).focus();

            form.querySelector('.rp-cf-cancel').addEventListener('click', () => this._closeDropdown());
            const submit = async () => {
                $err.hidden = true;
                const body = new URLSearchParams({
                    name: $name.value.trim(),
                    email: $email.value.trim(),
                });
                try {
                    const resp = await fetch(QUICK_CREATE_URL, {
                        method: 'POST',
                        headers: {
                            'X-CSRFToken': getCsrfToken(),
                            'Content-Type': 'application/x-www-form-urlencoded',
                            'Accept': 'application/json',
                        },
                        credentials: 'same-origin',
                        body: body.toString(),
                    });
                    const data = await resp.json().catch(() => ({}));
                    if (!resp.ok) {
                        $err.textContent = data.error || gettext('Could not create reviewee.');
                        $err.hidden = false;
                        return;
                    }
                    this.add({ uuid: data.uuid, name: data.name, email: data.email });
                    this.$input.value = '';
                    this._closeDropdown();
                    this.$input.focus();
                } catch (err) {
                    $err.textContent = gettext('Network error. Try again.');
                    $err.hidden = false;
                }
            };
            form.querySelector('.rp-cf-add').addEventListener('click', submit);
            form.addEventListener('keydown', e => {
                if (e.key === 'Enter' && e.target.matches('input')) {
                    e.preventDefault();
                    submit();
                }
            });
        }

        add(person, { silent } = {}) {
            if (!person || !person.uuid || this.selected.has(person.uuid)) return;
            this.selected.set(person.uuid, person);
            this._renderChip(person);
            this._renderHidden();
            if (!silent) this._fire('change');
        }

        remove(uuid) {
            if (!this.selected.has(uuid)) return;
            this.selected.delete(uuid);
            const chip = this.$chips.querySelector(`[data-uuid="${CSS.escape(uuid)}"]`);
            if (chip) chip.remove();
            this._renderHidden();
            this._fire('change');
        }

        _renderChip(person) {
            const chip = document.createElement('span');
            chip.className = 'rp-chip';
            chip.setAttribute('role', 'listitem');
            chip.dataset.uuid = person.uuid;
            const label = interpolate(gettext('Remove %(name)s'), {name: person.name || person.email}, true);
            chip.innerHTML = `
                <span class="rp-chip-name">${escapeHtml(person.name || person.email)}</span>
                <button type="button" class="rp-chip-remove" aria-label="${escapeHtml(label)}">×</button>
            `;
            this.$chips.appendChild(chip);
        }

        _renderHidden() {
            this.$hidden.innerHTML = '';
            for (const p of this.selected.values()) {
                const inp = document.createElement('input');
                inp.type = 'hidden';
                inp.name = this.fieldName;
                inp.value = p.uuid;
                this.$hidden.appendChild(inp);
            }
        }

        _fire(name) {
            this.root.dispatchEvent(new CustomEvent(`reviewee-picker:${name}`, {
                bubbles: true,
                detail: { selected: [...this.selected.values()] },
            }));
        }

        getSelected() {
            return [...this.selected.values()];
        }
    }

    function initAll(scope) {
        (scope || document).querySelectorAll('[data-reviewee-picker]').forEach(el => {
            if (!el._pickerInstance) el._pickerInstance = new RevieweePicker(el);
        });
    }

    window.RevieweePicker = RevieweePicker;
    window.initRevieweePickers = initAll;

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', () => initAll());
    } else {
        initAll();
    }
})();
