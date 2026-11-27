(() => {
    const overview = document.querySelector('.reviewees-overview');
    document.querySelectorAll('[data-submit-filter]').forEach(field => {
        field.addEventListener('change', () => field.form.requestSubmit());
    });

    const columnToggles = document.querySelectorAll('[data-column-toggle]');
    const storageKey = 'blik.reviewees.columns.v1';
    let savedColumns;
    try { savedColumns = JSON.parse(localStorage.getItem(storageKey)); } catch (_) {}
    const applyColumns = () => {
        columnToggles.forEach(toggle => {
            document.querySelectorAll('[data-reviewee-column="' + toggle.dataset.columnToggle + '"]')
                .forEach(cell => { cell.hidden = !toggle.checked; });
        });
    };
    columnToggles.forEach(toggle => {
        if (savedColumns && typeof savedColumns[toggle.dataset.columnToggle] === 'boolean') {
            toggle.checked = savedColumns[toggle.dataset.columnToggle];
        }
        if (toggle.dataset.columnToggle === 'gap' && overview?.dataset.sort === 'gap') toggle.checked = true;
        toggle.addEventListener('change', () => {
            applyColumns();
            const columns = Object.fromEntries([...columnToggles].map(item => [item.dataset.columnToggle, item.checked]));
            try { localStorage.setItem(storageKey, JSON.stringify(columns)); } catch (_) {}
        });
    });
    applyColumns();

    document.querySelectorAll('[data-reviewee-popover]').forEach(button => {
        const panel = document.getElementById(button.getAttribute('popovertarget'));
        panel.addEventListener('toggle', event => {
            button.setAttribute('aria-expanded', event.newState === 'open');
            if (event.newState !== 'open') return;
            const bounds = button.getBoundingClientRect();
            panel.style.left = Math.max(8, Math.min(bounds.right - panel.offsetWidth, innerWidth - panel.offsetWidth - 8)) + 'px';
            panel.style.top = (bounds.bottom + panel.offsetHeight + 8 <= innerHeight
                ? bounds.bottom + 8 : Math.max(8, bounds.top - panel.offsetHeight - 8)) + 'px';
        });
    });
    // The Reviewers column: hover or focus shows the names behind the numbers. Loaded once per row,
    // on demand, so that the list itself costs no query per person.
    const reviewerLabels = [['manager', 'labelManager'], ['peer', 'labelPeer'], ['direct_report', 'labelDirectReport']];
    const showReviewers = async event => {
        const source = event.target.closest?.('[data-reviewers-url]');
        if (!source) return;
        const tip = source.querySelector('.reviewee-reviewer-tip');
        if (!source.dataset.loaded) {
            source.dataset.loaded = '1';
            try {
                const response = await fetch(source.dataset.reviewersUrl,
                    {headers: {Accept: 'application/json'}, credentials: 'same-origin'});
                const data = await response.json();
                reviewerLabels.forEach(([code, label]) => {
                    // People of the organization by name, other reviewers by their email address
                    const names = (data[code] || []).map(person => person.name).concat(data.emails?.[code] || []);
                    if (!names.length) return;
                    const line = document.createElement('p');
                    const head = document.createElement('strong');
                    head.textContent = overview.dataset[label];
                    line.append(head, ': ' + names.join(', '));
                    tip.append(line);
                });
            } catch (_) {
                delete source.dataset.loaded;
                return;
            }
        }
        if (!tip.childElementCount || !source.matches(':hover, :focus-within') || tip.matches(':popover-open')) return;
        tip.showPopover();
        const bounds = source.getBoundingClientRect();
        tip.style.left = Math.max(8, Math.min(bounds.left, innerWidth - tip.offsetWidth - 8)) + 'px';
        tip.style.top = (bounds.bottom + tip.offsetHeight + 8 <= innerHeight
            ? bounds.bottom + 6 : Math.max(8, bounds.top - tip.offsetHeight - 6)) + 'px';
    };
    const hideReviewers = event => {
        const source = event.target.closest?.('[data-reviewers-url]');
        if (!source || source.contains(event.relatedTarget)) return;
        const tip = source.querySelector('.reviewee-reviewer-tip');
        if (tip.matches(':popover-open')) tip.hidePopover();
    };
    document.addEventListener('pointerover', showReviewers);
    document.addEventListener('focusin', showReviewers);
    document.addEventListener('pointerout', hideReviewers);
    document.addEventListener('focusout', hideReviewers);

    const closePopovers = event => {
        document.querySelectorAll('.reviewee-popover:popover-open').forEach(panel => {
            if (event.type === 'resize' || !panel.contains(event.target)) panel.hidePopover();
        });
    };
    window.addEventListener('resize', closePopovers);
    document.addEventListener('scroll', closePopovers, true);

    // Delegated, so the rows the cycle list's search swaps in keep working.
    document.addEventListener('click', event => {
        const button = event.target.closest('[data-reviewee-dialog]');
        if (button) {
            const panel = button.closest('[popover]');
            if (panel?.matches(':popover-open')) panel.hidePopover();
            const dialog = document.getElementById(button.dataset.revieweeDialog);
            // An overflow item disappears when its popover closes. Restore
            // focus to the visible menu trigger when this dialog is dismissed.
            const returnFocus = panel
                ? document.querySelector('[popovertarget="' + panel.id + '"]') : button;
            dialog.addEventListener('close', () => returnFocus.focus(), {once: true});
            dialog.showModal();
            dialog.querySelector('.card-body').scrollTop = 0;
        } else if (event.target.closest('[data-close-reviewee-dialog]')) {
            event.target.closest('dialog').close();
        } else if (event.target.matches('.reviewee-dialog')) {
            const dialog = event.target;
            const bounds = dialog.getBoundingClientRect();
            if (event.clientX < bounds.left || event.clientX > bounds.right ||
                event.clientY < bounds.top || event.clientY > bounds.bottom) dialog.close();
        }
    });
})();
