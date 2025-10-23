document.addEventListener('DOMContentLoaded', function() {
    const form = document.getElementById('feedback-form');
    const submitBtn = document.getElementById('submit-btn');
    const errorContainer = document.getElementById('error-container');

    if (form) {
        form.addEventListener('submit', async function(e) {
            e.preventDefault();

            // Disable submit button
            submitBtn.disabled = true;
            submitBtn.textContent = 'Submitting...';

            // Clear previous errors
            errorContainer.innerHTML = '';
            errorContainer.style.display = 'none';

            // Get form data
            const formData = new FormData(form);

            try {
                const response = await fetch(form.action, {
                    method: 'POST',
                    body: formData,
                    headers: {
                        'X-Requested-With': 'XMLHttpRequest'
                    }
                });

                const data = await response.json();

                if (response.ok && data.success) {
                    // Redirect to complete page
                    window.location.href = data.redirect;
                } else {
                    // Show errors
                    if (data.errors && data.errors.length > 0) {
                        showErrors(data.errors);
                    } else if (data.error) {
                        showErrors([data.error]);
                    } else {
                        showErrors(['An error occurred. Please try again.']);
                    }

                    // Re-enable submit button
                    submitBtn.disabled = false;
                    submitBtn.textContent = 'Submit Feedback';
                }
            } catch (error) {
                showErrors(['Network error. Please check your connection and try again.']);
                submitBtn.disabled = false;
                submitBtn.textContent = 'Submit Feedback';
            }
        });
    }

    function showErrors(errors) {
        errorContainer.style.display = 'block';
        const errorList = document.createElement('ul');
        errorList.className = 'error-list';

        errors.forEach(error => {
            const li = document.createElement('li');
            li.textContent = error;
            errorList.appendChild(li);
        });

        errorContainer.innerHTML = '<strong>Please fix the following errors:</strong>';
        errorContainer.appendChild(errorList);

        // Scroll to errors
        errorContainer.scrollIntoView({ behavior: 'smooth', block: 'center' });
    }
});
