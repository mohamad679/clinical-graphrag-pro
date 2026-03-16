// router.js

const routes = {
    '/': '<chat-interface></chat-interface>',
    '/evaluations': '<evaluations-dashboard></evaluations-dashboard>',
    '/graph': '<knowledge-graph></knowledge-graph>'
};

/**
 * Perform the routing logic: update the DOM inside the main container.
 */
function renderRoute(path) {
    const contentDiv = document.getElementById('page-content');
    if (!contentDiv) return;

    // Default to chat if route not found
    const componentHTML = routes[path] || routes['/'];

    // Update active state in sidebar (if app-layout has rendered)
    const layout = document.querySelector('app-layout');
    if (layout && typeof layout.updateActiveRoute === 'function') {
        layout.updateActiveRoute(path);
    }

    // Check if View Transitions API is supported
    if (!document.startViewTransition) {
        contentDiv.innerHTML = componentHTML;
        return;
    }

    // Use View Transitions for hyper-smooth crossfade
    document.startViewTransition(() => {
        contentDiv.innerHTML = componentHTML;
    });
}

/**
 * Handle browser back/forward buttons
 */
window.addEventListener('popstate', () => {
    renderRoute(window.location.pathname);
});

/**
 * Centralized navigation function called by components
 */
export function navigate(path) {
    if (window.location.pathname === path) return;
    window.history.pushState({}, '', path);
    renderRoute(path);
}

/**
 * Intercept all <a> clicks for client-side routing
 */
document.addEventListener('click', e => {
    const link = e.target.closest('a');
    if (link && link.href.startsWith(window.location.origin)) {
        e.preventDefault();
        const path = new URL(link.href).pathname;
        navigate(path);
    }
});

/**
 * Wait for the #page-content element to appear in the DOM
 * (injected by the app-layout Web Component) before routing.
 * This fixes the race condition between DOMContentLoaded and
 * the Custom Element lifecycle (connectedCallback).
 */
function waitForPageContent(callback) {
    // If already available, run immediately
    if (document.getElementById('page-content')) {
        callback();
        return;
    }

    // Use MutationObserver to wait for it to appear
    const observer = new MutationObserver(() => {
        if (document.getElementById('page-content')) {
            observer.disconnect();
            callback();
        }
    });
    observer.observe(document.body, { childList: true, subtree: true });

    // Fallback timeout (200ms) in case the observer misses it
    setTimeout(() => {
        observer.disconnect();
        if (document.getElementById('page-content')) {
            callback();
        }
    }, 200);
}

// Initial render — wait for the layout to be ready first
document.addEventListener('DOMContentLoaded', () => {
    waitForPageContent(() => {
        renderRoute(window.location.pathname);
    });
});
