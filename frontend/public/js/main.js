function renderCrashFallback(message) {
    const root = document.body;
    if (!root) return;

    let panel = document.getElementById('clinical-app-crash');
    if (!panel) {
        panel = document.createElement('div');
        panel.id = 'clinical-app-crash';
        panel.style.position = 'fixed';
        panel.style.inset = '0';
        panel.style.zIndex = '9999';
        panel.style.display = 'grid';
        panel.style.placeItems = 'center';
        panel.style.padding = '24px';
        panel.style.background = 'rgba(7, 10, 14, 0.92)';
        panel.style.color = '#f4f7fb';
        root.appendChild(panel);
    }

    panel.innerHTML = `
        <div style="max-width:560px;width:100%;border:1px solid rgba(122, 232, 216, 0.18);border-radius:24px;padding:28px;background:#10161d;box-shadow:0 24px 80px rgba(0,0,0,0.45);">
            <div style="font-size:12px;letter-spacing:0.18em;text-transform:uppercase;color:#7ae8d8;margin-bottom:12px;">Clinical GraphRAG Pro</div>
            <h1 style="margin:0 0 10px;font-size:28px;line-height:1.1;">The app hit a frontend error</h1>
            <p style="margin:0 0 18px;color:#b7c0cb;line-height:1.6;">${message}</p>
            <div style="display:flex;gap:12px;flex-wrap:wrap;">
                <button id="clinical-app-reload" style="border:none;border-radius:999px;padding:12px 18px;background:#7ae8d8;color:#0b1117;font-weight:700;cursor:pointer;">Reload app</button>
                <button id="clinical-app-clear" style="border:1px solid rgba(255,255,255,0.16);border-radius:999px;padding:12px 18px;background:transparent;color:#f4f7fb;font-weight:600;cursor:pointer;">Clear local data</button>
            </div>
        </div>
    `;

    panel.querySelector('#clinical-app-reload')?.addEventListener('click', () => window.location.reload(), { once: true });
    panel.querySelector('#clinical-app-clear')?.addEventListener('click', () => {
        window.localStorage.removeItem('clinical_auth_access_token');
        window.localStorage.removeItem('clinical_auth_refresh_token');
        window.localStorage.removeItem('clinical_auth_user');
        window.localStorage.removeItem('clinical_auth_session_id');
        window.location.href = '/';
    }, { once: true });
}

window.addEventListener('error', (event) => {
    if (!event?.error) return;
    if (String(event.error?.name || '') === 'ResizeObserverLoopError') return;
    renderCrashFallback('Reload the page once. If this keeps happening, the current browser tab may still be pointing at stale frontend assets.');
});

window.addEventListener('unhandledrejection', () => {
    renderCrashFallback('The page encountered an unexpected frontend failure before it could finish rendering.');
});

const ASSET_VERSION = '20260619-source-guard';
const importVersioned = (path) => import(`${path}?v=${ASSET_VERSION}`);

const lazyComponentLoaders = {
    '/': () => importVersioned('./components/case-dashboard.js'),
    '/workspace': () => importVersioned('./components/case-workspace.js'),
    '/sources': () => importVersioned('./components/source-library.js'),
    '/images': () => importVersioned('./components/imaging-review.js'),
    '/reports': () => importVersioned('./components/reports-workspace.js'),
    '/workflows': () => importVersioned('./components/ai-workflows.js'),
    '/graph': () => importVersioned('./components/knowledge-graph.js'),
    '/admin': () => importVersioned('./components/quality-admin.js'),
};

const loadedRouteComponents = new Set();
const routeComponentPromises = new Map();

async function loadRouteComponent(path) {
    const loader = lazyComponentLoaders[path];
    if (!loader || loadedRouteComponents.has(path)) return;
    if (routeComponentPromises.has(path)) return routeComponentPromises.get(path);

    const promise = loader()
        .then(() => {
            loadedRouteComponents.add(path);
        })
        .finally(() => {
            routeComponentPromises.delete(path);
        });

    routeComponentPromises.set(path, promise);
    try {
        await promise;
    } catch (error) {
        throw error;
    }
}

window.__CLINICAL_LOAD_ROUTE_COMPONENT__ = loadRouteComponent;

async function bootstrapApp() {
    try {
        window.addEventListener('clinical:route-rendered', async (event) => {
            const path = event?.detail?.path;
            if (!path) return;
            try {
                await loadRouteComponent(path);
            } catch (error) {
                console.error(`Failed to lazy load route component for ${path}`, error);
            }
        }, { once: false });

        const [, router] = await Promise.all([
            importVersioned('./components/app-layout.js'),
            importVersioned('./router.js'),
        ]);

        await router.renderRoute(`${window.location.pathname}${window.location.search}`);

        window.setTimeout(() => {
            importVersioned('./components/case-dashboard.js');
        }, 2000);
    } catch (error) {
        console.error('Failed to bootstrap frontend', error);
        renderCrashFallback('The latest frontend bundle could not load cleanly. Reload once, and if it persists, restart the local frontend proxy on a fresh port.');
    }
}

bootstrapApp();
