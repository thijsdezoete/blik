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

    // Org chart: for a manager or direct report the user adds, the server says what the chart has and
    // gives the question to show (empty when the chart has the relation). Only for those who may edit the chart.
    const chartUrl = form.dataset.chartUrl;
    const chartCategories = ['manager', 'direct_report'];
    const known = {};  // category -> uuids the card has seen, so only added people are asked about
    let filling = false;
    const choices = category => row(category).querySelector('[data-chart-choices]');
    const selectedUuids = category => (picker(category)?.getSelected() || []).map(person => person.uuid);
    const choiceOf = (category, uuid) => choices(category).querySelector('[data-chart-choice="' + CSS.escape(uuid) + '"]');

    // Each org chart change the card will make, in the sentence the server put on its choice. Built again
    // when a question comes or goes, also while the start dialog is open: everything listed there is posted.
    const listChartChanges = () => {
        const summary = document.querySelector('[data-chart-summary-list]');
        if (!summary) return;
        summary.replaceChildren(...[...form.querySelectorAll('[data-chart-choices] input:checked[data-chart-summary]')]
            .map(input => Object.assign(document.createElement('li'), {textContent: input.dataset.chartSummary})));
        summary.hidden = !summary.children.length;
    };

    const askChart = async (category, uuid) => {
        let data;
        try {
            const response = await fetch(chartUrl + '?' + new URLSearchParams({person: uuid, category}), {
                headers: {'Accept': 'application/json'}, credentials: 'same-origin',
            });
            if (!response.ok) return;
            data = await response.json();
        } catch (error) {
            return;  // No answer, no question: the chart stays as it is.
        }
        // The person may be gone, or asked about twice, by the time the answer comes.
        if (!data.html || !selectedUuids(category).includes(uuid) || choiceOf(category, uuid)) return;
        choices(category).insertAdjacentHTML('beforeend', data.html);
        listChartChanges();
    };

    const syncChart = category => {
        const now = selectedUuids(category);
        choices(category).querySelectorAll('[data-chart-choice]').forEach(choice => {
            if (!now.includes(choice.dataset.chartChoice)) choice.remove();
        });
        listChartChanges();
        now.filter(uuid => !known[category].includes(uuid)).forEach(uuid => askChart(category, uuid));
        known[category] = now;
    };

    if (chartUrl) {
        form.addEventListener('reviewee-picker:change', event => {
            const category = event.target.closest('.rv-cat')?.dataset.category;
            if (!filling && chartCategories.includes(category)) syncChart(category);
        });
        const startChart = () => chartCategories.forEach(category => {
            // A saved list or the org chart is not new: only the people of a previous review count as added.
            known[category] = form.dataset.source === 'previous' ? [] : selectedUuids(category);
            syncChart(category);
        });
        // A deferred script runs before DOMContentLoaded, when the pickers are built (their listener comes first).
        document.addEventListener('DOMContentLoaded', startChart);
    }

    // The fill buttons replace what the card shows. Nothing is saved until "Save reviewers".
    form.querySelectorAll('[data-fill]').forEach(button => {
        button.addEventListener('click', async () => {
            const error = form.querySelector('[data-fill-error]');
            let data = null;
            try {
                const response = await fetch(form.dataset.fillUrl + '&source=' + button.dataset.fill, {
                    headers: {'Accept': 'application/json'}, credentials: 'same-origin',
                });
                if (response.ok) data = await response.json();
            } catch (failure) {
                data = null;
            }
            error.hidden = Boolean(data);
            if (!data) return;
            filling = true;
            try {
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
            } finally {
                filling = false;
            }
            if (chartUrl) {
                // The people of the previous review count as added; the org chart has its own people already.
                chartCategories.forEach(category => {
                    known[category] = data.source === 'previous' ? [] : selectedUuids(category);
                    choices(category).replaceChildren();
                    syncChart(category);
                });
            }
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
        listChartChanges();
    });
})();
