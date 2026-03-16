import { apiFetch } from '../api.js';

class KnowledgeGraph extends HTMLElement {
    async connectedCallback() {
        this.renderLoading();
        try {
            const data = await apiFetch('/graph/visualize?limit=300');
            this.render();
            this.initNetwork(data);
        } catch (e) {
            this.innerHTML = `<div class="p-8 text-brand-danger">Failed to load Knowledge Graph: ${e.message}</div>`;
        }
    }

    renderLoading() {
        this.innerHTML = `<div class="p-8 h-full flex items-center justify-center"><div class="text-secondary pulse">Loading Neo4j Data...</div></div>`;
    }

    render() {
        this.innerHTML = `
            <div class="p-8 pt-24 h-screen flex flex-col max-w-7xl mx-auto animate-[fade-in_0.4s_ease-out]">
                <div class="mb-6">
                    <h1 class="text-3xl font-bold bg-gradient-to-r from-white to-white/60 bg-clip-text text-transparent flex items-center gap-3 mb-2">
                        <i data-lucide="network" class="w-8 h-8 text-brand-purple"></i> Knowledge Graph
                    </h1>
                    <p class="text-secondary text-sm">Visualizing medical entities and relationships from Neo4j.</p>
                </div>
                <!-- Vis Network Container -->
                <div id="kg-network" class="flex-1 glass-panel rounded-2xl overflow-hidden shadow-2xl relative w-full border-white/10"></div>
            </div>
        `;
        if (window.lucide) window.lucide.createIcons();
    }

    initNetwork(graphData) {
        if (!window.vis) {
            console.error('Vis Network library not loaded.');
            return;
        }

        const container = this.querySelector('#kg-network');

        // Map backend data to vis-network format
        const nodes = new vis.DataSet(
            graphData.nodes.map(n => ({
                id: n.id,
                label: n.name || n.label,
                group: n.label,
                title: JSON.stringify(n.properties, null, 2)
            }))
        );

        const edges = new vis.DataSet(
            graphData.links.map(l => ({
                from: l.source,
                to: l.target,
                label: l.type,
                font: { size: 10, color: 'rgba(255,255,255,0.4)' },
                arrows: 'to'
            }))
        );

        const data = { nodes, edges };

        // Premium Dark Theme Options
        const options = {
            nodes: {
                shape: 'dot',
                size: 16,
                font: { size: 12, color: '#ffffff' },
                borderWidth: 2,
                shadow: { enabled: true, color: 'rgba(0,0,0,0.5)', size: 10 }
            },
            edges: {
                width: 1.5,
                color: { color: 'rgba(255,255,255,0.15)', highlight: 'rgba(59,130,246,0.8)' },
                smooth: { type: 'continuous' }
            },
            groups: {
                Patient: { color: { background: '#8b5cf6', border: '#a78bfa' } },
                Drug: { color: { background: '#10b981', border: '#34d399' } },
                Disease: { color: { background: '#ef4444', border: '#f87171' } },
                Document: { shape: 'square', color: { background: '#3b82f6', border: '#60a5fa' } }
            },
            physics: {
                forceAtlas2Based: { gravitationalConstant: -26, centralGravity: 0.005, springLength: 230, springConstant: 0.18 },
                maxVelocity: 146,
                solver: 'forceAtlas2Based',
                timestep: 0.35,
                stabilization: { iterations: 150 }
            },
            interaction: {
                hover: true,
                tooltipDelay: 200,
                zoomView: true,
                dragView: true
            }
        };

        new vis.Network(container, data, options);
    }
}

customElements.define('knowledge-graph', KnowledgeGraph);
