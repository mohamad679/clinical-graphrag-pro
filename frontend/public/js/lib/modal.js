function escapeHtml(value = '') {
    return String(value)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}

const MODAL_ROOT_ID = 'global-modal-root';
const FOCUSABLE_SELECTOR = [
    'a[href]',
    'button:not([disabled])',
    'textarea:not([disabled])',
    'input:not([disabled])',
    'select:not([disabled])',
    '[tabindex]:not([tabindex="-1"])',
].join(',');

class ModalService {
    constructor() {
        this.active = null;
        this.boundKeydown = (event) => this.handleKeydown(event);
    }

    ensureRoot() {
        let root = document.getElementById(MODAL_ROOT_ID);
        if (root) return root;
        root = document.createElement('div');
        root.id = MODAL_ROOT_ID;
        document.body.appendChild(root);
        return root;
    }

    forceClose() {
        document.removeEventListener('keydown', this.boundKeydown, true);
        const root = document.getElementById(MODAL_ROOT_ID);
        if (root) root.innerHTML = '';
        document.body.classList.remove('modal-open');
        this.active = null;
    }

    close(result = null) {
        if (!this.active) {
            this.forceClose();
            return;
        }

        const { resolver, previouslyFocused } = this.active;
        this.forceClose();
        if (previouslyFocused?.focus && previouslyFocused.isConnected) {
            previouslyFocused.focus();
        }
        resolver(result);
    }

    focusFirstElement() {
        if (!this.active) return;
        const focusables = [...this.active.dialog.querySelectorAll(FOCUSABLE_SELECTOR)];
        const target = focusables.find((node) => node.hasAttribute('data-autofocus')) || focusables[0];
        target?.focus();
    }

    handleKeydown(event) {
        if (!this.active) return;
        if (event.key === 'Escape') {
            event.preventDefault();
            this.close(false);
            return;
        }

        if (event.key !== 'Tab') return;
        const focusables = [...this.active.dialog.querySelectorAll(FOCUSABLE_SELECTOR)];
        if (!focusables.length) return;
        const first = focusables[0];
        const last = focusables[focusables.length - 1];
        const current = document.activeElement;

        if (event.shiftKey && current === first) {
            event.preventDefault();
            last.focus();
        } else if (!event.shiftKey && current === last) {
            event.preventDefault();
            first.focus();
        }
    }

    open(title, content, actions = [], options = {}) {
        if (typeof document === 'undefined') return Promise.resolve(null);
        if (this.active) this.close(false);

        const root = this.ensureRoot();
        const dialogClass = options.wide ? 'modal-dialog modal-dialog--wide' : 'modal-dialog';
        const bodyContent = typeof content === 'string' ? content : '';

        root.innerHTML = `
            <div class="modal-overlay modal-overlay--global" data-modal-overlay>
                <div class="${dialogClass}" role="dialog" aria-modal="true" aria-labelledby="global-modal-title">
                    <div class="modal-header">
                        <div>
                            ${options.eyebrow ? `<div class="eyebrow">${escapeHtml(options.eyebrow)}</div>` : ''}
                            <h3 id="global-modal-title" class="modal-title">${escapeHtml(title)}</h3>
                        </div>
                        <button type="button" class="icon-button icon-button--ghost" data-modal-close aria-label="Close dialog">×</button>
                    </div>
                    <div class="modal-body">${bodyContent}</div>
                    <div class="modal-actions">
                        ${actions.map((action, index) => `
                            <button
                                type="button"
                                class="button ${action.variant === 'ghost' ? 'button--ghost' : action.variant === 'secondary' ? 'button--secondary' : 'button--primary'} ${action.danger ? 'button--danger' : ''}"
                                data-modal-action="${escapeHtml(String(index))}"
                                ${action.autofocus ? 'data-autofocus="true"' : ''}
                            >
                                ${escapeHtml(action.label || 'Action')}
                            </button>
                        `).join('')}
                    </div>
                </div>
            </div>
        `;

        const overlay = root.querySelector('[data-modal-overlay]');
        const dialog = root.querySelector('.modal-dialog');
        const previouslyFocused = document.activeElement;
        document.body.classList.add('modal-open');

        const promise = new Promise((resolve) => {
            this.active = { root, dialog, resolver: resolve, previouslyFocused };
            root.querySelector('[data-modal-close]')?.addEventListener('click', () => this.close(false));
            overlay?.addEventListener('click', (event) => {
                if (event.target === overlay && options.backdropClose !== false) {
                    this.close(false);
                }
            });
            root.querySelectorAll('[data-modal-action]').forEach((button) => {
                button.addEventListener('click', async () => {
                    const action = actions[Number(button.getAttribute('data-modal-action'))];
                    if (!action) return;
                    const result = typeof action.onClick === 'function' ? await action.onClick() : action.value;
                    if (action.closeOnClick === false) return;
                    this.close(result);
                });
            });
            document.addEventListener('keydown', this.boundKeydown, true);
            requestAnimationFrame(() => this.focusFirstElement());
        });

        return promise;
    }

    confirm(message, options = {}) {
        return this.open(
            options.title || 'Confirm Action',
            `<div class="modal-copy">${escapeHtml(message)}</div>`,
            [
                { label: options.cancelLabel || 'Cancel', value: false, variant: 'ghost' },
                {
                    label: options.confirmLabel || 'Confirm',
                    value: true,
                    variant: options.destructive ? 'primary' : 'secondary',
                    danger: Boolean(options.destructive),
                    autofocus: true,
                },
            ],
            { eyebrow: options.eyebrow || 'Confirmation' },
        ).then((result) => Boolean(result));
    }

    alert(message, options = {}) {
        return this.open(
            options.title || 'Notice',
            `<div class="modal-copy">${escapeHtml(message)}</div>`,
            [{ label: options.closeLabel || 'Close', value: true, variant: 'primary', autofocus: true }],
            { eyebrow: options.eyebrow || 'Message' },
        );
    }
}

export const modal = new ModalService();
