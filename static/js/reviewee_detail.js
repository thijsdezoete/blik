(() => {
    const form = document.querySelector('[data-reviewers-form]');
    if (!form) return;
    const listed = ['manager', 'peer', 'direct_report'];
    const threshold = Number(form.dataset.threshold);
    const row = category => form.querySelector('.rv-cat[data-category="' + category + '"]');
    const picker = category => row(category).querySelector('[data-reviewee-picker]')?._pickerInstance;
    const field = category => form.querySelector('textarea[name="' + category + '_emails"]');
    const emailsIn = category => field(category).value.split(/[,\n]+/).filter(email => email.trim());
    const count = category => (picker(category)?.getSelected().length || 0) + emailsIn(category).length;

    const showThresholds = () => {
        form.querySelectorAll('[data-threshold-line]').forEach(line => {
            line.hidden = count(line.closest('.rv-cat').dataset.category) >= threshold;
        });
    };
    form.addEventListener('input', showThresholds);
    form.addEventListener('reviewee-picker:change', showThresholds);

    // The fill buttons replace what the card shows. Nothing is saved until "Save reviewers".
    form.querySelectorAll('[data-fill]').forEach(button => {
        button.addEventListener('click', async () => {
            const response = await fetch(form.dataset.fillUrl + '&source=' + button.dataset.fill, {
                headers: {'Accept': 'application/json'}, credentials: 'same-origin',
            });
            if (!response.ok) return;
            const data = await response.json();
            listed.forEach(category => {
                const people = data[category] || [];
                const emails = data.emails[category] || [];
                const chips = picker(category);
                if (chips) {
                    chips.getSelected().forEach(person => chips.remove(person.uuid));
                    people.forEach(person => chips.add(person));
                    field(category).value = emails.join(', ');
                } else {
                    // Without the picker, people are edited as their email addresses.
                    field(category).value = people.map(person => person.email).concat(emails).join(', ');
                }
            });
            Object.entries(data.flags).forEach(([name, on]) => {
                const box = form.querySelector('input[name="' + name + '"]');
                if (box) box.checked = on;
            });
            const details = form.querySelector('details');
            if (details && listed.some(category => (data.emails[category] || []).length)) details.open = true;
            const line = form.querySelector('[data-source-line]');
            line.textContent = line.dataset[data.source] || '';
            line.hidden = !line.textContent;
            showThresholds();
        });
    });

    // The dialog names the number of reviewers that the card shows now.
    const start = document.querySelector('[data-reviewee-dialog="start-review-detail"]');
    start?.addEventListener('click', () => {
        const invited = listed.filter(category => form.querySelector('input[name="include_' + category + '"]').checked)
            .reduce((sum, category) => sum + count(category), 0);
        document.querySelector('[data-reviewer-count]').textContent = interpolate(ngettext(
            '%(counter)s reviewer gets an invitation.', '%(counter)s reviewers get an invitation.', invited),
            {counter: invited}, true);
    });
})();
