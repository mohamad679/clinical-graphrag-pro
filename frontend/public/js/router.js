const routes = {
    '/': { component: 'case-dashboard' },
    '/workspace': { component: 'case-workspace' },
    '/sources': { component: 'source-library' },
    '/images': { component: 'imaging-review' },
    '/reports': { component: 'reports-workspace' },
    '/workflows': { component: 'ai-workflows' },
    '/graph': { component: 'knowledge-graph' },
    '/admin': { component: 'quality-admin' },
};

function waitForPageContent() {
    return new Promise((resolve) => {
        const existing = document.getElementById('page-content');
        if (existing) {
            resolve(existing);
            return;
        }

        const observer = new MutationObserver(() => {
            const content = document.getElementById('page-content');
            if (content) {
                observer.disconnect();
                resolve(content);
            }
        });

        observer.observe(document.body, { childList: true, subtree: true });
    });
}

function normalizeRoute(pathname) {
    return routes[pathname] ? pathname : '/';
}

async function resolveGuardedPath(pathname, search = window.location.search) {
    const normalized = normalizeRoute(pathname);
    return `${normalized}${search}`;
}

export async function renderRoute(targetPath = `${window.location.pathname}${window.location.search}`) {
    const url = new URL(targetPath, window.location.origin);
    const guarded = await resolveGuardedPath(url.pathname, url.search);

    if (guarded !== `${url.pathname}${url.search}`) {
        window.history.replaceState({}, '', guarded);
        return renderRoute(guarded);
    }

    const pathname = normalizeRoute(url.pathname);
    const route = routes[pathname] || routes['/'];
    const layout = document.querySelector('app-layout');
    layout?.setRoute(pathname);

    const loadRouteComponent = window.__CLINICAL_LOAD_ROUTE_COMPONENT__;
    if (typeof loadRouteComponent === 'function') {
        await loadRouteComponent(pathname);
    }

    const contentDiv = await waitForPageContent();
    const componentHTML = `<${route.component}></${route.component}>`;

    const performRender = () => {
        contentDiv.innerHTML = componentHTML;
        window.dispatchEvent(new CustomEvent('clinical:route-rendered', {
            detail: { path: pathname, search: url.search },
        }));
    };

    performRender();

    layout?.updateActiveRoute(pathname);
}

export function navigate(path, { replace = false } = {}) {
    const target = new URL(path, window.location.origin);
    if (`${window.location.pathname}${window.location.search}` === `${target.pathname}${target.search}`) {
        return renderRoute(`${target.pathname}${target.search}`);
    }

    const historyMethod = replace ? window.history.replaceState : window.history.pushState;
    historyMethod.call(window.history, {}, '', `${target.pathname}${target.search}`);
    return renderRoute(`${target.pathname}${target.search}`);
}

window.addEventListener('popstate', () => {
    renderRoute(`${window.location.pathname}${window.location.search}`);
});

document.addEventListener('click', (event) => {
    const link = event.target.closest('a[href]');
    if (!link) return;
    const url = new URL(link.href, window.location.origin);
    if (url.origin !== window.location.origin) return;
    if (link.hasAttribute('data-native')) return;
    event.preventDefault();
    navigate(`${url.pathname}${url.search}`);
});

document.addEventListener('DOMContentLoaded', () => {
    renderRoute(`${window.location.pathname}${window.location.search}`);
});
