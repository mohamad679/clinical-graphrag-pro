import {
    getAgentWorkflow,
    listAgentTools,
    listAgentWorkflows,
    showToast,
    streamAgentWorkflow,
} from '../api.js';

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

function formatTimestamp(value) {
    if (!value) return 'Just now';
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return 'Just now';
    return date.toLocaleString();
}

function renderInlineMarkdown(text = '') {
    return escapeHtml(text)
        .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
        .replace(/\*(.+?)\*/g, '<em>$1</em>')
        .replace(/`([^`]+)`/g, '<code>$1</code>');
}

function renderMarkdown(text = '') {
    const lines = String(text || '').split('\n');
    const html = [];
    let inUl = false;
    let inOl = false;
    let tableRows = [];

    const closeLists = () => {
        if (inUl) {
            html.push('</ul>');
            inUl = false;
        }
        if (inOl) {
            html.push('</ol>');
            inOl = false;
        }
    };

    const flushTable = () => {
        if (!tableRows.length) return;
        const parseRow = (row) => row.replace(/^\||\|$/g, '').split('|').map((cell) => cell.trim());
        const isSeparatorRow = (row) => parseRow(row).every((cell) => /^:?-{3,}:?$/.test(cell));
        const hasSeparator = tableRows.length > 1 && isSeparatorRow(tableRows[1]);
        const rawHeader = parseRow(tableRows[0]);
        const rawBody = (hasSeparator ? tableRows.slice(2) : tableRows.slice(1)).map(parseRow);
        const columnCount = Math.max(rawHeader.length, ...rawBody.map((row) => row.length), 1);
        const normalizeRow = (row) => Array.from({ length: columnCount }, (_, index) => row[index] || '');
        const header = normalizeRow(rawHeader);
        const body = rawBody.map(normalizeRow);
        html.push(`
            <div class="md-table-wrap">
                <table class="md-table">
                    <thead><tr>${header.map((cell) => `<th>${renderInlineMarkdown(cell)}</th>`).join('')}</tr></thead>
                    <tbody>
                        ${body.map((row) => `<tr>${row.map((cell) => `<td>${renderInlineMarkdown(cell)}</td>`).join('')}</tr>`).join('')}
                    </tbody>
                </table>
            </div>
        `);
        tableRows = [];
    };

    lines.forEach((line) => {
        const trimmed = line.trim();

        const isTableRow = trimmed.startsWith('|') && trimmed.endsWith('|');
        const isSeparator = /^\|[\s\-:|]+\|$/.test(trimmed);
        if (isTableRow || isSeparator) {
            closeLists();
            tableRows.push(line);
            return;
        }
        flushTable();

        if (!trimmed) {
            closeLists();
            html.push('<div class="md-spacer"></div>');
            return;
        }

        if (trimmed.startsWith('#### ')) {
            closeLists();
            html.push(`<h4>${renderInlineMarkdown(trimmed.slice(5))}</h4>`);
            return;
        }
        if (trimmed.startsWith('### ')) {
            closeLists();
            html.push(`<h3>${renderInlineMarkdown(trimmed.slice(4))}</h3>`);
            return;
        }
        if (trimmed.startsWith('## ')) {
            closeLists();
            html.push(`<h2>${renderInlineMarkdown(trimmed.slice(3))}</h2>`);
            return;
        }
        if (trimmed.startsWith('# ')) {
            closeLists();
            html.push(`<h1>${renderInlineMarkdown(trimmed.slice(2))}</h1>`);
            return;
        }
        if (trimmed.startsWith('- ') || trimmed.startsWith('* ')) {
            if (!inUl) {
                closeLists();
                html.push('<ul>');
                inUl = true;
            }
            html.push(`<li>${renderInlineMarkdown(trimmed.slice(2))}</li>`);
            return;
        }
        if (/^\d+\. /.test(trimmed)) {
            if (!inOl) {
                closeLists();
                html.push('<ol>');
                inOl = true;
            }
            html.push(`<li>${renderInlineMarkdown(trimmed.replace(/^\d+\. /, ''))}</li>`);
            return;
        }

        closeLists();
        html.push(`<p>${renderInlineMarkdown(trimmed)}</p>`);
    });

    flushTable();
    closeLists();
    return html.join('');
}

function formatJson(value) {
    try {
        return JSON.stringify(value, null, 2);
    } catch (_) {
        return '{}';
    }
}

function summarizeOutput(output) {
    if (!output) return 'Waiting for tool result.';
    if (typeof output.error === 'string' && output.error.trim()) return output.error;
    if (Array.isArray(output.results)) return `${output.results.length} result(s) returned.`;
    if (Array.isArray(output.interactions)) return `${output.interactions.length} interaction findings returned.`;
    if (typeof output.analysis === 'string' && output.analysis.trim()) return output.analysis.slice(0, 160);
    if (output.analysis?.summary) return output.analysis.summary;
    return 'Result available.';
}

class AiWorkflows extends HTMLElement {
    constructor() {
        super();
        this.ready = false;
        this.loading = true;
        this.running = false;
        this.agentState = 'idle'; // idle, thinking, planning, using tools, running, completed, failed
        this.workflowType = 'general';
        this.query = '';
        this.history = [];
        this.toolDefinitions = [];
        this.reasoningSteps = [];
        this.timeline = [];
        this.verification = null;
        this.finalAnswer = '';
        this.currentWorkflowId = '';
        this.selectedWorkflowId = '';
        this.historyOpen = true;
        this.expandedCards = new Set();
        this.traceEvents = [];
        this.evidenceList = [];
    }

    async connectedCallback() {
        this.renderLoading();
        try {
            await this.bootstrap();
        } catch (error) {
            this.renderError(error.message || 'Unable to load the agent workspace.');
            this.setupEvents();
        }
    }

    async bootstrap() {
        const [historyResponse, tools] = await Promise.all([
            listAgentWorkflows({ limit: 12 }),
            listAgentTools().catch(() => []),
        ]);
        this.history = historyResponse?.workflows || [];
        this.toolDefinitions = Array.isArray(tools) ? tools : [];
        this.loading = false;
        this.ready = true;
        this.render();
        this.setupEvents();
    }

    renderLoading() {
        this.innerHTML = `
            <section class="docs-view workflow-view">
                <header class="page-header">
                    <div>
                        <div class="eyebrow">AI Workflows</div>
                        <h1 class="page-title">Loading Workflow Studio</h1>
                        <p class="page-subtitle pulse">Initializing agent workflow runners...</p>
                    </div>
                </header>
            </section>
        `;
    }

    renderError(message) {
        this.innerHTML = `
            <section class="docs-view workflow-view">
                <header class="page-header">
                    <div>
                        <div class="eyebrow">AI Workflows</div>
                        <h1 class="page-title">Workspace Offline</h1>
                        <p class="page-subtitle">${escapeHtml(message)}</p>
                    </div>
                </header>
            </section>
        `;
    }

    resetRunState() {
        this.reasoningSteps = [];
        this.timeline = [];
        this.verification = null;
        this.finalAnswer = '';
        this.currentWorkflowId = '';
        this.selectedWorkflowId = '';
        this.expandedCards.clear();
        this.expandedCards.add('trace-canvas');
        this.traceEvents = [];
        this.evidenceList = [];
    }

    getHistoryLabel(workflow) {
        const query = workflow?.input_data?.query || 'Workflow run';
        return query.length > 48 ? `${query.slice(0, 48)}...` : query;
    }

    renderWorkflowCards() {
        const triggers = [
            { id: 'soap', label: 'Generate SOAP Note', desc: 'Create a source-grounded note from session records.', query: 'Extract subjective patient concerns, objective findings, diagnostics, and formulate a SOAP note.', type: 'data_extraction' },
            { id: 'chart', label: 'Summarize Chart', desc: 'Synthesize patient case records and milestones.', query: 'Analyze all indexed medical files and compile a clinical chart summary.', type: 'general' },
            { id: 'scan', label: 'Analyze Image', desc: 'Detect findings and run automated diagnostics.', query: 'Run AI computer vision models on uploaded pulmonary scans.', type: 'general' },
            { id: 'lab', label: 'Review Lab Trends', desc: 'Track lab metrics and outliers over time.', query: 'Plot lab trends to trace outliers and cross-reference with treatments.', type: 'general' },
            { id: 'entity', label: 'Extract Entities', desc: 'Map clinical text to SNOMED/RxNorm.', query: 'Examine clinical logs and normalize all drug and disease concepts.', type: 'data_extraction' },
            { id: 'graph', label: 'Build Knowledge Graph', desc: 'Expose temporal/patient graph structures.', query: 'Parse documents to extract structural entities and build patient relationship graph.', type: 'general' },
        ];

        return `
            <div class="workflow-cards-grid" style="display:grid; grid-template-columns: repeat(auto-fill, minmax(220px, 1fr)); gap:12px; margin-bottom:20px;">
                ${triggers.map(t => `
                    <div class="glass-panel workflow-trigger-card" data-trigger-query="${escapeAttr(t.query)}" data-trigger-type="${escapeAttr(t.type)}" style="padding:16px; cursor:pointer; display:flex; flex-direction:column; gap:8px;">
                        <h4 style="margin:0; font-size:14px; color:var(--accent);">${escapeHtml(t.label)}</h4>
                        <p style="margin:0; font-size:11px; color:var(--text-muted); line-height:1.4;">${escapeHtml(t.desc)}</p>
                    </div>
                `).join('')}
            </div>
        `;
    }

    renderRunComposer() {
        const stateColorMap = {
            idle: 'secondary',
            thinking: 'warning',
            planning: 'warning',
            'using tools': 'warning',
            running: 'processing',
            completed: 'ready',
            failed: 'error'
        };
        const activeStateBadge = `<span class="status-badge status-badge--${stateColorMap[this.agentState]}">${this.agentState.toUpperCase()}</span>`;

        return `
            <section class="glass-panel workflow-composer">
                <div class="workflow-composer__header flex-row" style="justify-content:space-between; gap:16px;">
                    <div>
                        <div class="eyebrow">Studio Studio</div>
                        <h2 class="page-title page-title--compact" style="margin:4px 0 0;">Agent Execution Canvas</h2>
                    </div>
                    <div class="flex-row" style="gap:12px;">
                        <div style="font-size:12px; color:var(--text-muted); text-align:right;">
                            Agent State: ${activeStateBadge}
                        </div>
                        <button type="button" class="button button--secondary" id="run-again-btn" ${!this.query.trim() || this.running ? 'disabled' : ''}>Restart</button>
                    </div>
                </div>

                ${this.renderWorkflowCards()}

                <form id="agent-run-form" class="workflow-form" style="margin-top:16px;">
                    <div style="display:grid; grid-template-columns:1fr 240px; gap:16px;">
                        <label class="field workflow-form__query">
                            <span class="field-label">Clinical Workflow Query</span>
                            <textarea id="workflow-query" class="field-input workflow-form__textarea" rows="3" placeholder="Describe the workflow or select a card above to prefill...">${escapeHtml(this.query)}</textarea>
                        </label>
                        
                        <label class="field">
                            <span class="field-label">Workflow Model Mode</span>
                            <select id="workflow-type" class="field-input">
                                ${['general', 'diagnosis', 'pharmacovigilance', 'data_extraction'].map((option) => `
                                    <option value="${option}" ${this.workflowType === option ? 'selected' : ''}>${option.replace('_', ' ')}</option>
                                `).join('')}
                            </select>
                        </label>
                    </div>
                    
                    <div class="workflow-form__actions flex-row" style="margin-top:12px; justify-content:space-between;">
                        <button type="submit" class="button button--primary" ${this.running ? 'disabled' : ''}>
                            ${this.running ? 'Running Workflow State...' : 'Dispatch Agent Workflow'}
                        </button>
                        <span class="workflow-ping-indicator" style="font-size:12px; color:var(--accent);"></span>
                    </div>
                </form>
            </section>
        `;
    }

    renderReasoningRail() {
        if (!this.reasoningSteps.length) return '';
        return `
            <section class="workflow-reasoning" style="margin-top:20px;">
                <div class="eyebrow">Execution Plan Steps</div>
                ${this.reasoningSteps.map((step) => `
                    <article class="workflow-reasoning__item" style="padding:10px 14px; display:flex; justify-content:space-between; align-items:center; background:rgba(255,255,255,0.03); border-radius:10px; margin-top:8px;">
                        <div>
                            <strong style="font-size:13px; color:var(--accent);">Step ${step.step} : ${escapeHtml(step.title)}</strong>
                            <div style="font-size:11px; color:var(--text-muted); margin-top:2px;">${escapeHtml(step.description)}</div>
                        </div>
                        <span class="status-chip status-chip--${escapeAttr(step.status || 'pending')}">${escapeHtml(step.status || 'pending')}</span>
                    </article>
                `).join('')}
            </section>
        `;
    }

    renderTraceCanvas() {
        if (!this.traceEvents.length) return '';
        return `
            <section class="glass-panel workflow-trace-canvas" style="margin-top:20px; padding:16px;">
                <div class="eyebrow">D3 Tool Stream Events</div>
                <div style="background:#090d11; border:1px solid var(--border-subtle); padding:12px; border-radius:12px; font-family:var(--font-mono); font-size:11px; max-height:240px; overflow-y:auto; color:var(--accent); line-height:1.5; margin-top:8px;">
                    ${this.traceEvents.map((evt) => `
                        <div>
                            <span style="color:var(--text-muted);">[${formatTimestamp(evt.timestamp)}]</span>
                            <strong style="color:#60a5fa;">${escapeHtml(evt.type.toUpperCase())}</strong> : 
                            <span>${escapeHtml(evt.message)}</span>
                        </div>
                    `).join('')}
                </div>
            </section>
        `;
    }

    renderToolTimeline() {
        if (!this.timeline.length) {
            return `
                <section class="empty-state" style="margin-top:20px;">
                    <p class="empty-state__body">Tool execution logs and confidence outputs appear here.</p>
                </section>
            `;
        }

        return `
            <section class="workflow-timeline" style="margin-top:20px;">
                <div class="eyebrow">D3 Tool Invocations Map</div>
                ${this.timeline.map((card) => {
                    const expanded = this.expandedCards.has(card.id);
                    return `
                        <article class="workflow-card workflow-card--${escapeAttr(card.status || 'pending')}" style="margin-top:8px;">
                            <button type="button" class="workflow-card__header flex-row" style="justify-content:space-between; width:100%; border:none; background:transparent; padding:10px 14px; text-align:left;" data-toggle-tool-card="${escapeAttr(card.id)}">
                                <div class="workflow-card__title-wrap">
                                    <span class="workflow-tool-badge">${escapeHtml(card.toolName)}</span>
                                    <span style="margin-left:8px; font-size:13px; font-weight:600;">${escapeHtml(card.summary)}</span>
                                </div>
                                <span class="status-chip status-chip--${escapeAttr(card.status)}">${escapeHtml(card.status)}</span>
                            </button>
                            <div class="workflow-card__body ${expanded ? 'is-open' : ''}" style="display:${expanded ? 'block' : 'none'}; padding:12px 14px; border-top:1px solid var(--border-subtle);">
                                <pre style="font-family:var(--font-mono); font-size:11px; margin:0; overflow-x:auto;">${escapeHtml(formatJson(card.output || {}))}</pre>
                            </div>
                        </article>
                    `;
                }).join('')}
            </section>
        `;
    }

    renderFinalAnswer() {
        if (!this.finalAnswer) return '';

        return `
            <section class="glass-panel workflow-answer" style="margin-top:20px; padding:16px;">
                <div class="eyebrow">Synthesized Summary Output</div>
                <div class="markdown-body" style="margin-top:10px; line-height:1.6;">
                    ${renderMarkdown(this.finalAnswer)}
                </div>
            </section>
        `;
    }

    renderHistoryPanel() {
        return `
            <aside class="glass-panel workflow-history ${this.historyOpen ? '' : 'is-collapsed'}" style="width:${this.historyOpen ? '280px' : '64px'}; transition: width var(--transition-base);">
                <div class="workflow-history__header flex-row" style="justify-content:space-between; padding:12px;">
                    ${this.historyOpen ? `
                        <div>
                            <div class="eyebrow">History</div>
                            <div style="font-size:11px; color:var(--text-muted);">${this.history.length} runs</div>
                        </div>
                    ` : ''}
                    <button type="button" class="button button--ghost" id="toggle-history-btn" style="min-height:30px; padding:0 8px;">
                        ${this.historyOpen ? 'Collapse' : '»'}
                    </button>
                </div>
                
                ${this.historyOpen ? `
                    <div class="workflow-history__list" style="display:flex; flex-direction:column; gap:8px; padding:8px; overflow-y:auto; max-height:480px;">
                        ${this.history.map((h) => `
                            <button type="button" class="workflow-history__item ${this.selectedWorkflowId === String(h.id) ? 'is-selected' : ''}" data-open-workflow="${escapeAttr(String(h.id))}" style="text-align:left; background:transparent; border:none; padding:8px; border-radius:8px;">
                                <div style="font-size:12px; font-weight:600; color:var(--accent);">${escapeHtml(h.workflow_type)}</div>
                                <div class="text-truncate" style="font-size:11px; margin-top:2px;">${escapeHtml(h.input_data?.query || 'Run')}</div>
                                <div style="font-size:10px; color:var(--text-muted); margin-top:2px;">${new Date(h.created_at).toLocaleDateString()}</div>
                            </button>
                        `).join('')}
                    </div>
                ` : ''}
            </aside>
        `;
    }

    render() {
        this.innerHTML = `
            <section class="docs-view workflow-view">
                <header class="page-header">
                    <div>
                        <div class="eyebrow">Clinical Planning Studio</div>
                        <h1 class="page-title">AI Workflows</h1>
                        <p class="page-subtitle">Formulate clinical queries, orchestrate autonomous diagnostic workflows, and monitor system tool logs.</p>
                    </div>
                </header>

                <div class="workflow-shell" style="display:flex; gap:20px; margin-top:20px; align-items:flex-start;">
                    ${this.renderHistoryPanel()}
                    
                    <main class="workflow-main" style="flex:1; display:flex; flex-direction:column;">
                        ${this.renderRunComposer()}
                        ${this.renderReasoningRail()}
                        ${this.renderTraceCanvas()}
                        ${this.renderToolTimeline()}
                        ${this.renderFinalAnswer()}
                    </main>
                </div>
            </section>
        `;
    }

    setupEvents() {
        const form = this.querySelector('#agent-run-form');
        const queryInput = this.querySelector('#workflow-query');
        const typeSelect = this.querySelector('#workflow-type');
        const runAgainButton = this.querySelector('#run-again-btn');
        const toggleHistoryButton = this.querySelector('#toggle-history-btn');

        queryInput?.addEventListener('input', () => {
            this.query = queryInput.value;
        });

        typeSelect?.addEventListener('change', () => {
            this.workflowType = typeSelect.value;
        });

        form?.addEventListener('submit', async (event) => {
            event.preventDefault();
            await this.handleRun();
        });

        runAgainButton?.addEventListener('click', async () => {
            await this.handleRun();
        });

        toggleHistoryButton?.addEventListener('click', () => {
            this.historyOpen = !this.historyOpen;
            this.render();
            this.setupEvents();
        });

        // Pre-fill query cards click handler
        this.querySelectorAll('.workflow-trigger-card').forEach((card) => {
            card.addEventListener('click', () => {
                this.query = card.getAttribute('data-trigger-query') || '';
                this.workflowType = card.getAttribute('data-trigger-type') || 'general';
                this.render();
                this.setupEvents();
                this.querySelector('#workflow-query')?.focus();
            });
        });

        this.querySelectorAll('[data-open-workflow]').forEach((button) => {
            button.addEventListener('click', async () => {
                await this.openWorkflow(button.getAttribute('data-open-workflow') || '');
            });
        });

        this.querySelectorAll('[data-toggle-tool-card]').forEach((button) => {
            button.addEventListener('click', () => {
                const id = button.getAttribute('data-toggle-tool-card');
                if (this.expandedCards.has(id)) this.expandedCards.delete(id);
                else this.expandedCards.add(id);
                this.render();
                this.setupEvents();
            });
        });
    }

    async openWorkflow(workflowId) {
        if (!workflowId) return;
        this.selectedWorkflowId = workflowId;
        this.loading = true;
        this.renderLoading();
        try {
            const workflow = await getAgentWorkflow(workflowId);
            this.hydrateWorkflow(workflow);
            this.loading = false;
            this.render();
            this.setupEvents();
        } catch (error) {
            this.loading = false;
            this.render();
            this.setupEvents();
            showToast('Unable to fetch workflow details.', 'error');
        }
    }

    hydrateWorkflow(workflow) {
        this.running = false;
        this.agentState = workflow.status === 'failed' ? 'failed' : 'completed';
        this.currentWorkflowId = String(workflow.id || '');
        this.workflowType = workflow.workflow_type || 'general';
        this.query = workflow.input_data?.query || '';
        this.reasoningSteps = (workflow.steps || []).map((step) => ({
            step: step.step_number,
            title: step.title,
            description: step.description || '',
            status: step.status || 'done',
        }));
        this.timeline = [];
        this.traceEvents = [];
        this.finalAnswer = workflow.output_data?.answer || '';

        (workflow.steps || []).forEach((step) => {
            (step.tool_calls || []).forEach((tc) => {
                this.timeline.push({
                    id: tc.id || `${tc.tool_name}-${Date.now()}`,
                    toolName: tc.tool_name,
                    summary: tc.status === 'completed' ? 'Successfully executed' : 'Failed',
                    status: tc.status === 'completed' ? 'done' : 'error',
                    output: tc.output_data || {},
                });
            });
        });
    }

    async handleRun() {
        const queryVal = this.query.trim();
        if (!queryVal || this.running) return;

        this.resetRunState();
        this.running = true;
        this.agentState = 'planning';
        this.query = queryVal;
        this.render();
        this.setupEvents();

        await streamAgentWorkflow({
            query: queryVal,
            workflowType: this.workflowType,
            onEvent: (event) => this.handleStreamEvent(event),
            onError: (error) => {
                this.running = false;
                this.agentState = 'failed';
                showToast(error.message || 'Workflow run failed.', 'error');
                this.render();
                this.setupEvents();
            },
        });
    }

    handleStreamEvent(event) {
        if (!event) return;
        
        let message = '';
        if (event.type === 'workflow_start') {
            this.agentState = 'running';
            message = 'Supervisor started workflow execution.';
        } else if (event.type === 'plan_created') {
            this.agentState = 'planning';
            message = `Execution plan generated with ${event.metadata?.steps?.length || 0} stages.`;
        } else if (event.type === 'tool_start') {
            this.agentState = 'using tools';
            message = `Invoking tool ${event.tool} with coordinates.`;
            this.timeline.push({
                id: event.tool,
                toolName: event.tool,
                summary: 'Executing tool...',
                status: 'running',
                output: {},
            });
        } else if (event.type === 'tool_complete') {
            this.agentState = 'running';
            message = `Tool ${event.tool} returned findings in ${event.duration || 0}ms.`;
            this.timeline = this.timeline.map(t => t.id === event.tool ? {
                ...t,
                status: 'done',
                summary: 'Completed',
                output: event.output || {},
            } : t);
        } else if (event.type === 'answer_drafted') {
            this.agentState = 'thinking';
            message = 'Formulating diagnostic synthesis.';
        } else if (event.type === 'token') {
            this.agentState = 'running';
            this.finalAnswer += event.content || '';
        } else if (event.type === 'workflow_done' || event.type === 'workflow_complete') {
            this.agentState = 'completed';
            this.running = false;
            message = 'Workflow completed successfully.';
            if (event.answer) this.finalAnswer = event.answer;
            listAgentWorkflows({ limit: 12 }).then(res => {
                this.history = res?.workflows || [];
                this.render();
                this.setupEvents();
            });
        } else if (event.type === 'error') {
            this.agentState = 'failed';
            this.running = false;
            message = `Execution encountered error: ${event.content}`;
        }

        if (event.type !== 'ping') {
            this.traceEvents.push({
                timestamp: event.timestamp || new Date().toISOString(),
                type: event.type,
                message: message || event.description || 'System state update.'
            });
        }

        this.render();
        this.setupEvents();
    }
}

customElements.define('ai-workflows', AiWorkflows);
export default AiWorkflows;
