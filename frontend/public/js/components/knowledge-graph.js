	import {
	    getGraphStats,
	    getGraphVisualization,
	    getPatientLabTrends,
	    getTemporalGraphState,
	    ingestFhirBundle,
	    listOntologies,
	    normalizeEntities,
	    primeChatContext,
	    showToast,
	} from '../api.js';
import { ensureChartJs, ensureD3 } from '../lib-loader.js';
import { navigate } from '../router.js';

function escapeHtml(value = '') {
    return String(value)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}

function escapeAttr(value = '') {
    return escapeHtml(value).replace(/`/g, '&#96;');
}

function formatDate(value) {
    if (!value) return 'Unknown';
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return String(value);
    return date.toLocaleDateString();
}

function isoToDateValue(value) {
    if (!value) return '';
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return '';
    return date.toISOString().slice(0, 10);
}

class KnowledgeGraph extends HTMLElement {
    constructor() {
        super();
        this.graphData = { nodes: [], links: [], source: 'temporal_graph' };
        this.stats = null;
        this.loading = true;
        this.error = '';
        this.searchTerm = '';
        this.patientFilterId = '';
        this.selectedNodeId = '';
        this.typeFilters = new Set();
        this.timelineDates = [];
        this.timelineIndex = -1;
        this.temporalQuery = {
            open: false,
            entity: '',
            date: '',
            matches: new Set(),
            result: null,
        };
	        this.labTrends = {
	            open: false,
	            loading: false,
	            patientId: '',
	            data: null,
	            error: '',
	            chartReady: false,
	        };
	        this.normalizationText = '';
	        this.normalizationResult = null;
	        this.fhirText = '';
	        this.fhirResult = null;
	        this.ontologies = [];
	        this.labTrendChart = null;
	    }

    async connectedCallback() {
        this.renderLoading();
        if (!this._themeChangeHandler) {
            this._themeChangeHandler = () => {
                if (!this.loading && !this.error) {
                    this.render();
                    this.setupEvents();
                    this.mountGraph();
                }
            };
            window.addEventListener('clinical:theme-changed', this._themeChangeHandler);
        }
        try {
            await Promise.all([
                ensureD3(),
                this.loadGraph(),
            ]);
            this.loading = false;
            this.render();
            this.setupEvents();
            this.mountGraph();
        } catch (error) {
            const isCdnError = error.message?.includes('Timeout loading')
                || error.message?.includes('Failed to load');
            this.error = isCdnError
                ? 'Graph visualization library could not load. Check your internet connection.'
                : (error.message || 'Unable to load graph data.');
            this.render();
            this.setupEvents();
        }
    }

    disconnectedCallback() {
        this.destroyLabTrendChart();
        if (this._themeChangeHandler) {
            window.removeEventListener('clinical:theme-changed', this._themeChangeHandler);
            this._themeChangeHandler = null;
        }
    }

    async loadGraph() {
        const [graphData, stats] = await Promise.all([
            getGraphVisualization(320, this.patientFilterId),
            getGraphStats().catch(() => null),
        ]);
        this.graphData = {
            nodes: Array.isArray(graphData?.nodes) ? graphData.nodes : [],
            links: Array.isArray(graphData?.links) ? graphData.links : [],
            source: graphData?.source || 'temporal_graph',
        };
	        this.stats = stats;
	        const ontologyPayload = await listOntologies().catch(() => ({ ontologies: [] }));
	        this.ontologies = Array.isArray(ontologyPayload?.ontologies) ? ontologyPayload.ontologies : [];

        const presentTypes = this.getNodeTypes();
        if (!this.typeFilters.size) {
            presentTypes.forEach((type) => this.typeFilters.add(type));
        }

        this.timelineDates = this.getTimelineDates();
        if (this.timelineDates.length) {
            this.timelineIndex = this.timelineDates.length - 1;
        }
    }

    renderLoading() {
        this.innerHTML = `
            <section class="docs-view graph-view">
                <header class="page-header">
                    <div>
                        <div class="eyebrow">Knowledge Graph</div>
                        <h1 class="page-title">Loading Relationship Map</h1>
                        <p class="page-subtitle pulse">Preparing temporal entities, graph stats, and force layout...</p>
                    </div>
                </header>
            </section>
        `;
    }

    getNodeType(node) {
        const raw = String(node?.label || node?.type || 'entity').toLowerCase();
        if (raw.includes('patient')) return 'patient';
        if (raw.includes('drug') || raw.includes('medication')) return 'drug';
        if (raw.includes('disease') || raw.includes('condition') || raw.includes('symptom')) return 'condition';
        if (raw.includes('lab') || raw.includes('test')) return 'lab';
        if (raw.includes('document')) return 'document';
        return 'entity';
    }

    getNodeTypes() {
        return [...new Set(this.graphData.nodes.map((node) => this.getNodeType(node)))].sort();
    }

    getTimelineDates() {
        return [...new Set(
            this.graphData.links.flatMap((link) => [link.start_date, link.end_date]).filter(Boolean),
        )].sort();
    }

    getCurrentTimelineDate() {
        if (this.timelineIndex < 0 || !this.timelineDates.length) return '';
        return this.timelineDates[this.timelineIndex] || '';
    }

    isNodeAllowed(node) {
        return this.typeFilters.has(this.getNodeType(node));
    }

    isLinkActiveAtDate(link, dateValue) {
        if (!dateValue) return true;
        const current = new Date(dateValue);
        const start = link.start_date ? new Date(link.start_date) : null;
        const end = link.end_date ? new Date(link.end_date) : null;
        if (start && current < start) return false;
        if (end && current > end) return false;
        return true;
    }

    getVisibleGraph() {
        const allowedNodes = this.graphData.nodes.filter((node) => this.isNodeAllowed(node));
        const allowedIds = new Set(allowedNodes.map((node) => String(node.id)));
        const timelineDate = this.getCurrentTimelineDate();

        const visibleLinks = this.graphData.links.filter((link) => (
            allowedIds.has(String(link.source))
            && allowedIds.has(String(link.target))
            && this.isLinkActiveAtDate(link, timelineDate)
        ));

        const connectedIds = new Set();
        visibleLinks.forEach((link) => {
            connectedIds.add(String(link.source));
            connectedIds.add(String(link.target));
        });

        const visibleNodes = allowedNodes.filter((node) => (
            connectedIds.has(String(node.id))
            || String(node.id) === String(this.selectedNodeId)
            || !visibleLinks.length
        ));

        return { nodes: visibleNodes, links: visibleLinks };
    }

    getDegreeMap(nodes, links) {
        const degree = new Map(nodes.map((node) => [String(node.id), 0]));
        links.forEach((link) => {
            degree.set(String(link.source), (degree.get(String(link.source)) || 0) + 1);
            degree.set(String(link.target), (degree.get(String(link.target)) || 0) + 1);
        });
        return degree;
    }

    getSelectedNode() {
        return this.graphData.nodes.find((node) => String(node.id) === String(this.selectedNodeId)) || null;
    }

    getNodeConnections(nodeId) {
        const nodeMap = new Map(this.graphData.nodes.map((node) => [String(node.id), node]));
        return this.graphData.links
            .filter((link) => String(link.source) === String(nodeId) || String(link.target) === String(nodeId))
            .map((link) => {
                const outgoing = String(link.source) === String(nodeId);
                const peer = nodeMap.get(String(outgoing ? link.target : link.source));
                return {
                    direction: outgoing ? 'outgoing' : 'incoming',
                    relationship: link.type || 'RELATED_TO',
                    peerName: peer?.name || peer?.id || 'Entity',
                    peerType: this.getNodeType(peer || {}),
                    startDate: link.start_date || '',
                    endDate: link.end_date || '',
                };
            });
    }

    getLastUpdatedLabel() {
        return formatDate(this.stats?.knowledge_graph?.last_updated || new Date().toISOString());
    }

    getTemporalSummary() {
        if (!this.temporalQuery.result) return '';
        const count = Number(this.temporalQuery.result.total_active || 0);
        return `${count} active relationship${count === 1 ? '' : 's'} on ${formatDate(this.temporalQuery.result.target_date)} for ${this.temporalQuery.result.entity}.`;
    }

    getSuggestedPatientId() {
        const selectedNode = this.getSelectedNode();
        if (selectedNode && this.getNodeType(selectedNode) === 'patient') {
            return String(selectedNode.id || selectedNode.name || '').trim();
        }
        return '';
    }

    destroyLabTrendChart() {
        if (this.labTrendChart) {
            this.labTrendChart.destroy();
            this.labTrendChart = null;
        }
    }

    getNodeColor(type) {
        return {
            patient: '#c084fc',
            drug: '#2dd4bf',
            condition: '#fbbf24',
            lab: '#60a5fa',
            document: '#94a3b8',
            entity: '#64748b',
        }[type] || '#64748b';
    }

    isSearchMatch(node) {
        if (!this.searchTerm.trim()) return true;
        const haystack = `${node.name || ''} ${node.label || ''}`.toLowerCase();
        return haystack.includes(this.searchTerm.trim().toLowerCase());
    }

    renderStatsBar(visibleGraph) {
        return `
            <div class="graph-stats">
                <span class="filter-pill">Visible Nodes ${visibleGraph.nodes.length}</span>
                <span class="filter-pill">Visible Edges ${visibleGraph.links.length}</span>
                <span class="filter-pill">Source ${escapeHtml(this.graphData.source || 'graph')}</span>
                <span class="filter-pill">Last Updated ${escapeHtml(this.getLastUpdatedLabel())}</span>
                ${this.getCurrentTimelineDate() ? `<span class="filter-pill">Timeline ${escapeHtml(formatDate(this.getCurrentTimelineDate()))}</span>` : ''}
            </div>
        `;
    }

    renderToolbar() {
        const types = this.getNodeTypes();
        const currentDate = this.getCurrentTimelineDate();
        const patientIdValue = this.labTrends.patientId || this.getSuggestedPatientId();
        return `
            <section class="glass-panel graph-toolbar">
                <div class="graph-toolbar__search-pane" style="display: flex; flex-direction: column; gap: 10px; width: 100%;">
                    <label class="field graph-toolbar__search" style="width: 100%;">
                        <span class="field-label">Search Entities</span>
                        <input id="graph-search" class="field-input" type="search" placeholder="Search patients, drugs, conditions, or labs" value="${escapeAttr(this.searchTerm)}" />
                    </label>
                    <label class="field graph-toolbar__patient-id" style="width: 100%;">
                        <span class="field-label">Patient ID Scope</span>
                        <div style="display: flex; gap: 8px; width: 100%;">
                            <input id="patient-filter-input" class="field-input" type="text" placeholder="Filter patient ID (e.g. pat-1)" value="${escapeAttr(this.patientFilterId)}" style="flex: 1;" />
                            <button type="button" class="button button--secondary" id="apply-patient-filter" style="min-height: 38px;">Filter</button>
                        </div>
                    </label>
                </div>
                <div class="graph-toolbar__filters">
                    <div class="field-label">Type Filters</div>
                    <div class="graph-type-filters">
                        ${types.map((type) => `
                            <label class="graph-filter-check">
                                <input type="checkbox" data-graph-type="${escapeAttr(type)}" ${this.typeFilters.has(type) ? 'checked' : ''} />
                                <span>${escapeHtml(type)}</span>
                            </label>
                        `).join('')}
                    </div>
                </div>
                <div class="graph-toolbar__timeline">
                    <div class="field-label">Temporal Filter</div>
                    ${this.timelineDates.length ? `
                        <input id="graph-timeline" type="range" min="0" max="${Math.max(this.timelineDates.length - 1, 0)}" value="${Math.max(this.timelineIndex, 0)}" />
                        <div class="graph-toolbar__timeline-label">${escapeHtml(formatDate(currentDate))}</div>
                    ` : '<div class="empty-inline">No temporal edges available in this graph snapshot.</div>'}
                </div>
                <div class="graph-toolbar__lab">
                    <div class="field-label">Lab Trends</div>
                    <div class="graph-toolbar__lab-controls">
                        <input type="text" id="patient-id-input" class="field-input" placeholder="Patient ID for lab trends" value="${escapeAttr(patientIdValue)}" />
                        <div class="graph-toolbar__lab-actions">
                            <button type="button" class="button button--secondary" id="load-lab-trends">Load Lab Trends</button>
                            <button type="button" class="button button--ghost" id="toggle-lab-trends">Lab Trends</button>
                        </div>
                    </div>
                </div>
                <div class="graph-toolbar__actions">
                    <button type="button" class="button button--secondary" id="graph-temporal-btn">Temporal Query</button>
                </div>
            </section>
        `;
    }

    renderSidePanel() {
        const node = this.getSelectedNode();
        if (!node) {
            return `
                <aside class="glass-panel graph-sidepanel">
                    <div class="eyebrow">Entity Details</div>
                    <h3 class="graph-sidepanel__title">Select a node</h3>
                    <p class="page-subtitle">Click a node to inspect its connections, dates, and clinical context. Double-click a node to start a chat about it.</p>
                </aside>
            `;
        }

        const connections = this.getNodeConnections(node.id);
        return `
            <aside class="glass-panel graph-sidepanel">
                <div class="eyebrow">Entity Details</div>
                <h3 class="graph-sidepanel__title">${escapeHtml(node.name || node.id)}</h3>
                <div class="graph-sidepanel__chips">
                    <span class="filter-pill">${escapeHtml(this.getNodeType(node))}</span>
                    <span class="filter-pill">Connections ${connections.length}</span>
                </div>
                <div class="graph-sidepanel__meta">
                    ${Object.entries(node || {}).filter(([key]) => !['id', 'name', 'label', 'x', 'y', 'vx', 'vy'].includes(key)).map(([key, value]) => `
                        <div class="graph-detail-row">
                            <span class="graph-detail-row__key">${escapeHtml(key)}</span>
                            <span class="graph-detail-row__value">${escapeHtml(String(value))}</span>
                        </div>
                    `).join('') || '<div class="empty-inline">No additional metadata on this node.</div>'}
                </div>
                <div class="graph-sidepanel__connections">
                    <div class="field-label">Connections</div>
                    ${connections.length ? connections.map((connection) => `
                        <article class="graph-connection">
                            <div class="graph-connection__top">
                                <span class="graph-connection__peer">${escapeHtml(connection.peerName)}</span>
                                <span class="graph-connection__type">${escapeHtml(connection.relationship)}</span>
                            </div>
                            <div class="graph-connection__meta">${escapeHtml(connection.direction)} · ${escapeHtml(connection.peerType)}</div>
                            ${connection.startDate || connection.endDate ? `<div class="graph-connection__dates">${escapeHtml(formatDate(connection.startDate))} to ${escapeHtml(connection.endDate ? formatDate(connection.endDate) : 'active')}</div>` : ''}
                        </article>
                    `).join('') : '<div class="empty-inline">No visible connections for this node under the current filters.</div>'}
                </div>
                <button type="button" class="button button--primary button--full" id="graph-chat-node">Chat About This Entity</button>
            </aside>
        `;
    }

    renderTemporalModal() {
        if (!this.temporalQuery.open) return '';
        return `
            <div class="modal-overlay" id="graph-modal-overlay">
                <div class="modal-dialog" role="dialog" aria-modal="true" aria-labelledby="graph-temporal-title">
                    <div class="modal-header">
                        <div>
                            <div class="eyebrow">Temporal Query</div>
                            <h3 id="graph-temporal-title" class="modal-title">Highlight Relationships On A Date</h3>
                        </div>
                        <button type="button" class="icon-button icon-button--ghost" id="graph-close-modal" aria-label="Close modal">x</button>
                    </div>
                    <form id="graph-temporal-form" class="modal-body">
                        <label class="field">
                            <span class="field-label">Entity</span>
                            <input id="graph-temporal-entity" class="field-input" type="text" value="${escapeAttr(this.temporalQuery.entity)}" placeholder="Patient_A or another entity id" />
                        </label>
                        <label class="field">
                            <span class="field-label">Date</span>
                            <input id="graph-temporal-date" class="field-input" type="date" value="${escapeAttr(this.temporalQuery.date)}" />
                        </label>
                        <div class="modal-actions">
                            <button type="submit" class="button button--primary">Run Query</button>
                            <button type="button" class="button button--ghost" id="graph-clear-temporal">Clear Highlight</button>
                        </div>
                    </form>
                </div>
            </div>
        `;
    }

	    renderLabTrendsPanel(patientId) {
        const panelOpen = this.labTrends.open;
        const payload = this.labTrends.data;
        const dataPoints = Array.isArray(payload?.data_points) ? payload.data_points : [];
        const availableLabs = Array.isArray(payload?.available_labs) ? payload.available_labs : [];
        const earliest = payload?.date_range?.earliest || '';
        const latest = payload?.date_range?.latest || '';
        const summary = this.labTrends.error
            || payload?.message
            || (dataPoints.length
                ? `${dataPoints.length} chronologically ordered lab data point${dataPoints.length === 1 ? '' : 's'} loaded.`
                : 'Load a patient to inspect graph-backed lab trends.');

        return `
            <section class="glass-panel graph-lab-panel ${panelOpen ? 'is-open' : ''}">
                <div class="graph-lab-panel__header">
                    <div>
                        <div class="eyebrow">Lab Trends</div>
                        <h3 class="graph-sidepanel__title">${escapeHtml(patientId || 'No patient selected')}</h3>
                        <p class="page-subtitle">${escapeHtml(summary)}</p>
                    </div>
                    <button type="button" class="button button--ghost" id="toggle-lab-trends-panel">${panelOpen ? 'Collapse' : 'Expand'}</button>
                </div>
                ${panelOpen ? `
                    <div class="graph-lab-panel__body">
                        <div class="graph-lab-panel__meta">
                            <span class="filter-pill">Data Points ${escapeHtml(String(dataPoints.length))}</span>
                            <span class="filter-pill">Labs ${escapeHtml(String(availableLabs.length))}</span>
                            ${earliest ? `<span class="filter-pill">Earliest ${escapeHtml(formatDate(earliest))}</span>` : ''}
                            ${latest ? `<span class="filter-pill">Latest ${escapeHtml(formatDate(latest))}</span>` : ''}
                        </div>
                        ${availableLabs.length ? `<div class="graph-lab-panel__available">Available Labs: ${escapeHtml(availableLabs.join(', '))}</div>` : ''}
                        ${this.labTrends.loading ? '<div class="empty-inline">Loading lab trends from the knowledge graph...</div>' : ''}
                        ${!this.labTrends.loading && dataPoints.length && this.labTrends.chartReady ? `
                            <div class="graph-lab-chart">
                                <canvas id="graph-lab-trends-chart"></canvas>
                            </div>
                        ` : ''}
                        ${!this.labTrends.loading && dataPoints.length && !this.labTrends.chartReady ? '<div class="empty-inline">Chart preview unavailable. Table view is still available.</div>' : ''}
                        ${!this.labTrends.loading && dataPoints.length ? `
                            <div class="graph-lab-table-wrap">
                                <table class="graph-lab-table">
                                    <thead>
                                        <tr>
                                            <th>Date</th>
                                            <th>Lab</th>
                                            <th>Value</th>
                                            <th>Source</th>
                                        </tr>
                                    </thead>
                                    <tbody>
                                        ${dataPoints.map((point) => {
                                            const renderedValue = point.value === null || point.value === undefined
                                                ? '&mdash;'
                                                : escapeHtml(`${point.value}${point.value_unit ? ` ${point.value_unit}` : ''}`);
                                            const sourceBits = [point.source_type, point.source_id].filter(Boolean).join(' / ');
                                            return `
                                                <tr>
                                                    <td>${escapeHtml(formatDate(point.date))}</td>
                                                    <td>${escapeHtml(point.lab || '')}</td>
                                                    <td>${renderedValue}</td>
                                                    <td>${escapeHtml(sourceBits || 'Unknown')}</td>
                                                </tr>
                                            `;
                                        }).join('')}
                                    </tbody>
                                </table>
                            </div>
                        ` : ''}
                        ${!this.labTrends.loading && !dataPoints.length ? '<div class="empty-inline">No lab trend rows to display for the current patient selection.</div>' : ''}
                    </div>
                ` : ''}
            </section>
        `;
	    }

	    renderClinicalDataTools() {
	        const normalized = this.normalizationResult?.normalized_entities || [];
	        return `
	            <section class="graph-tools-grid">
	                <article class="glass-panel graph-data-tool">
	                    <div class="graph-data-tool__header">
	                        <div>
	                            <div class="eyebrow">Entity Normalization</div>
	                            <h3>Map clinical terms to ontologies</h3>
	                        </div>
	                    </div>
	                    <form id="normalization-form" class="graph-data-tool__form">
	                        <label class="field">
	                            <span class="field-label">Clinical terms</span>
	                            <textarea id="normalization-input" class="field-input" rows="3" placeholder="hypertension, lisinopril, creatinine">${escapeHtml(this.normalizationText)}</textarea>
	                        </label>
	                        <button type="submit" class="button button--secondary">Normalize Terms</button>
	                    </form>
	                    <div class="document-card__entities">
	                        ${this.ontologies.slice(0, 4).map((ontology) => `<span class="entity-chip">${escapeHtml(ontology.code)} · ${escapeHtml(ontology.name)}</span>`).join('')}
	                    </div>
	                    <div class="normalization-results">
	                        ${normalized.length ? normalized.map((entity) => `
	                            <article class="graph-detail-row">
	                                <span class="graph-detail-row__key">${escapeHtml(entity.surface_form)}</span>
	                                <span class="graph-detail-row__value">${escapeHtml(entity.canonical_label)} · ${escapeHtml(entity.ontology)} ${escapeHtml(entity.concept_id)}</span>
	                            </article>
	                        `).join('') : '<div class="empty-inline">Normalized entities appear here.</div>'}
	                    </div>
	                </article>
	                <article class="glass-panel graph-data-tool">
	                    <div class="graph-data-tool__header">
	                        <div>
	                            <div class="eyebrow">FHIR Import</div>
	                            <h3>Ingest structured patient data</h3>
	                        </div>
	                    </div>
	                    <form id="fhir-ingest-form" class="graph-data-tool__form">
	                        <label class="field">
	                            <span class="field-label">FHIR resource or Bundle JSON</span>
	                            <textarea id="fhir-input" class="field-input" rows="5" placeholder='{"resourceType":"Bundle","entry":[]}'>${escapeHtml(this.fhirText)}</textarea>
	                        </label>
	                        <button type="submit" class="button button--secondary">Ingest FHIR</button>
	                    </form>
	                    ${this.fhirResult ? `
	                        <div class="graph-import-result">
	                            <span class="status-badge status-badge--ready">Imported</span>
	                            <span>${escapeHtml(String(this.fhirResult.nodes || 0))} nodes · ${escapeHtml(String(this.fhirResult.edges || 0))} edges</span>
	                        </div>
	                    ` : '<div class="empty-inline">FHIR ingest updates the knowledge graph using the backend parser.</div>'}
	                </article>
	            </section>
	        `;
	    }

    render() {
        this.destroyLabTrendChart();

        if (this.loading) {
            this.renderLoading();
            return;
        }

        if (this.error) {
            this.innerHTML = `
                <section class="docs-view graph-view">
                    <header class="page-header">
                        <div>
                            <div class="eyebrow">Knowledge Graph</div>
                            <h1 class="page-title">Graph Unavailable</h1>
                            <p class="page-subtitle">${escapeHtml(this.error)}</p>
                        </div>
                    </header>
                    <section class="empty-state empty-state--compact">
                        <div class="empty-state__icon">KG</div>
                        <h2 class="empty-state__title empty-state__title--compact">Unable to load the graph</h2>
                        <p class="empty-state__body">Retry the graph request and restore the latest relationship map.</p>
                        <button type="button" id="graph-retry-btn" class="button button--primary">Retry</button>
                    </section>
                </section>
            `;
            return;
        }

        const visibleGraph = this.getVisibleGraph();
        this.innerHTML = `
            <section class="docs-view graph-view">
                <header class="page-header">
                    <div>
                        <div class="eyebrow">Knowledge Graph</div>
                        <h1 class="page-title">Temporal Entity Map</h1>
                        <p class="page-subtitle">Explore clinical relationships, adjust temporal filters, and jump directly into chat with the entity that needs follow-up.</p>
                    </div>
                </header>
                ${this.renderToolbar()}
	                ${this.renderStatsBar(visibleGraph)}
	                ${this.temporalQuery.result ? `<section class="glass-panel graph-temporal-summary">${escapeHtml(this.getTemporalSummary())}</section>` : ''}
	                <div class="graph-layout">
                    <section class="glass-panel graph-canvas-panel">
                        <div id="graph-canvas" class="graph-canvas"></div>
                        <div id="graph-tooltip" class="graph-tooltip" hidden></div>
                    </section>
                    ${this.renderSidePanel()}
	                </div>
	                ${this.renderLabTrendsPanel(this.labTrends.patientId || this.getSuggestedPatientId())}
	                ${this.renderClinicalDataTools()}
	                ${this.renderTemporalModal()}
	            </section>
	        `;
    }

    setupEvents() {
        const searchInput = this.querySelector('#graph-search');
        const timelineInput = this.querySelector('#graph-timeline');
        const temporalButton = this.querySelector('#graph-temporal-btn');
        const patientIdInput = this.querySelector('#patient-id-input');
        const loadLabTrendsButton = this.querySelector('#load-lab-trends');
        const toggleLabTrendsButton = this.querySelector('#toggle-lab-trends');
        const toggleLabTrendsPanel = this.querySelector('#toggle-lab-trends-panel');
        const modalOverlay = this.querySelector('#graph-modal-overlay');
        const closeModal = this.querySelector('#graph-close-modal');
	        const temporalForm = this.querySelector('#graph-temporal-form');
	        const normalizationForm = this.querySelector('#normalization-form');
	        const fhirForm = this.querySelector('#fhir-ingest-form');
        const clearTemporal = this.querySelector('#graph-clear-temporal');
        const chatNodeButton = this.querySelector('#graph-chat-node');
        const retryButton = this.querySelector('#graph-retry-btn');

        retryButton?.addEventListener('click', async () => {
            this.loading = true;
            this.error = '';
            this.renderLoading();
            try {
                await Promise.all([
                    ensureD3(),
                    this.loadGraph(),
                ]);
                this.loading = false;
                this.render();
                this.setupEvents();
                this.mountGraph();
            } catch (error) {
                this.loading = false;
                this.error = error.message || 'Unable to load graph data.';
                this.render();
                this.setupEvents();
            }
        });

        searchInput?.addEventListener('input', () => {
            this.searchTerm = searchInput.value;
            this.render();
            this.setupEvents();
            this.mountGraph();
        });

        const patientFilterInput = this.querySelector('#patient-filter-input');
        const applyPatientFilterButton = this.querySelector('#apply-patient-filter');

        const triggerPatientFilter = async () => {
            const filterVal = patientFilterInput?.value.trim() || '';
            this.patientFilterId = filterVal;
            this.loading = true;
            this.renderLoading();
            try {
                await this.loadGraph();
                this.loading = false;
                this.render();
                this.setupEvents();
                this.mountGraph();
            } catch (error) {
                this.loading = false;
                this.error = error.message || 'Unable to load graph data.';
                this.render();
                this.setupEvents();
            }
        };

        applyPatientFilterButton?.addEventListener('click', triggerPatientFilter);
        patientFilterInput?.addEventListener('keydown', (event) => {
            if (event.key === 'Enter') {
                event.preventDefault();
                triggerPatientFilter();
            }
        });

        patientIdInput?.addEventListener('input', () => {
            this.labTrends.patientId = patientIdInput.value;
        });

        timelineInput?.addEventListener('input', () => {
            this.timelineIndex = Number(timelineInput.value);
            this.render();
            this.setupEvents();
            this.mountGraph();
        });

        this.querySelectorAll('[data-graph-type]').forEach((checkbox) => {
            checkbox.addEventListener('change', () => {
                const type = checkbox.getAttribute('data-graph-type');
                if (!type) return;
                if (checkbox.checked) this.typeFilters.add(type);
                else this.typeFilters.delete(type);
                this.render();
                this.setupEvents();
                this.mountGraph();
            });
        });

        temporalButton?.addEventListener('click', () => {
            const selectedNode = this.getSelectedNode();
            this.temporalQuery.open = true;
            this.temporalQuery.entity = selectedNode?.id ? String(selectedNode.id) : this.temporalQuery.entity;
            this.temporalQuery.date = this.temporalQuery.date || isoToDateValue(this.getCurrentTimelineDate()) || new Date().toISOString().slice(0, 10);
            this.render();
            this.setupEvents();
            this.mountGraph();
        });

        const toggleLabTrends = () => {
            const suggestedPatientId = patientIdInput?.value.trim() || this.labTrends.patientId || this.getSuggestedPatientId();
            if (!this.labTrends.patientId && suggestedPatientId) {
                this.labTrends.patientId = suggestedPatientId;
            }
            this.labTrends.open = !this.labTrends.open;
            this.render();
            this.setupEvents();
            this.mountGraph();
        };

        toggleLabTrendsButton?.addEventListener('click', toggleLabTrends);
        toggleLabTrendsPanel?.addEventListener('click', toggleLabTrends);

        loadLabTrendsButton?.addEventListener('click', async () => {
            await this.loadLabTrends(patientIdInput?.value.trim() || this.labTrends.patientId || this.getSuggestedPatientId());
        });

        modalOverlay?.addEventListener('click', (event) => {
            if (event.target !== modalOverlay) return;
            this.temporalQuery.open = false;
            this.render();
            this.setupEvents();
            this.mountGraph();
        });

        closeModal?.addEventListener('click', () => {
            this.temporalQuery.open = false;
            this.render();
            this.setupEvents();
            this.mountGraph();
        });

        clearTemporal?.addEventListener('click', () => {
            this.temporalQuery = {
                open: false,
                entity: '',
                date: '',
                matches: new Set(),
                result: null,
            };
            this.render();
            this.setupEvents();
            this.mountGraph();
        });

	        temporalForm?.addEventListener('submit', async (event) => {
	            event.preventDefault();
	            const entity = this.querySelector('#graph-temporal-entity')?.value.trim() || '';
            const date = this.querySelector('#graph-temporal-date')?.value || '';
            if (!entity || !date) {
                showToast('Choose both an entity and a date for temporal query.', 'warning');
                return;
            }
	            await this.runTemporalQuery(entity, date);
	        });

	        normalizationForm?.addEventListener('submit', async (event) => {
	            event.preventDefault();
	            await this.runNormalization();
	        });

	        fhirForm?.addEventListener('submit', async (event) => {
	            event.preventDefault();
	            await this.ingestFhir();
	        });

        chatNodeButton?.addEventListener('click', async () => {
            const selectedNode = this.getSelectedNode();
            if (!selectedNode) return;
            primeChatContext({
                draft: `Explain the clinical relevance of ${selectedNode.name || selectedNode.id} and summarize its graph relationships.`,
                resetSession: true,
            });
            await navigate('/');
            showToast(`${selectedNode.name || selectedNode.id} queued for a new chat.`, 'success', 2500);
        });
    }

    async runTemporalQuery(entity, date) {
        try {
            const result = await getTemporalGraphState(entity, date);
            const matches = new Set();
            (result.active_relationships || []).forEach((item) => {
                this.graphData.links.forEach((link) => {
                    const forward = String(link.source) === String(entity) && item.target_entity && String(link.target) === String(item.target_entity) && link.type === item.relationship;
                    const backward = item.source_entity && String(link.target) === String(entity) && String(link.source) === String(item.source_entity) && `IS_${link.type}_OF` === item.relationship;
                    if (forward || backward) {
                        matches.add(`${link.source}|${link.target}|${link.type}`);
                    }
                });
            });
            this.temporalQuery = {
                open: false,
                entity,
                date,
                matches,
                result,
            };
            showToast('Temporal relationships highlighted on the graph.', 'success', 2500);
            this.render();
            this.setupEvents();
            this.mountGraph();
        } catch (error) {
            showToast(error.message || 'Temporal query failed.', 'error');
        }
    }

    async loadLabTrends(patientId) {
        const normalizedPatientId = String(patientId || '').trim();
        if (!normalizedPatientId) {
            showToast('Enter a patient ID to load lab trends.', 'warning');
            return;
        }

        this.labTrends = {
            ...this.labTrends,
            open: true,
            loading: true,
            patientId: normalizedPatientId,
            data: null,
            error: '',
        };
        this.render();
        this.setupEvents();
        this.mountGraph();

        try {
            const [payload, chartReady] = await Promise.all([
                getPatientLabTrends(normalizedPatientId),
                ensureChartJs().then(() => true).catch(() => false),
            ]);
            this.labTrends = {
                open: true,
                loading: false,
                patientId: normalizedPatientId,
                data: payload,
                error: '',
                chartReady,
            };
            if (!chartReady && Array.isArray(payload?.data_points) && payload.data_points.length) {
                showToast('Chart preview unavailable. Showing table only.', 'info', 2500);
            }
            this.render();
            this.setupEvents();
            this.mountGraph();
        } catch (error) {
            this.labTrends = {
                ...this.labTrends,
                open: true,
                loading: false,
                patientId: normalizedPatientId,
                data: null,
                error: error.message || 'Unable to load lab trends.',
                chartReady: false,
            };
            this.render();
            this.setupEvents();
            this.mountGraph();
        }
    }

    async runNormalization() {
        this.normalizationText = this.querySelector('#normalization-input')?.value.trim() || '';
        const terms = this.normalizationText
            .split(/[\n,]+/)
            .map((value) => value.trim())
            .filter(Boolean)
            .map((surface_form) => ({ surface_form }));
        if (!terms.length) {
            showToast('Enter at least one clinical term to normalize.', 'warning');
            return;
        }
        try {
            this.normalizationResult = await normalizeEntities(terms);
            this.render();
            this.setupEvents();
            this.mountGraph();
            showToast('Clinical entities normalized.', 'success', 2500);
        } catch (error) {
            showToast(error.message || 'Entity normalization failed.', 'error');
        }
    }

    async ingestFhir() {
        this.fhirText = this.querySelector('#fhir-input')?.value.trim() || '';
        if (!this.fhirText) {
            showToast('Paste a FHIR resource or Bundle JSON payload.', 'warning');
            return;
        }
        let payload = null;
        try {
            payload = JSON.parse(this.fhirText);
        } catch (_) {
            showToast('FHIR import requires valid JSON.', 'warning');
            return;
        }
        try {
            this.fhirResult = await ingestFhirBundle(payload);
            await this.loadGraph();
            this.render();
            this.setupEvents();
            this.mountGraph();
            showToast(this.fhirResult.message || 'FHIR data ingested.', 'success', 2500);
        } catch (error) {
            showToast(error.message || 'FHIR ingest failed.', 'error');
        }
    }

    renderLabTrendsChart() {
        this.destroyLabTrendChart();
        if (!this.labTrends.open || !this.labTrends.chartReady || typeof window.Chart === 'undefined') return;

        const canvas = this.querySelector('#graph-lab-trends-chart');
        const dataPoints = Array.isArray(this.labTrends.data?.data_points) ? this.labTrends.data.data_points : [];
        if (!canvas || !dataPoints.length) return;

        this.labTrendChart = new window.Chart(canvas, {
            type: 'line',
            data: {
                labels: dataPoints.map((point) => `${formatDate(point.date)} · ${point.lab}`),
                datasets: [
                    {
                        label: 'Observation Sequence',
                        data: dataPoints.map((_point, index) => index + 1),
                        borderColor: '#60a5fa',
                        backgroundColor: 'rgba(96, 165, 250, 0.18)',
                        borderWidth: 2,
                        fill: true,
                        tension: 0.25,
                        pointRadius: 3,
                        pointHoverRadius: 5,
                    },
                ],
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: {
                        display: true,
                    },
                    tooltip: {
                        callbacks: {
                            label: (context) => {
                                const point = dataPoints[context.dataIndex];
                                const value = point?.value === null || point?.value === undefined
                                    ? 'Value unavailable'
                                    : `${point.value}${point.value_unit ? ` ${point.value_unit}` : ''}`;
                                return `${point?.lab || 'Lab'}: ${value}`;
                            },
                        },
                    },
                },
                scales: {
                    x: {
                        ticks: {
                            maxRotation: 0,
                            autoSkip: true,
                        },
                    },
                    y: {
                        beginAtZero: true,
                        ticks: {
                            precision: 0,
                            stepSize: 1,
                        },
                        title: {
                            display: true,
                            text: 'Data Point Index',
                        },
                    },
                },
            },
        });
    }

    mountGraph() {
        const container = this.querySelector('#graph-canvas');
        if (!container || typeof window.d3 === 'undefined') {
            this.renderLabTrendsChart();
            return;
        }
        const tooltip = this.querySelector('#graph-tooltip');
        const d3 = window.d3;
        container.innerHTML = '';

        const isLightTheme = document.documentElement.classList.contains('light-theme');

        const { nodes, links } = this.getVisibleGraph();
        if (!nodes.length) {
            container.innerHTML = `
                <div class="empty-state empty-state--compact">
                    <div class="empty-state__icon">KG</div>
                    <h3 class="empty-state__title empty-state__title--compact">No Nodes Match These Filters</h3>
                    <p class="empty-state__body">Adjust the type filters, temporal slider, or search term to bring more graph relationships back into view.</p>
                    <button type="button" id="graph-reset-filters" class="button button--primary">Reset Filters</button>
                </div>
            `;
            this.querySelector('#graph-reset-filters')?.addEventListener('click', async () => {
                this.searchTerm = '';
                this.patientFilterId = '';
                this.typeFilters = new Set(this.getNodeTypes());
                this.timelineIndex = this.timelineDates.length ? this.timelineDates.length - 1 : -1;
                this.temporalQuery = {
                    open: false,
                    entity: '',
                    date: '',
                    matches: new Set(),
                    result: null,
                };
                this.loading = true;
                this.renderLoading();
                try {
                    await this.loadGraph();
                    this.loading = false;
                    this.render();
                    this.setupEvents();
                    this.mountGraph();
                } catch (error) {
                    this.loading = false;
                    this.error = error.message || 'Unable to load graph data.';
                    this.render();
                    this.setupEvents();
                }
            });
            this.renderLabTrendsChart();
            return;
        }

        const degree = this.getDegreeMap(nodes, links);
        const width = Math.max(container.clientWidth, 640);
        const height = Math.max(container.clientHeight || 620, 620);
        const svg = d3.select(container)
            .append('svg')
            .attr('viewBox', `0 0 ${width} ${height}`)
            .attr('class', 'graph-svg');

        const root = svg.append('g');
        svg.call(
            d3.zoom().scaleExtent([0.35, 2.4]).on('zoom', (event) => {
                root.attr('transform', event.transform);
            }),
        );

        const nodeData = nodes.map((node) => ({ ...node }));
        const linkData = links.map((link) => ({ ...link, key: `${link.source}|${link.target}|${link.type}` }));

        const linkSelection = root.append('g')
            .attr('class', 'graph-links')
            .selectAll('line')
            .data(linkData)
            .enter()
            .append('line')
            .attr('class', (link) => `graph-link ${link.start_date || link.end_date ? 'is-temporal' : ''} ${this.temporalQuery.matches.has(link.key) ? 'is-highlighted' : ''}`)
            .attr('stroke-width', (link) => this.temporalQuery.matches.has(link.key) ? 2.8 : 1.7)
            .attr('stroke', (link) => this.temporalQuery.matches.has(link.key) ? '#fbbf24' : (isLightTheme ? 'rgba(15,23,42,0.18)' : 'rgba(255,255,255,0.18)'))
            .attr('stroke-dasharray', (link) => (link.start_date || link.end_date ? '6 5' : null))
            .attr('opacity', (link) => {
                const sourceNode = nodes.find((node) => String(node.id) === String(link.source));
                const targetNode = nodes.find((node) => String(node.id) === String(link.target));
                const match = this.isSearchMatch(sourceNode || {}) || this.isSearchMatch(targetNode || {});
                return match ? 0.8 : 0.12;
            });

        const nodeSelection = root.append('g')
            .attr('class', 'graph-nodes')
            .selectAll('circle')
            .data(nodeData)
            .enter()
            .append('circle')
            .attr('class', 'graph-node')
            .attr('r', (node) => 10 + Math.min(degree.get(String(node.id)) || 0, 8) * 1.4)
            .attr('fill', (node) => this.getNodeColor(this.getNodeType(node)))
            .attr('stroke', (node) => (String(node.id) === String(this.selectedNodeId) ? (isLightTheme ? '#0f172a' : '#f8fafc') : (isLightTheme ? '#ffffff' : 'rgba(15,23,42,0.9)')))
            .attr('stroke-width', (node) => (String(node.id) === String(this.selectedNodeId) ? 3 : 1.8))
            .attr('opacity', (node) => (this.isSearchMatch(node) ? 1 : 0.18))
            .on('mouseenter', (event, node) => {
                if (!tooltip) return;
                tooltip.hidden = false;
                tooltip.innerHTML = `${escapeHtml(node.name || node.id)}<br/><span>${escapeHtml(this.getNodeType(node))} · degree ${degree.get(String(node.id)) || 0}</span>`;
                tooltip.style.left = `${event.clientX + 16}px`;
                tooltip.style.top = `${event.clientY + 16}px`;
            })
            .on('mousemove', (event) => {
                if (!tooltip) return;
                tooltip.style.left = `${event.clientX + 16}px`;
                tooltip.style.top = `${event.clientY + 16}px`;
            })
            .on('mouseleave', () => {
                if (tooltip) tooltip.hidden = true;
            })
            .on('click', (_event, node) => {
                this.selectedNodeId = String(node.id);
                this.render();
                this.setupEvents();
                this.mountGraph();
            })
            .on('dblclick', async (_event, node) => {
                primeChatContext({
                    draft: `Explain the clinical relevance of ${node.name || node.id} and summarize its graph relationships.`,
                    resetSession: true,
                });
                await navigate('/');
                showToast(`${node.name || node.id} queued for a new chat.`, 'success', 2500);
            });

        const labelSelection = root.append('g')
            .attr('class', 'graph-labels')
            .selectAll('text')
            .data(nodeData)
            .enter()
            .append('text')
            .attr('class', 'graph-label')
            .text((node) => node.name || node.id)
            .attr('font-size', 11)
            .attr('fill', isLightTheme ? '#0f172a' : 'rgba(226,232,240,0.92)')
            .attr('opacity', (node) => (this.isSearchMatch(node) ? 1 : 0.12));

        const simulation = d3.forceSimulation(nodeData)
            .force('link', d3.forceLink(linkData).id((d) => d.id).distance((link) => ((link.start_date || link.end_date) ? 132 : 96)))
            .force('charge', d3.forceManyBody().strength(-320))
            .force('center', d3.forceCenter(width / 2, height / 2))
            .force('collision', d3.forceCollide().radius((node) => 18 + Math.min(degree.get(String(node.id)) || 0, 8)));

        const drag = d3.drag()
            .on('start', (event, node) => {
                if (!event.active) simulation.alphaTarget(0.3).restart();
                node.fx = node.x;
                node.fy = node.y;
            })
            .on('drag', (_event, node) => {
                node.fx = _event.x;
                node.fy = _event.y;
            })
            .on('end', (event, node) => {
                if (!event.active) simulation.alphaTarget(0);
                node.fx = null;
                node.fy = null;
            });

        nodeSelection.call(drag);

        simulation.on('tick', () => {
            linkSelection
                .attr('x1', (link) => link.source.x)
                .attr('y1', (link) => link.source.y)
                .attr('x2', (link) => link.target.x)
                .attr('y2', (link) => link.target.y);

            nodeSelection
                .attr('cx', (node) => node.x)
                .attr('cy', (node) => node.y);

            labelSelection
                .attr('x', (node) => node.x + 12)
                .attr('y', (node) => node.y + 4);
        });

        this.renderLabTrendsChart();
    }
}

customElements.define('knowledge-graph', KnowledgeGraph);
