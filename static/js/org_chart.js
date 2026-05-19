/**
 * Org-chart editor glue.
 *
 * Adaptive UX:
 *   - Every team renders `filled chips + 1 trailing [+] empty slot` for each
 *     tier. Adding someone appends the next chip; a fresh [+] appears.
 *   - Teams form a real tree: a team whose manager is a member of another
 *     team nests visually inside that member's slot.
 *   - The new-team modal takes just a name (no shape config).
 *
 * All mutations return the full tree HTML; the client replaces `#ocTeams`
 * innerHTML in one go. Predictable and simple.
 */
(function () {
    'use strict';

    const PLACEHOLDER_UUID = '00000000-0000-0000-0000-000000000000';
    const PLACEHOLDER_ID = '/0/';

    function csrf() {
        const el = document.querySelector('[name=csrfmiddlewaretoken]');
        if (el) return el.value;
        const m = document.cookie.match(/csrftoken=([^;]+)/);
        return m ? m[1] : '';
    }

    async function postForm(url, params) {
        const body = new URLSearchParams(params);
        const resp = await fetch(url, {
            method: 'POST',
            credentials: 'same-origin',
            headers: {
                'X-CSRFToken': csrf(),
                'Accept': 'application/json',
                'Content-Type': 'application/x-www-form-urlencoded',
            },
            body: body.toString(),
        });
        const data = await resp.json().catch(() => ({}));
        if (!resp.ok) {
            throw new Error(data.error || `Request failed (${resp.status})`);
        }
        return data;
    }

    function applyChange(data) {
        if (!data) return;
        const $teams = document.getElementById('ocTeams');
        if (data.tree_html !== undefined) {
            if (data.tree_html.trim()) {
                $teams.innerHTML = data.tree_html;
            } else {
                $teams.innerHTML = `
                    <div class="oc-empty-state">
                        <p style="font-size: 1.125rem; font-weight: 600; margin-bottom: 0.5rem;">No teams yet</p>
                        <p style="color: var(--text-secondary);">Click <strong>+ New team</strong> to create your first pyramid.</p>
                    </div>`;
            }
        }
        if (data.unplaced_html !== undefined) {
            document.getElementById('ocUnplaced').innerHTML = data.unplaced_html;
        }
        bindAll();
    }

    function showError(msg) {
        alert(msg);
    }

    // ------------------------------------------------------------------ modal

    const $backdrop = document.getElementById('ocTeamModalBackdrop');
    const $form = document.getElementById('ocTeamForm');
    const $dTitle = document.getElementById('ocTeamDialogTitle');
    const $dName = document.getElementById('ocTeamName');
    const $dSubmit = document.getElementById('ocTeamDialogSubmit');
    const $dCancel = document.getElementById('ocTeamDialogCancel');
    const $dErr = document.getElementById('ocTeamDialogError');

    let dialogMode = 'create'; // 'create' | 'rename'
    let dialogTeamUuid = null;

    function openDialog(mode, opts = {}) {
        dialogMode = mode;
        dialogTeamUuid = opts.teamUuid || null;
        $dErr.hidden = true;
        if (mode === 'create') {
            $dTitle.textContent = 'New team';
            $dName.value = '';
            $dSubmit.textContent = 'Create';
        } else if (mode === 'rename') {
            $dTitle.textContent = 'Rename team';
            $dName.value = opts.name || '';
            $dSubmit.textContent = 'Save';
        }
        $backdrop.hidden = false;
        document.body.style.overflow = 'hidden';
        setTimeout(() => $dName.focus(), 10);
    }

    function closeDialog() {
        $backdrop.hidden = true;
        document.body.style.overflow = '';
    }

    $dCancel.addEventListener('click', (e) => {
        e.preventDefault();
        closeDialog();
    });
    $backdrop.addEventListener('click', (e) => {
        if (e.target === $backdrop) closeDialog();
    });
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape' && !$backdrop.hidden) closeDialog();
    });

    $form.addEventListener('submit', async (e) => {
        e.preventDefault();
        $dErr.hidden = true;
        const name = $dName.value.trim();
        if (!name) {
            $dErr.textContent = 'Team name is required.';
            $dErr.hidden = false;
            return;
        }
        try {
            let data;
            if (dialogMode === 'create') {
                data = await postForm(window.OC_ENDPOINTS.teamCreate, { name });
            } else {
                const url = window.OC_ENDPOINTS.teamUpdate.replace(PLACEHOLDER_UUID, dialogTeamUuid);
                data = await postForm(url, { name });
            }
            applyChange(data);
            closeDialog();
        } catch (err) {
            $dErr.textContent = err.message;
            $dErr.hidden = false;
        }
    });

    document.getElementById('ocNewTeamBtn').addEventListener('click', () => {
        openDialog('create');
    });

    // ---------------------------------------------------------- team actions

    function bindTeamActions() {
        document.querySelectorAll('.oc-team-rename').forEach(btn => {
            if (btn._bound) return;
            btn._bound = true;
            btn.addEventListener('click', () => {
                openDialog('rename', {
                    teamUuid: btn.dataset.teamUuid,
                    name: btn.dataset.teamName,
                });
            });
        });

        document.querySelectorAll('.oc-team-delete').forEach(btn => {
            if (btn._bound) return;
            btn._bound = true;
            btn.addEventListener('click', async () => {
                const name = btn.dataset.teamName;
                if (!confirm(`Delete team "${name}"? All of its slot assignments will be removed. (People stay in Blik — they just return to the unplaced pool if they aren't on any other team.)`)) return;
                try {
                    const url = window.OC_ENDPOINTS.teamDelete.replace(PLACEHOLDER_UUID, btn.dataset.teamUuid);
                    applyChange(await postForm(url, {}));
                } catch (err) {
                    showError(err.message);
                }
            });
        });

        document.querySelectorAll('.oc-team-set-parent').forEach(btn => {
            if (btn._bound) return;
            btn._bound = true;
            btn.addEventListener('click', () => {
                openReportToModal(btn.dataset.teamUuid, btn.dataset.teamName);
            });
        });
    }

    // ---------------------------------------------------------- report-to modal

    const $reportBackdrop = document.getElementById('ocReportToBackdrop');
    const $reportIntro = document.getElementById('ocReportToIntro');
    const $reportList = document.getElementById('ocReportToList');
    const $reportErr = document.getElementById('ocReportToError');
    const $reportCancel = document.getElementById('ocReportToCancel');

    function closeReportModal() {
        $reportBackdrop.hidden = true;
        $reportList.innerHTML = '';
        $reportErr.hidden = true;
        document.body.style.overflow = '';
    }

    $reportCancel.addEventListener('click', (e) => {
        e.preventDefault();
        closeReportModal();
    });
    $reportBackdrop.addEventListener('click', (e) => {
        if (e.target === $reportBackdrop) closeReportModal();
    });
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape' && !$reportBackdrop.hidden) closeReportModal();
    });

    function openReportToModal(childUuid, childName) {
        // Collect every other team on the page (read from the rendered DOM).
        // The server will reject descendants-of-self + no-manager cases, so
        // we list them all and surface the error if chosen.
        const others = [];
        document.querySelectorAll('.oc-team-card').forEach(card => {
            const uuid = card.dataset.teamUuid;
            if (!uuid || uuid === childUuid) return;
            const nameEl = card.querySelector('.oc-team-name');
            const name = nameEl ? nameEl.textContent.trim() : uuid;
            others.push({ uuid, name });
        });

        $reportIntro.textContent = `Pick the team "${childName}" should report to. Its first manager will be added as a member of that team.`;
        $reportErr.hidden = true;

        if (others.length === 0) {
            $reportList.innerHTML = `
                <p style="color: var(--text-secondary); font-size: 0.875rem; margin: 0;">
                    You only have one team. Create another team first, then pick it here.
                </p>`;
        } else {
            $reportList.innerHTML = '';
            others.sort((a, b) => a.name.localeCompare(b.name)).forEach(other => {
                const opt = document.createElement('button');
                opt.type = 'button';
                opt.className = 'oc-team-option';
                opt.textContent = other.name;
                opt.addEventListener('click', async () => {
                    $reportErr.hidden = true;
                    try {
                        const url = window.OC_ENDPOINTS.teamSetParent.replace(PLACEHOLDER_UUID, childUuid);
                        applyChange(await postForm(url, { parent_team_uuid: other.uuid }));
                        closeReportModal();
                    } catch (err) {
                        $reportErr.textContent = err.message;
                        $reportErr.hidden = false;
                    }
                });
                $reportList.appendChild(opt);
            });
        }

        $reportBackdrop.hidden = false;
        document.body.style.overflow = 'hidden';
    }

    // ----------------------------------------------------------- chip remove

    function bindChipRemove() {
        document.querySelectorAll('.oc-chip-remove').forEach(btn => {
            if (btn._bound) return;
            btn._bound = true;
            btn.addEventListener('click', async (e) => {
                e.stopPropagation();
                try {
                    const url = window.OC_ENDPOINTS.membershipDelete.replace(
                        PLACEHOLDER_ID, `/${btn.dataset.membershipId}/`);
                    applyChange(await postForm(url, {}));
                } catch (err) {
                    showError(err.message);
                }
            });
        });
    }

    // --------------------------------------------------------------- drag/drop

    let dragData = null;

    function bindDnD() {
        document.querySelectorAll('.oc-chip[draggable="true"]').forEach(chip => {
            if (chip._bound) return;
            chip._bound = true;
            chip.addEventListener('dragstart', (e) => {
                dragData = {
                    reviewee_uuid: chip.dataset.revieweeUuid,
                    reviewee_name: chip.dataset.revieweeName,
                    source_team_uuid: chip.dataset.teamUuid || null,
                };
                chip.classList.add('oc-chip-dragging');
                e.dataTransfer.effectAllowed = 'copyMove';
                e.dataTransfer.setData('text/plain', chip.dataset.revieweeUuid);
            });
            chip.addEventListener('dragend', () => {
                chip.classList.remove('oc-chip-dragging');
                dragData = null;
            });
        });

        // Drop targets: the trailing [+] empty slots.
        document.querySelectorAll('.oc-slot-empty').forEach(slot => {
            if (slot._bound) return;
            slot._bound = true;
            slot.addEventListener('dragover', (e) => {
                if (!dragData) return;
                e.preventDefault();
                e.dataTransfer.dropEffect = e.shiftKey ? 'move' : 'copy';
                slot.classList.add('oc-slot-drop-target');
            });
            slot.addEventListener('dragleave', () => {
                slot.classList.remove('oc-slot-drop-target');
            });
            slot.addEventListener('drop', async (e) => {
                e.preventDefault();
                slot.classList.remove('oc-slot-drop-target');
                if (!dragData) return;

                const params = {
                    team_uuid: slot.dataset.teamUuid,
                    reviewee_uuid: dragData.reviewee_uuid,
                    role: slot.dataset.role,
                };
                if (e.shiftKey && dragData.source_team_uuid) {
                    params.mode = 'move';
                    params.source_team_uuid = dragData.source_team_uuid;
                }
                try {
                    applyChange(await postForm(window.OC_ENDPOINTS.membershipCreate, params));
                } catch (err) {
                    showError(err.message);
                }
            });
        });
    }

    // --------------------------------------------------------- empty-slot click

    function bindEmptySlotClick() {
        document.querySelectorAll('.oc-slot-empty').forEach(slot => {
            if (slot._clickBound) return;
            slot._clickBound = true;
            slot.addEventListener('click', (e) => {
                e.stopPropagation();
                openSlotPicker(slot);
            });
            slot.addEventListener('keydown', (e) => {
                if (e.key === 'Enter' || e.key === ' ') {
                    e.preventDefault();
                    openSlotPicker(slot);
                }
            });
        });
    }

    function openSlotPicker(slot) {
        document.querySelectorAll('.oc-slot-picker-open').forEach(el => {
            el.classList.remove('oc-slot-picker-open');
            const p = el.querySelector('.reviewee-picker');
            if (p) p.remove();
        });

        slot.classList.add('oc-slot-picker-open');
        slot.textContent = '';  // clear the "+" sigil
        const holder = document.createElement('div');
        holder.setAttribute('data-reviewee-picker', '');
        holder.setAttribute('data-field-name', '_unused');
        holder.setAttribute('data-placeholder', 'Search or add…');
        slot.appendChild(holder);
        if (typeof window.RevieweePicker === 'function') {
            const instance = new window.RevieweePicker(holder);
            holder._pickerInstance = instance;
            setTimeout(() => {
                const inp = holder.querySelector('.rp-input');
                if (inp) inp.focus();
            }, 10);

            holder.addEventListener('reviewee-picker:change', async (e) => {
                const first = (e.detail.selected || [])[0];
                if (!first) return;
                try {
                    applyChange(await postForm(window.OC_ENDPOINTS.membershipCreate, {
                        team_uuid: slot.dataset.teamUuid,
                        reviewee_uuid: first.uuid,
                        role: slot.dataset.role,
                    }));
                } catch (err) {
                    showError(err.message);
                }
            });
        }

        setTimeout(() => {
            document.addEventListener('click', function handler(ev) {
                if (!slot.contains(ev.target)) {
                    // Re-render from server state rather than manually
                    // restoring the "+" — applyChange already ran on success,
                    // and on cancel we just reload the unchanged server state.
                    slot.classList.remove('oc-slot-picker-open');
                    slot.textContent = '+';
                    const p = slot.querySelector('.reviewee-picker');
                    if (p) p.remove();
                    document.removeEventListener('click', handler);
                }
            });
        }, 50);
    }

    // -------------------------------------------------------- unplaced search

    function bindUnplacedSearch() {
        const $search = document.querySelector('.oc-unplaced-search');
        if (!$search || $search._bound) return;
        $search._bound = true;
        $search.addEventListener('input', () => {
            const q = $search.value.trim().toLowerCase();
            document.querySelectorAll('.oc-chip-unplaced').forEach(c => {
                const hit = !q ||
                    (c.dataset.revieweeName || '').toLowerCase().includes(q) ||
                    (c.dataset.revieweeEmail || '').toLowerCase().includes(q);
                c.style.display = hit ? '' : 'none';
            });
        });
    }

    function bindAll() {
        bindTeamActions();
        bindChipRemove();
        bindDnD();
        bindEmptySlotClick();
        bindUnplacedSearch();
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', bindAll);
    } else {
        bindAll();
    }
})();
