// Email previews, and the dialog that asks for the sender's names before a form sends email.
(function () {
    'use strict';

    // The fields that change the email are in the same form or dialog as the preview.
    function scopeOf(box) {
        return box.closest('form, dialog') || document;
    }

    function refresh(box) {
        const url = new URL(box.dataset.emailPreview, location.href);
        scopeOf(box).querySelectorAll('[data-preview-field]').forEach(function (field) {
            if (field.value) url.searchParams.set(field.name, field.value);
        });
        fetch(url, {headers: {'Accept': 'application/json'}})
            .then(function (response) { return response.json(); })
            .then(function (email) {
                box.querySelector('[data-email-subject]').textContent = email.subject;
                box.querySelector('iframe').srcdoc = email.html;
            })
            .catch(function () { /* The preview is a help. The form works without it. */ });
    }

    document.querySelectorAll('[data-email-preview]').forEach(function (box) {
        let timer;
        function later(event) {
            if (!event.target.matches('[data-preview-field]')) return;
            clearTimeout(timer);
            timer = setTimeout(function () { refresh(box); }, 250);
        }
        scopeOf(box).addEventListener('input', later);
        scopeOf(box).addEventListener('change', later);
        if (!box.hasAttribute('data-email-preview-lazy')) refresh(box);
    });

    const dialog = document.getElementById('senderIdentityDialog');
    if (!dialog) return;

    const box = dialog.querySelector('[data-email-preview]');
    const error = dialog.querySelector('[data-identity-error]');
    let waiting = null;
    let saved = false;

    // In the capture phase, so that no other handler of the form runs before the names are saved.
    document.addEventListener('submit', function (event) {
        const form = event.target;
        const kind = (event.submitter && event.submitter.dataset.sendsMail) || form.dataset.sendsMail;
        if (saved || !kind || dialog.contains(form)) return;
        event.preventDefault();
        event.stopPropagation();
        waiting = {form: form, submitter: event.submitter};
        const url = new URL(box.dataset.emailPreview, location.href);
        url.searchParams.set('kind', kind);
        box.dataset.emailPreview = url.pathname + url.search;
        refresh(box);
        dialog.showModal();
    }, true);

    dialog.querySelector('[data-identity-cancel]').addEventListener('click', function () { dialog.close(); });

    dialog.querySelector('form').addEventListener('submit', function (event) {
        event.preventDefault();
        fetch(event.target.action, {method: 'POST', body: new FormData(event.target)})
            .then(function (response) {
                if (!response.ok) throw new Error(response.status);
                saved = true;
                dialog.close();
                waiting.form.requestSubmit(waiting.submitter);
            })
            .catch(function () { error.hidden = false; });
    });
})();
