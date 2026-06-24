const TOAST_CONTAINER_ID = 'toast-stack';

function escapeHtml(value = '') {
    return String(value)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}

function ensureToastContainer() {
    if (typeof document === 'undefined') return null;
    let container = document.getElementById(TOAST_CONTAINER_ID);
    if (container) return container;

    container = document.createElement('div');
    container.id = TOAST_CONTAINER_ID;
    container.className = 'toast-stack';
    document.body.appendChild(container);
    return container;
}

function renderToast(message, tone = 'info', duration = 4000) {
    if (typeof document === 'undefined') return;
    const container = ensureToastContainer();
    if (!container) return;

    const toast = document.createElement('button');
    toast.type = 'button';
    toast.className = `toast toast--${tone}`;
    toast.innerHTML = `
        <span class="toast__icon" aria-hidden="true">${tone === 'success' ? '✓' : tone === 'error' ? '!' : tone === 'warning' ? '!' : 'i'}</span>
        <span class="toast__message">${escapeHtml(message)}</span>
    `;

    const dismiss = () => {
        toast.classList.add('toast--exiting');
        window.setTimeout(() => toast.remove(), 220);
    };

    toast.addEventListener('click', dismiss);
    container.appendChild(toast);
    requestAnimationFrame(() => toast.classList.add('toast--visible'));
    window.setTimeout(dismiss, duration);
}

export const toast = {
    show(message, tone = 'info', duration = 4000) {
        renderToast(message, tone, duration);
    },
    success(message, duration = 3000) {
        renderToast(message, 'success', duration);
    },
    error(message, duration = 5000) {
        renderToast(message, 'error', duration);
    },
    warning(message, duration = 4000) {
        renderToast(message, 'warning', duration);
    },
    info(message, duration = 4000) {
        renderToast(message, 'info', duration);
    },
};

export function showToast(message, tone = 'info', duration = 4000) {
    toast.show(message, tone, duration);
}
