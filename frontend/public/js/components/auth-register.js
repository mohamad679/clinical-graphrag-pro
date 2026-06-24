import { showToast } from '../api.js';
import { navigate } from '../router.js';

class AuthRegister extends HTMLElement {
    connectedCallback() {
        this.render();
        this.setupEvents();
    }

    render() {
        this.innerHTML = `
            <section class="auth-card-wrap">
                <div class="auth-card">
                    <div class="auth-card__brand">Clinical GraphRAG Pro</div>
                    <h1 class="auth-card__title">Request access</h1>
                    <p class="auth-card__subtitle">Self-registration is intentionally restricted. Use this form to prepare a request, then contact an administrator.</p>

                    <form id="register-form" class="auth-form">
                        <label class="field">
                            <span class="field-label">Full name</span>
                            <input id="register-name" class="field-input" type="text" required placeholder="Dr. Alex Morgan" />
                        </label>

                        <label class="field">
                            <span class="field-label">Work email</span>
                            <input id="register-email" class="field-input" type="email" required placeholder="alex@hospital.org" />
                        </label>

                        <label class="field">
                            <span class="field-label">Clinical role</span>
                            <select id="register-role" class="field-input">
                                <option value="physician">Physician</option>
                                <option value="nurse">Nurse</option>
                                <option value="viewer">Viewer</option>
                            </select>
                        </label>

                        <button type="submit" class="button button--primary button--full">Prepare Access Request</button>
                    </form>

                    <div class="auth-card__actions">
                        <a href="/login" class="link-button">Back to sign in</a>
                    </div>
                </div>
            </section>
        `;
    }

    setupEvents() {
        const form = this.querySelector('#register-form');

        form?.addEventListener('submit', async (event) => {
            event.preventDefault();
            const name = this.querySelector('#register-name')?.value.trim() || '';
            const email = this.querySelector('#register-email')?.value.trim() || '';
            const role = this.querySelector('#register-role')?.value || 'physician';

            showToast(
                `Registration is disabled in this deployment. Ask an administrator to create access for ${name || email || 'this account'} (${role}).`,
                'info',
                5500,
            );
            await navigate('/login');
        });
    }
}

customElements.define('auth-register', AuthRegister);
