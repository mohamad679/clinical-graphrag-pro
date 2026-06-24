import { modal } from './modal.js';

const SHORTCUTS = [
    { combo: 'Cmd/Ctrl + K', description: 'Focus the chat input from anywhere' },
    { combo: 'Cmd/Ctrl + /', description: 'Open keyboard shortcuts help' },
    { combo: 'Cmd/Ctrl + N', description: 'Start a new chat session' },
    { combo: '1', description: 'Go to Clinical Chat' },
    { combo: '2', description: 'Go to Agent Workflow' },
    { combo: '3', description: 'Go to Medical Images' },
    { combo: '4', description: 'Go to Knowledge Graph' },
    { combo: '5', description: 'Go to Document Library' },
    { combo: 'Escape', description: 'Close the active modal or panel' },
];

let registered = false;

function isTypingTarget(target) {
    if (!target) return false;
    const tag = target.tagName?.toLowerCase();
    return tag === 'input' || tag === 'textarea' || tag === 'select' || target.isContentEditable;
}

function renderShortcutHelp() {
    return `
        <div class="shortcut-grid">
            ${SHORTCUTS.map((item) => `
                <article class="shortcut-card">
                    <div class="shortcut-key">${item.combo}</div>
                    <div class="shortcut-description">${item.description}</div>
                </article>
            `).join('')}
        </div>
    `;
}

export function openShortcutsHelp() {
    return modal.open(
        'Keyboard Shortcuts',
        renderShortcutHelp(),
        [{ label: 'Close', value: true, variant: 'secondary', autofocus: true }],
        { eyebrow: 'Productivity' },
    );
}

function focusChatInput(navigate) {
    const focus = () => {
        const input = document.getElementById('chat-input');
        input?.focus();
        input?.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
    };

    if (window.location.pathname !== '/') {
        const once = () => {
            window.removeEventListener('clinical:route-rendered', once);
            requestAnimationFrame(focus);
        };
        window.addEventListener('clinical:route-rendered', once);
        navigate('/');
        return;
    }

    requestAnimationFrame(focus);
}

export function registerGlobalShortcuts({ navigate, onNewChat } = {}) {
    if (registered || typeof document === 'undefined') return;
    registered = true;

    document.addEventListener('keydown', (event) => {
        if (!(event instanceof KeyboardEvent) || event.defaultPrevented || event.isComposing) {
            return;
        }

        const rawKey = typeof event.key === 'string' ? event.key : '';
        if (!rawKey) return;

        const key = rawKey.toLowerCase();
        const metaPressed = event.metaKey || event.ctrlKey;

        if (metaPressed && key === 'k') {
            event.preventDefault();
            focusChatInput(navigate);
            return;
        }

        if (metaPressed && (key === '/' || key === '?')) {
            event.preventDefault();
            openShortcutsHelp();
            return;
        }

        if (metaPressed && key === 'n') {
            event.preventDefault();
            onNewChat?.();
            return;
        }

        if (metaPressed || event.altKey || isTypingTarget(event.target)) return;

        const routeMap = {
            '1': '/',
            '2': '/agents',
            '3': '/images',
            '4': '/graph',
            '5': '/documents',
        };

        if (routeMap[key]) {
            event.preventDefault();
            navigate?.(routeMap[key]);
        }
    });
}
