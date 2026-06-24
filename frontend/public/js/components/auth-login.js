import { apiFetch, AuthService, showToast } from '../api.js';
import { navigate } from '../router.js';

class AuthLogin extends HTMLElement {
    constructor() {
        super();
        this.isSubmitting = false;
        this.showPassword = false;
        this.errorMessage = '';
        this.bootstrapOpen = false;
        this.bootstrapStatusLoading = true;
        this.resetMode = false;
        this.resetSubmitting = false;
        this.resetEmail = '';
    }

    connectedCallback() {
        this.render();
        this.setupEvents();
        this.loadBootstrapStatus();
    }

    getNextPath() {
        const params = new URLSearchParams(window.location.search);
        return params.get('next') || '/';
    }

    async loadBootstrapStatus() {
        try {
            const status = await AuthService.getBootstrapStatus();
            this.bootstrapOpen = Boolean(status?.bootstrap_open);
        } catch (_) {
            this.bootstrapOpen = false;
        } finally {
            this.bootstrapStatusLoading = false;
            this.render();
            this.setupEvents();
        }
    }

    getTitle() {
        return this.bootstrapOpen ? 'Create first admin' : 'Sign in';
    }

    getSubtitle() {
        if (this.resetMode) {
            return 'Enter your email address and we will send a password reset link if the account exists.';
        }
        if (this.bootstrapOpen) {
            return 'This deployment has no users yet. Create the initial administrator account to continue.';
        }
        return 'Access the clinical workspace with your assigned account.';
    }

    getBrandTitle() {
        if (this.resetMode) return 'Reset password';
        return this.getTitle();
    }

    renderStatusNote() {
        if (this.resetMode) {
            return '<div class="auth-hint">For privacy, the app confirms the request without revealing whether the email is registered.</div>';
        }
        if (this.bootstrapStatusLoading) {
            return '<div class="auth-hint">Checking whether this deployment needs first-time setup…</div>';
        }
        if (!this.bootstrapOpen) return '';
        return '<div class="auth-hint">First-time setup is open because the user database is empty.</div>';
    }

    renderPrimaryForm() {
        return `
            <form id="login-form" class="auth-form ${this.errorMessage ? 'is-shaking' : ''}">
                ${this.bootstrapOpen ? `
                    <label class="field">
                        <span class="field-label">Name</span>
                        <input id="login-name" class="field-input" type="text" autocomplete="name" placeholder="Administrator" />
                    </label>
                ` : ''}

                <label class="field">
                    <span class="field-label">Email</span>
                    <input id="login-email" class="field-input" type="email" autocomplete="email" required placeholder="you@hospital.org" />
                </label>

                <label class="field">
                    <span class="field-label">Password</span>
                    <div class="field-input-wrap">
                        <input id="login-password" class="field-input field-input--with-action" type="${this.showPassword ? 'text' : 'password'}" autocomplete="${this.bootstrapOpen ? 'new-password' : 'current-password'}" required placeholder="Enter your password" />
                        <button type="button" id="toggle-password" class="field-action">${this.showPassword ? 'Hide' : 'Show'}</button>
                    </div>
                </label>

                ${this.bootstrapOpen ? `
                    <label class="field">
                        <span class="field-label">Confirm password</span>
                        <input id="login-password-confirm" class="field-input" type="${this.showPassword ? 'text' : 'password'}" autocomplete="new-password" required placeholder="Confirm your password" />
                    </label>
                ` : ''}

                ${this.errorMessage ? `<div class="form-error" role="alert">${this.errorMessage}</div>` : ''}

                <button type="submit" class="button button--primary button--full" ${this.isSubmitting || this.bootstrapStatusLoading ? 'disabled' : ''}>
                    ${this.isSubmitting ? (this.bootstrapOpen ? 'Creating admin…' : 'Signing In…') : (this.bootstrapOpen ? 'Create Admin' : 'Sign In')}
                </button>
            </form>
        `;
    }

    renderResetForm() {
        return `
            <form id="reset-password-form" class="auth-form ${this.errorMessage ? 'is-shaking' : ''}">
                <label class="field">
                    <span class="field-label">Email</span>
                    <input id="reset-email" class="field-input" type="email" autocomplete="email" required placeholder="you@hospital.org" />
                </label>

                ${this.errorMessage ? `<div class="form-error" role="alert">${this.errorMessage}</div>` : ''}

                <button type="submit" class="button button--primary button--full" ${this.resetSubmitting ? 'disabled' : ''}>
                    ${this.resetSubmitting ? 'Sending reset link…' : 'Send reset link'}
                </button>
            </form>
        `;
    }

    renderFooterActions() {
        if (this.resetMode) {
            return `
                <div class="auth-card__actions">
                    <button type="button" id="cancel-reset-btn" class="link-button">Cancel</button>
                </div>
            `;
        }

        return `
            <div class="auth-card__actions">
                <button type="button" id="forgot-password-btn" class="link-button">Forgot password?</button>
                <a href="/register" class="link-button">Need access?</a>
            </div>
        `;
    }

    render() {
        this.innerHTML = `
            <section class="auth-card-wrap">
                <div class="auth-card">
                    <div class="auth-card__brand">Clinical GraphRAG Pro</div>
                    <h1 class="auth-card__title">${this.getBrandTitle()}</h1>
                    <p class="auth-card__subtitle">${this.getSubtitle()}</p>

                    ${this.resetMode ? this.renderResetForm() : this.renderPrimaryForm()}
                    ${this.renderFooterActions()}

                    ${this.renderStatusNote()}
                </div>
            </section>
        `;
    }

