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

    // Get token from form or data attribute for draft storage
    const feedbackToken = form ? form.dataset.token : null;

    // === Encrypted Local Storage for Drafts ===

    async function deriveKey(token) {
        // Derive an encryption key from the token using PBKDF2
        const encoder = new TextEncoder();
        const keyMaterial = await crypto.subtle.importKey(
            'raw',
            encoder.encode(token),
            'PBKDF2',
            false,
            ['deriveKey']
        );

        // Use a fixed salt based on token hash for deterministic key derivation
        const saltData = await crypto.subtle.digest('SHA-256', encoder.encode(token));

        return crypto.subtle.deriveKey(
            {
                name: 'PBKDF2',
                salt: saltData,
                iterations: 100000,
                hash: 'SHA-256'
            },
            keyMaterial,
            { name: 'AES-GCM', length: 256 },
            false,
            ['encrypt', 'decrypt']
        );
    }

    async function hashToken(token) {
        // Hash the token using SHA-256 to avoid storing it directly
        const encoder = new TextEncoder();
        const data = encoder.encode(token);
        const hashBuffer = await crypto.subtle.digest('SHA-256', data);
        const hashArray = Array.from(new Uint8Array(hashBuffer));
        const hashHex = hashArray.map(b => b.toString(16).padStart(2, '0')).join('');
        return hashHex;
    }

    async function getStorageKey() {
        if (!feedbackToken) return null;
        const hashed = await hashToken(feedbackToken);
        return `feedback_draft_${hashed}`;
    }

    async function encryptData(data, key) {
        const encoder = new TextEncoder();
        const dataString = JSON.stringify(data);
        const iv = crypto.getRandomValues(new Uint8Array(12)); // 96-bit IV for AES-GCM

        const encrypted = await crypto.subtle.encrypt(
            { name: 'AES-GCM', iv: iv },
            key,
            encoder.encode(dataString)
        );

        // Combine IV and encrypted data
        const combined = new Uint8Array(iv.length + encrypted.byteLength);
        combined.set(iv, 0);
        combined.set(new Uint8Array(encrypted), iv.length);

        // Convert to base64 for storage
        return btoa(String.fromCharCode.apply(null, combined));
    }

    async function decryptData(encryptedBase64, key) {
        // Convert from base64
        const combined = Uint8Array.from(atob(encryptedBase64), c => c.charCodeAt(0));

        // Extract IV and encrypted data
        const iv = combined.slice(0, 12);
        const encrypted = combined.slice(12);

        const decrypted = await crypto.subtle.decrypt(
            { name: 'AES-GCM', iv: iv },
            key,
            encrypted
        );

        const decoder = new TextDecoder();
        return JSON.parse(decoder.decode(decrypted));
    }

    async function saveDraft() {
        const storageKey = await getStorageKey();
        if (!storageKey) return;

        const drafts = {};

        // Save all text inputs and textareas
        const textInputs = form.querySelectorAll('input[type="text"], textarea');
        textInputs.forEach(input => {
            if (input.value.trim()) {
                drafts[input.name] = input.value;
            }
        });

        // Save select values
        const selects = form.querySelectorAll('select');
        selects.forEach(select => {
            if (select.value) {
                drafts[select.name] = select.value;
            }
        });

        // Save radio selections
        const radios = form.querySelectorAll('input[type="radio"]:checked');
        radios.forEach(radio => {
            drafts[radio.name] = radio.value;
        });

        // Save checkbox selections
        const checkboxGroups = {};
        const checkboxes = form.querySelectorAll('input[type="checkbox"]:checked');
        checkboxes.forEach(checkbox => {
            if (!checkboxGroups[checkbox.name]) {
                checkboxGroups[checkbox.name] = [];
            }
            checkboxGroups[checkbox.name].push(checkbox.value);
        });
        Object.assign(drafts, checkboxGroups);

        if (Object.keys(drafts).length > 0) {
            try {
                const draftData = {
                    responses: drafts,
                    currentStep: currentStep
                };

                const key = await deriveKey(feedbackToken);
                const encrypted = await encryptData(draftData, key);

                localStorage.setItem(storageKey, encrypted);
                console.log('Draft saved to encrypted storage');
            } catch (e) {
                console.error('Error encrypting draft:', e);
            }
        }
    }

    async function loadDraft() {
        const storageKey = await getStorageKey();
        if (!storageKey) return;

        const stored = localStorage.getItem(storageKey);
        if (!stored) return;

        try {
            const key = await deriveKey(feedbackToken);
            let storedData;

            // Try to decrypt - if it fails, it might be old unencrypted data
            try {
                storedData = await decryptData(stored, key);
            } catch (decryptError) {
                console.log('Attempting to load legacy unencrypted draft');
                storedData = JSON.parse(stored);
            }

            // Handle both old format (direct object) and new format (with responses and currentStep)
            const drafts = storedData.responses || storedData;
            const savedStep = storedData.currentStep;

            let restoredCount = 0;

            // Restore text inputs and textareas
            Object.entries(drafts).forEach(([name, value]) => {
                const input = form.querySelector(`[name="${name}"]`);

                if (!input) return;

                if (input.type === 'radio') {
                    const radio = form.querySelector(`input[type="radio"][name="${name}"][value="${value}"]`);
                    if (radio) {
                        radio.checked = true;
                        restoredCount++;
                    }
                } else if (input.type === 'checkbox') {
                    // Handle checkbox arrays
                    if (Array.isArray(value)) {
                        value.forEach(v => {
                            const checkbox = form.querySelector(`input[type="checkbox"][name="${name}"][value="${v}"]`);
                            if (checkbox) {
                                checkbox.checked = true;
                                restoredCount++;
                            }
                        });
                    }
                } else if (input.tagName === 'SELECT' || input.tagName === 'TEXTAREA' || input.type === 'text') {
                    input.value = value;
                    restoredCount++;
                }
            });

            // Restore step position if saved
            if (savedStep !== undefined && savedStep >= 0 && savedStep < sections.length) {
                currentStep = savedStep;
            }

            if (restoredCount > 0) {
                console.log(`Restored ${restoredCount} draft answers from encrypted storage`);
                // Show a subtle notification
                showDraftRestored(restoredCount, savedStep);
            }
        } catch (e) {
            console.error('Error loading draft:', e);
        }
    }

    async function clearDraft() {
        const storageKey = await getStorageKey();
        if (!storageKey) return;
        localStorage.removeItem(storageKey);
        console.log('Draft cleared from storage');
    }

    function showDraftRestored(count, step) {
        const notification = document.createElement('div');
        notification.style.cssText = 'position: fixed; top: 20px; right: 20px; background: #10b981; color: white; padding: 12px 20px; border-radius: 8px; box-shadow: 0 4px 6px rgba(0,0,0,0.1); z-index: 10000; font-size: 14px;';

        let message = `✓ Restored ${count} draft answer${count > 1 ? 's' : ''}`;
        if (step !== undefined && step > 0) {
            message += ` (Step ${step + 1})`;
        }
        notification.textContent = message;

        document.body.appendChild(notification);

        setTimeout(() => {
            notification.style.transition = 'opacity 0.3s';
            notification.style.opacity = '0';
            setTimeout(() => notification.remove(), 300);
        }, 3000);
    }

    // Auto-save on input changes (debounced)
    let saveTimeout;
    function debouncedSave() {
        clearTimeout(saveTimeout);
        saveTimeout = setTimeout(saveDraft, 1000); // Save 1 second after user stops typing
    }

    async function initialize() {
        if (form && feedbackToken) {
            // Load existing draft on page load
            await loadDraft();
        }

        // Show the appropriate step (will be updated by loadDraft if applicable)
        showStep(currentStep);

        if (form && feedbackToken) {
            // Auto-save on input
            form.addEventListener('input', debouncedSave);
            form.addEventListener('change', debouncedSave);
        }
    }

    initialize();

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

    function validateSection(sectionIndex) {
        const section = sections[sectionIndex];
        const requiredInputs = section.querySelectorAll('[required]');

        for (let input of requiredInputs) {
            if (input.type === 'radio') {
                const radioGroup = section.querySelectorAll(`[name="${input.name}"]`);
                const isChecked = Array.from(radioGroup).some(radio => radio.checked);
                if (!isChecked) {
                    return false;
                }
            } else if (input.tagName === 'SELECT') {
                // Handle select/dropdown elements
                if (!input.value || input.value === '') {
                    return false;
                }
            } else if (input.type === 'textarea' || input.type === 'text') {
                if (!input.value.trim()) {
                    return false;
                }
            }
        }

        // Check multiple choice validators (for checkbox groups)
        const multipleChoiceValidators = section.querySelectorAll('.multiple-choice-validator[data-required="true"]');
        for (let validator of multipleChoiceValidators) {
            const questionId = validator.dataset.questionId;
            const checkboxes = section.querySelectorAll(`input[type="checkbox"][name="question_${questionId}"]`);
            const isAnyChecked = Array.from(checkboxes).some(cb => cb.checked);
            if (!isAnyChecked) {
                return false;
            }
        }

        return true;
    }

    function validateCurrentSection() {
        return validateSection(currentStep);
    }

    function validateAllSections() {
        // Returns the first section index with validation errors, or -1 if all valid
        for (let i = 0; i < sections.length; i++) {
            if (!validateSection(i)) {
                return i;
            }
        }
        return -1;
    }

    prevBtn.addEventListener('click', function() {
        if (currentStep > 0) {
            currentStep--;
            showStep(currentStep);
            errorContainer.style.display = 'none';
            saveDraft(); // Save step position
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
            saveDraft(); // Save step position
        }
    });

    if (form) {
        form.addEventListener('submit', async function(e) {
            e.preventDefault();

            // Validate all sections before submission
            const firstInvalidSection = validateAllSections();
            if (firstInvalidSection !== -1) {
                // Navigate to the first section with errors
                currentStep = firstInvalidSection;
                showStep(currentStep);
                showErrors([`Please complete all required questions. Check step ${firstInvalidSection + 1}.`]);
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
                    // Redirect to completion page (draft will be cleared there)
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
});
