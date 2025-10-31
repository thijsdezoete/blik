document.addEventListener('DOMContentLoaded', function() {
    const form = document.getElementById('feedback-form');
    const sections = Array.from(document.querySelectorAll('.section'));
    const prevBtn = document.getElementById('prev-btn');
    const nextBtn = document.getElementById('next-btn');
    const submitBtn = document.getElementById('submit-btn');
    const progressFill = document.querySelector('.progress-fill');
    const progressText = document.querySelector('.progress-text');
    const errorContainer = document.getElementById('error-container');

    let currentStep = 0;

    function showStep(stepIndex) {
        sections.forEach((section, index) => {
            section.classList.toggle('active', index === stepIndex);
        });

        prevBtn.style.display = stepIndex === 0 ? 'none' : 'block';
        nextBtn.style.display = stepIndex === sections.length - 1 ? 'none' : 'inline-block';
        submitBtn.style.display = stepIndex === sections.length - 1 ? 'inline-block' : 'none';

        const progress = ((stepIndex + 1) / sections.length) * 100;
        progressFill.style.width = progress + '%';
        progressText.textContent = `Step ${stepIndex + 1} of ${sections.length}`;

        window.scrollTo({ top: 0, behavior: 'smooth' });
    }

    function validateCurrentSection() {
        const currentSection = sections[currentStep];
        const requiredInputs = currentSection.querySelectorAll('[required]');

        for (let input of requiredInputs) {
            if (input.type === 'radio') {
                const radioGroup = currentSection.querySelectorAll(`[name="${input.name}"]`);
                const isChecked = Array.from(radioGroup).some(radio => radio.checked);
                if (!isChecked) {
                    return false;
                }
            } else if (input.type === 'textarea' || input.type === 'text') {
                if (!input.value.trim()) {
                    return false;
                }
            }
        }

        // Check multiple choice validators (for checkbox groups)
        const multipleChoiceValidators = currentSection.querySelectorAll('.multiple-choice-validator[data-required="true"]');
        for (let validator of multipleChoiceValidators) {
            const questionId = validator.dataset.questionId;
            const checkboxes = currentSection.querySelectorAll(`input[type="checkbox"][name="question_${questionId}"]`);
            const isAnyChecked = Array.from(checkboxes).some(cb => cb.checked);
            if (!isAnyChecked) {
                return false;
            }
        }

        return true;
    }

    prevBtn.addEventListener('click', function() {
        if (currentStep > 0) {
            currentStep--;
            showStep(currentStep);
            errorContainer.style.display = 'none';
        }
    });

    nextBtn.addEventListener('click', function() {
        if (!validateCurrentSection()) {
            showErrors(['Please answer all required questions before continuing.']);
            return;
        }

        errorContainer.style.display = 'none';

        if (currentStep < sections.length - 1) {
            currentStep++;
            showStep(currentStep);
        }
    });

    if (form) {
        form.addEventListener('submit', async function(e) {
            e.preventDefault();

            if (!validateCurrentSection()) {
                showErrors(['Please answer all required questions.']);
                return;
            }

            submitBtn.disabled = true;
            submitBtn.textContent = 'Submitting...';

            errorContainer.innerHTML = '';
            errorContainer.style.display = 'none';

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
                    window.location.href = data.redirect;
                } else {
                    if (data.errors && data.errors.length > 0) {
                        showErrors(data.errors);
                    } else if (data.error) {
                        showErrors([data.error]);
                    } else {
                        showErrors(['An error occurred. Please try again.']);
                    }

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

        errorContainer.innerHTML = '<strong>Please fix the following:</strong>';
        errorContainer.appendChild(errorList);

        errorContainer.scrollIntoView({ behavior: 'smooth', block: 'center' });
    }

    showStep(0);
});
