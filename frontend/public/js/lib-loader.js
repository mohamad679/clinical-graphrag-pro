const scriptPromises = new Map();

function loadScriptOnce(key, src, isReady) {
    if (isReady()) {
        return Promise.resolve();
    }

    const existingPromise = scriptPromises.get(key);
    if (existingPromise) {
        return existingPromise;
    }

    const promise = new Promise((resolve, reject) => {
        const existingScript = document.querySelector(`script[data-lib="${key}"]`);
        if (existingScript) {
            existingScript.addEventListener('load', () => resolve(), { once: true });
            existingScript.addEventListener('error', () => reject(new Error(`Failed to load ${key}`)), { once: true });
            return;
        }

        const script = document.createElement('script');
        script.src = src;
        script.async = true;
        script.dataset.lib = key;
        script.onload = () => resolve();
        script.onerror = () => reject(new Error(`Failed to load ${src}`));
        document.head.appendChild(script);
    });

    scriptPromises.set(key, promise);
    return promise;
}

function loadScriptWithTimeout(key, src, isReady, timeoutMs = 10000) {
    let timeoutId = null;
    const loadPromise = loadScriptOnce(key, src, isReady);
    const timeoutPromise = new Promise((_, reject) => {
        timeoutId = window.setTimeout(() => {
            scriptPromises.delete(key);
            const stalledScript = document.querySelector(`script[data-lib="${key}"]`);
            if (stalledScript && !isReady()) {
                stalledScript.remove();
            }
            reject(new Error(`Timeout loading ${key} from CDN`));
        }, timeoutMs);
    });

    return Promise.race([loadPromise, timeoutPromise]).finally(() => {
        if (timeoutId !== null) window.clearTimeout(timeoutId);
    });
}

export function ensureChartJs() {
    return loadScriptWithTimeout(
        'chartjs',
        'https://cdn.jsdelivr.net/npm/chart.js',
        () => typeof window.Chart !== 'undefined',
    );
}

export function ensureVisNetwork() {
    return loadScriptWithTimeout(
        'vis-network',
        'https://unpkg.com/vis-network/standalone/umd/vis-network.min.js',
        () => typeof window.vis !== 'undefined',
    );
}

export async function ensureD3() {
    try {
        return await loadScriptWithTimeout(
            'd3',
            'https://cdn.jsdelivr.net/npm/d3@7/dist/d3.min.js',
            () => typeof window.d3 !== 'undefined',
            8000,
        );
    } catch (_) {
        return await loadScriptWithTimeout(
            'd3',
            'https://unpkg.com/d3@7/dist/d3.min.js',
            () => typeof window.d3 !== 'undefined',
            8000,
        );
    }
}