    restoreFormValues({ email = '', password = '', passwordConfirm = '', name = '' } = {}) {
        const emailInput = this.querySelector('#login-email');
        const passwordInput = this.querySelector('#login-password');
        const confirmInput = this.querySelector('#login-password-confirm');
        const nameInput = this.querySelector('#login-name');
        if (emailInput) emailInput.value = email;
        if (passwordInput) passwordInput.value = password;
        if (confirmInput) confirmInput.value = passwordConfirm;
        if (nameInput) nameInput.value = name;
    }

    restoreResetFormValue(email = '') {
        const resetEmailInput = this.querySelector('#reset-email');
        if (resetEmailInput) resetEmailInput.value = email;
    }

    setupEvents() {
        const form = this.querySelector('#login-form');
        const emailInput = this.querySelector('#login-email');
        const passwordInput = this.querySelector('#login-password');
        const confirmInput = this.querySelector('#login-password-confirm');
        const nameInput = this.querySelector('#login-name');
        const resetForm = this.querySelector('#reset-password-form');
        const resetEmailInput = this.querySelector('#reset-email');
        const togglePassword = this.querySelector('#toggle-password');
        const forgotPassword = this.querySelector('#forgot-password-btn');
        const cancelReset = this.querySelector('#cancel-reset-btn');

        togglePassword?.addEventListener('click', () => {
            const snapshot = {
                email: emailInput?.value || '',
                password: passwordInput?.value || '',
                passwordConfirm: confirmInput?.value || '',
                name: nameInput?.value || '',
            };
            this.showPassword = !this.showPassword;
            this.render();
            this.setupEvents();
            this.restoreFormValues(snapshot);
            this.querySelector(this.bootstrapOpen ? '#login-name' : '#login-email')?.focus();
        });

        forgotPassword?.addEventListener('click', () => {
            this.resetMode = true;
            this.resetSubmitting = false;
            this.errorMessage = '';
            this.resetEmail = emailInput?.value.trim() || '';
            this.render();
            this.setupEvents();
            this.restoreResetFormValue(this.resetEmail);
            this.querySelector('#reset-email')?.focus();
        });

        cancelReset?.addEventListener('click', () => {
            this.resetMode = false;
            this.resetSubmitting = false;
            this.errorMessage = '';
            this.render();
            this.setupEvents();
            this.restoreFormValues({ email: this.resetEmail });
            this.querySelector('#login-email')?.focus();
        });

        resetForm?.addEventListener('submit', async (event) => {
            event.preventDefault();
            if (this.resetSubmitting) return;

            const email = resetEmailInput?.value.trim() || '';
            if (!email) {
                this.errorMessage = 'Please enter your email address.';
                this.render();
                this.setupEvents();
                this.restoreResetFormValue(email);
                return;
            }

            this.resetSubmitting = true;
            this.errorMessage = '';
            this.resetEmail = email;
            this.render();
            this.setupEvents();
            this.restoreResetFormValue(email);

            try {
                await apiFetch('/auth/forgot-password', {
                    method: 'POST',
                    body: JSON.stringify({ email }),
                    auth: false,
                    fallbackMessage: 'Unable to request a password reset',
                    silent: true,
                    skipRedirect: true,
                    retryOnAuth: false,
                });
                this.resetMode = false;
                this.resetSubmitting = false;
                this.errorMessage = '';
                this.render();
                this.setupEvents();
                this.restoreFormValues({ email });
                showToast('If that email is registered, a reset link was sent.', 'success');
            } catch (error) {
                this.resetSubmitting = false;
                this.errorMessage = error.message || 'Unable to request a password reset.';
                this.render();
                this.setupEvents();
                this.restoreResetFormValue(email);
                showToast(error.message || 'Unable to request a password reset.', 'error');
            }
        });

        form?.addEventListener('submit', async (event) => {
            event.preventDefault();
            if (this.isSubmitting || this.bootstrapStatusLoading) return;

            const email = emailInput?.value.trim() || '';
            const password = passwordInput?.value || '';
            const passwordConfirm = confirmInput?.value || '';
            const name = nameInput?.value.trim() || 'Administrator';

            if (this.bootstrapOpen && password !== passwordConfirm) {
                this.errorMessage = 'The password confirmation does not match.';
                this.render();
                this.setupEvents();
                this.restoreFormValues({ email, password, passwordConfirm, name });
                return;
            }

            this.isSubmitting = true;
            this.errorMessage = '';
            this.render();
            this.setupEvents();
            this.restoreFormValues({ email, password, passwordConfirm, name });

            try {
                if (this.bootstrapOpen) {
                    await AuthService.bootstrapAdmin({ email, password, name });
                    showToast('Initial administrator created successfully.', 'success', 3000);
                } else {
                    await AuthService.login(email, password);
                    showToast('Signed in successfully.', 'success', 2500);
                }
                await navigate(this.getNextPath(), { replace: true });
            } catch (error) {
                this.errorMessage = this.bootstrapOpen
                    ? (error.message || 'Unable to create the first admin account.')
                    : (error.status === 401 ? 'Invalid email or password.' : (error.message || 'Unable to sign in.'));
                this.isSubmitting = false;
                this.render();
                this.setupEvents();
                this.restoreFormValues({ email, password, passwordConfirm, name });
            }
        });
    }
}

customElements.define('auth-login', AuthLogin);
