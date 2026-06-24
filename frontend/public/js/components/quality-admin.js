import {
    apiFetch,
    AuthService,
    blessEvaluationBaseline,
    getEvaluationBaseline,
    reviewEvaluationCase,
    cancelFineTuneJob,
    createFineTuneDataset,
    deleteFineTuneDataset,
    deleteFineTuneModel,
    deployFineTuneModel,
    generateFineTuneSamples,
    listFineTuneDatasets,
    listFineTuneJobs,
    listFineTuneModels,
    registerFineTuneModel,
    startFineTuneTraining,
    undeployFineTuneModel,
    validateFineTuneDataset,
    createAdminUser,
    exportUserData,
    getAdminConfig,
    getAdminHealth,
    getAdminMetrics,
    listAdminSessions,
    listAdminUsers,
    listAuditLog,
    purgeUserData,
    revokeAdminSession,
    showToast,
} from '../api.js';
import { modal } from '../lib/modal.js';
import { ensureChartJs } from '../lib-loader.js';

function escapeHtml(value = '') {
    return String(value)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}

function formatDate(value) {
    if (!value) return 'Unknown';
    const date = new Date(value);
    return Number.isNaN(date.getTime()) ? String(value) : date.toLocaleString();
}

class QualityAdmin extends HTMLElement {
    constructor() {
        super();
        this.activeTab = window.sessionStorage.getItem('clinical_admin_active_tab') || 'evaluations';
        this.user = null;
        this.tabLoading = false;
        this.tabError = '';

        // Evaluations Tab State
        this.latest = null;
        this.history = [];
        this.baseline = null;
        this.isRunningEval = false;
        this.charts = [];

        // Fine-Tuning Tab State
        this.datasets = [];
        this.jobs = [];
        this.models = [];
        this.validationResult = null;
        this.ftDisabledReason = '';

        // Admin Settings Tab State
        this.health = null;
        this.metrics = null;
        this.config = null;
        this.users = [];
        this.sessions = [];
        this.audit = { items: [], total: 0 };
        this.exportResult = null;
    }

    async connectedCallback() {
        this.user = AuthService.getUser() || await AuthService.fetchCurrentUser({ silent: true });
        this.renderShell();
        await this.loadTab(this.activeTab);
    }

    disconnectedCallback() {
        this.destroyCharts();
    }

    destroyCharts() {
        if (this.charts && this.charts.length) {
            this.charts.forEach((chart) => {
                try {
                    chart.destroy();
                } catch (_) {}
            });
            this.charts = [];
        }
    }

    async loadTab(tabName) {
        this.destroyCharts();
        this.tabLoading = true;
        this.tabError = '';
        this.renderTabContent();

        try {
            if (tabName === 'evaluations') {
                const chartReady = ensureChartJs().catch(() => null);
                const [latest, metrics, baseline] = await Promise.all([
                    apiFetch('/evaluations/latest', { silent: true, skipRedirect: true }).catch(() => null),
                    apiFetch('/evaluations/metrics', { silent: true, skipRedirect: true }).catch(() => ({ data: [] })),
                    getEvaluationBaseline().catch(() => null),
                    chartReady,
                ]);
                this.latest = latest;
                this.history = metrics?.data || [];
                this.baseline = baseline;
            } else if (tabName === 'ops') {
                try {
                    const [datasets, jobs, models] = await Promise.all([
                        listFineTuneDatasets(),
                        listFineTuneJobs(),
                        listFineTuneModels(),
                    ]);
                    this.datasets = datasets?.datasets || [];
                    this.jobs = jobs?.jobs || [];
                    this.models = models?.models || [];
                    this.ftDisabledReason = '';
                } catch (error) {
                    if (error.status === 503) {
                        this.ftDisabledReason = error.message || 'Fine-tuning is disabled in this deployment.';
                    } else {
                        throw error;
                    }
                }
            } else if (tabName === 'admin') {
                const [health, metrics, config, users, sessions, audit] = await Promise.all([
                    getAdminHealth(),
                    getAdminMetrics().catch(() => null),
                    getAdminConfig().catch(() => null),
                    listAdminUsers().catch(() => ({ users: [] })),
                    listAdminSessions().catch(() => ({ sessions: [] })),
                    listAuditLog().catch(() => ({ items: [], total: 0 })),
                ]);
                this.health = health;
                this.metrics = metrics;
                this.config = config;
                this.users = users?.users || [];
                this.sessions = sessions?.sessions || [];
                this.audit = audit || { items: [], total: 0 };
            }
        } catch (error) {
            console.error(`Error loading tab: ${tabName}`, error);
            this.tabError = error.message || 'Unable to retrieve dashboard metrics.';
        } finally {
            this.tabLoading = false;
            this.renderTabContent();
            if (tabName === 'evaluations' && !this.tabError) {
                this.renderCharts();
            }
            this.bindEvents();
        }
    }

    renderShell() {
        this.innerHTML = `
            <section class="docs-view ops-view">
                <header class="page-header" style="align-items: center; margin-bottom: 8px;">
                    <div>
                        <div class="eyebrow">Quality & Operations Control</div>
                        <h1 class="page-title" style="margin-bottom: 8px;">Quality & Admin Console</h1>
                        <p class="page-subtitle">Configure model options, monitor safety/groundedness baselines, and manage clinical system parameters.</p>
                    </div>
                </header>

                <div class="library-tabs flex-row" style="gap:12px; margin-bottom:12px; display:flex; flex-wrap:wrap; border-bottom:1px solid var(--border-subtle); padding-bottom:12px;">
                    <button type="button" class="button ${this.activeTab === 'evaluations' ? 'button--primary' : 'button--secondary'}" data-tab="evaluations" style="min-height:38px; padding:0 18px;">
                        📈 Model Evaluations & Baselines
                    </button>
                    <button type="button" class="button ${this.activeTab === 'ops' ? 'button--primary' : 'button--secondary'}" data-tab="ops" style="min-height:38px; padding:0 18px;">
                        ⚙️ Fine-Tuning & Model Ops
                    </button>
                    <button type="button" class="button ${this.activeTab === 'admin' ? 'button--primary' : 'button--secondary'}" data-tab="admin" style="min-height:38px; padding:0 18px;">
                        🛡️ Governance & Auditing
                    </button>
                </div>

                <div id="tab-content-root" class="tab-content" style="min-height: 400px;"></div>
            </section>
        `;

        this.querySelectorAll('[data-tab]').forEach((btn) => {
            btn.addEventListener('click', async () => {
                const tab = btn.getAttribute('data-tab');
                if (this.activeTab === tab) return;

                this.activeTab = tab;
                window.sessionStorage.setItem('clinical_admin_active_tab', tab);

                this.querySelectorAll('[data-tab]').forEach((b) => {
                    b.className = `button ${b.getAttribute('data-tab') === tab ? 'button--primary' : 'button--secondary'}`;
                });

                await this.loadTab(tab);
            });
        });
    }

    renderTabContent() {
        const root = this.querySelector('#tab-content-root');
        if (!root) return;

        if (this.tabLoading) {
            root.innerHTML = `
                <div style="padding: 60px 0; text-align: center; color: var(--text-secondary);">
                    <div class="skeleton" style="width: 80px; height: 16px; margin: 0 auto 12px; border-radius: 4px;"></div>
                    <div class="skeleton" style="width: 240px; height: 28px; margin: 0 auto 16px; border-radius: 6px;"></div>
                    <p class="pulse" style="font-size: 0.95rem; color: var(--text-dim);">Fetching live configuration and metrics from clinical endpoints…</p>
                </div>
            `;
            return;
        }

        if (this.tabError) {
            root.innerHTML = `
                <article class="glass-panel" style="padding: 32px; border-color: rgba(248, 113, 113, 0.28); margin-top: 16px;">
                    <h3 style="color: var(--danger); margin-top: 0;">Operational Console Unavailable</h3>
                    <p style="color: var(--text-secondary); margin-bottom: 20px;">${escapeHtml(this.tabError)}</p>
                    <button class="button button--secondary" id="tab-retry-btn">Retry Connection</button>
                </article>
            `;
            return;
        }

        if (this.activeTab === 'evaluations') {
            root.innerHTML = this.getEvaluationsTemplate();
        } else if (this.activeTab === 'ops') {
            root.innerHTML = this.getOpsTemplate();
        } else if (this.activeTab === 'admin') {
            root.innerHTML = this.getAdminTemplate();
        }
    }

    scoreTone(score) {
        if (score == null) return 'muted';
        if (score > 0.75) return 'success';
        if (score >= 0.5) return 'warning';
        return 'danger';
    }

    // ==========================================
    // EVALUATIONS TEMPLATES & CHARTS
    // ==========================================

    renderMetricCard(label, score, helper) {
        const tone = this.scoreTone(score);
        const percent = Math.max(0, Math.min(100, Math.round((score || 0) * 100)));
        return `
            <article class="glass-panel evaluation-card" style="padding: 20px;">
                <div class="evaluation-card__header">
                    <div class="eyebrow" style="font-size: 0.75rem;">${label}</div>
                    <span class="status-badge status-badge--${tone === 'success' ? 'ready' : tone === 'warning' ? 'processing' : tone === 'danger' ? 'error' : 'idle'}">
                        ${score == null ? 'No data' : `${percent}%`}
                    </span>
                </div>
                <div class="evaluation-card__score" style="font-size: 2.2rem; margin: 10px 0;">${score == null ? '---' : score.toFixed(3)}</div>
                <div class="evaluation-meter" style="margin-bottom: 12px;">
                    <div class="evaluation-meter__fill evaluation-meter__fill--${tone}" style="width:${percent}%"></div>
                </div>
                <p class="evaluation-card__helper" style="margin: 0; font-size: 0.85rem; line-height: 1.4;">${helper}</p>
            </article>
        `;
    }

    getEvaluationsTemplate() {
        if (!this.latest) {
            const adminAction = this.user?.role === 'admin'
                ? `<button type="button" class="button button--secondary" id="run-eval-btn">${this.isRunningEval ? 'Running…' : 'Run evaluation'}</button>`
                : '';
            return `
                <div style="text-align: center; padding: 48px 24px; border: 1px dashed var(--border-subtle); border-radius: 20px;">
                    <h3 style="margin-top: 0;">No Evaluation Reports Yet</h3>
                    <p style="color: var(--text-secondary); max-width: 500px; margin: 8px auto 20px;">
                        Run the clinical quality suite to generate safety profiles, citation accuracy indexes, and retrieval recall metrics.
                    </p>
                    <div style="display:flex; justify-content:center; gap:12px;">
                        <button type="button" class="button button--secondary" id="tab-refresh-btn">Refresh</button>
                        ${adminAction}
                    </div>
                </div>
            `;
        }

        const metrics = this.latest.metrics || {};
        const cases = this.latest.cases || [];
        const updatedAt = this.latest.timestamp ? new Date(this.latest.timestamp).toLocaleString() : 'Unknown';
        const adminAction = this.user?.role === 'admin'
            ? `<button type="button" class="button button--secondary" id="run-eval-btn" ${this.isRunningEval ? 'disabled' : ''}>${this.isRunningEval ? 'Running…' : 'Run evaluation'}</button>`
            : '';
        const baselineAction = this.user?.role === 'admin' && this.latest?.id
            ? `<button type="button" class="button button--secondary" id="bless-baseline-btn">Bless Baseline</button>`
            : '';

        return `
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px; flex-wrap: wrap; gap: 16px;">
                <div>
                    <h2 style="margin: 0; font-size: 1.4rem;">Performance Summary</h2>
                    <p style="margin: 4px 0 0; font-size: 0.88rem; color: var(--text-dim);">
                        Job ID: ${this.latest.job_id || 'n/a'} · Updated: ${updatedAt} · Cases: ${this.latest.dataset_size || cases.length}
                    </p>
                </div>
                <div style="display: flex; gap: 8px;">
                    <button type="button" class="button button--secondary" id="tab-refresh-btn" style="min-height: 38px;">Refresh</button>
                    ${baselineAction}
                    ${adminAction}
                </div>
            </div>

            <div class="document-list" style="display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 16px; margin-bottom: 24px;">
                ${this.renderMetricCard('Groundedness', metrics.answer_groundedness ?? metrics.faithfulness, 'Percentage of answer content directly grounded in source context.')}
                ${this.renderMetricCard('Citation Accuracy', metrics.citation_correctness ?? metrics.citation_accuracy, 'Percentage of citations referencing correct semantic target blocks.')}
                ${this.renderMetricCard('Retrieval Recall', metrics.retrieval_recall_proxy ?? metrics.context_recall, 'Semantic coverage of expected retrieval text vs. benchmark.')}
                ${this.renderMetricCard('Hallucination Index', metrics.hallucination_rate, 'Lower is better. Ratio of unsupported generated medical claims.')}
            </div>

            <div class="document-list" style="grid-template-columns: repeat(auto-fit, minmax(400px, 1fr)); gap: 20px; margin-bottom: 24px;">
                <article class="glass-panel" style="padding: 20px;">
                    <div class="evaluation-panel__header" style="margin-bottom: 16px;">
                        <div class="eyebrow">Metrics Progression</div>
                        <h3 style="margin: 4px 0 0; font-size: 1.15rem;">Benchmark Performance History</h3>
                    </div>
                    <div style="height:280px; position: relative;">
                        <canvas id="evaluationHistoryChart"></canvas>
                    </div>
                </article>

                <article class="glass-panel" style="padding: 20px;">
                    <div class="evaluation-panel__header" style="margin-bottom: 16px;">
                        <div class="eyebrow">Active Release Target</div>
                        <h3 style="margin: 4px 0 0; font-size: 1.15rem;">Blessed Baseline Configuration</h3>
                    </div>
                    ${this.baseline ? `
                        <div class="evaluation-summary-grid" style="display: grid; grid-template-columns: repeat(auto-fit, minmax(130px, 1fr)); gap: 12px; margin-bottom: 20px;">
                            <div class="evaluation-summary-tile" style="padding: 12px; background: rgba(255,255,255,0.02); border-radius: 12px;">
                                <span class="eyebrow" style="font-size: 0.7rem;">Baseline Run</span>
                                <strong style="display: block; font-size: 1.05rem; margin-top: 4px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">${this.baseline.id || 'baseline'}</strong>
                            </div>
                            <div class="evaluation-summary-tile" style="padding: 12px; background: rgba(255,255,255,0.02); border-radius: 12px;">
                                <span class="eyebrow" style="font-size: 0.7rem;">Total Samples</span>
                                <strong style="display: block; font-size: 1.05rem; margin-top: 4px;">${this.baseline.dataset_size || 0} cases</strong>
                            </div>
                            <div class="evaluation-summary-tile" style="padding: 12px; background: rgba(255,255,255,0.02); border-radius: 12px;">
                                <span class="eyebrow" style="font-size: 0.7rem;">Blessed Date</span>
                                <strong style="display: block; font-size: 1.05rem; margin-top: 4px;">${this.baseline.timestamp ? new Date(this.baseline.timestamp).toLocaleDateString() : 'Unknown'}</strong>
                            </div>
                        </div>
                        <p style="font-size: 0.88rem; color: var(--text-dim); margin: 0; line-height: 1.5;">
                            This baseline represents the verified clinical safety gate. Future evaluations are compared directly to this baseline to flag regressions.
                        </p>
                    ` : `
                        <div style="text-align: center; padding: 24px 12px; border: 1px dashed var(--border-subtle); border-radius: 14px;">
                            <p style="color: var(--text-secondary); margin: 0 0 12px;">No blessed baseline has been defined for this environment.</p>
                            <span style="font-size: 0.85rem; color: var(--text-muted);">Blessing a run marks it as the official comparison target.</span>
                        </div>
                    `}
                </article>
            </div>

            <article class="glass-panel" style="padding: 20px;">
                <div class="evaluation-panel__header" style="margin-bottom: 16px;">
                    <div class="eyebrow">Case Details</div>
                    <h3 style="margin: 4px 0 0; font-size: 1.15rem;">Individual Test Case Breakdown</h3>
                </div>
                ${cases.length ? this.renderCaseTable(cases) : '<p style="color: var(--text-dim); font-size: 0.9rem; padding: 12px 0;">No individual case results are recorded in the current run.</p>'}
            </article>
        `;
    }

    renderCaseTable(cases) {
        return `
            <div class="evaluation-table-wrap" style="overflow-x: auto;">
                <table class="evaluation-table" style="width: 100%; border-collapse: collapse; min-width: 800px;">
                    <thead>
                        <tr style="border-bottom: 1px solid var(--border-subtle);">
                            <th style="text-align: left; padding: 12px;">Question</th>
                            <th style="text-align: left; padding: 12px;">Expected Answer</th>
                            <th style="text-align: left; padding: 12px;">Generated Answer</th>
                            <th style="text-align: center; padding: 12px; width: 90px;">Grounded</th>
                            <th style="text-align: center; padding: 12px; width: 90px;">Citation</th>
                            <th style="text-align: center; padding: 12px; width: 90px;">Recall</th>
                            <th style="text-align: center; padding: 12px; width: 90px;">Halluc</th>
                            <th style="text-align: center; padding: 12px; width: 100px;">Verification</th>
                        </tr>
                    </thead>
                    <tbody>
                        ${cases.map((item) => `
                            <tr style="border-bottom: 1px solid rgba(255,255,255,0.03);">
                                <td style="padding: 12px; font-size: 0.88rem; vertical-align: top; max-width: 200px; white-space: normal; line-height: 1.4;">${escapeHtml(item.question || '—')}</td>
                                <td style="padding: 12px; font-size: 0.88rem; vertical-align: top; max-width: 220px; white-space: normal; line-height: 1.4; color: var(--text-dim);">${escapeHtml(item.ground_truth || '—')}</td>
                                <td style="padding: 12px; font-size: 0.88rem; vertical-align: top; max-width: 220px; white-space: normal; line-height: 1.4; color: var(--text-secondary);">${escapeHtml(item.answer || '—')}</td>
                                <td style="padding: 12px; text-align: center; vertical-align: top;">
                                    <span class="evaluation-chip evaluation-chip--${this.scoreTone(item.answer_groundedness ?? item.faithfulness)}">
                                        ${((item.answer_groundedness ?? item.faithfulness) ?? 0).toFixed(3)}
                                    </span>
                                </td>
                                <td style="padding: 12px; text-align: center; vertical-align: top;">
                                    <span class="evaluation-chip evaluation-chip--${this.scoreTone(item.citation_correctness ?? item.citation_accuracy)}">
                                        ${((item.citation_correctness ?? item.citation_accuracy) ?? 0).toFixed(3)}
                                    </span>
                                </td>
                                <td style="padding: 12px; text-align: center; vertical-align: top;">
                                    <span class="evaluation-chip evaluation-chip--${this.scoreTone(item.retrieval_recall_proxy ?? item.context_recall)}">
                                        ${((item.retrieval_recall_proxy ?? item.context_recall) ?? 0).toFixed(3)}
                                    </span>
                                </td>
                                <td style="padding: 12px; text-align: center; vertical-align: top;">
                                    <span class="evaluation-chip evaluation-chip--${this.scoreTone(1 - (item.hallucination_rate ?? 0))}">
                                        ${(item.hallucination_rate ?? 0).toFixed(3)}
                                    </span>
                                </td>
                                <td style="padding: 12px; text-align: center; vertical-align: top;">
                                    <button type="button" class="button button--ghost" style="min-height: 28px; padding: 0 10px; font-size: 0.78rem;" data-review-case="${escapeHtml(item.case_id || item.id || item.question)}">Accept</button>
                                </td>
                            </tr>
                        `).join('')}
                    </tbody>
                </table>
            </div>
        `;
    }

    renderCharts() {
        if (typeof Chart === 'undefined') return;
        this.destroyCharts();

        const canvas = this.querySelector('#evaluationHistoryChart');
        if (!canvas || !this.history.length) return;

        const history = [...this.history].reverse();
        const chart = new Chart(canvas, {
            type: 'line',
            data: {
                labels: history.map((entry) => new Date(entry.timestamp).toLocaleDateString()),
                datasets: [
                    { label: 'Groundedness', data: history.map((entry) => entry.metrics?.answer_groundedness ?? entry.metrics?.faithfulness ?? null), borderColor: '#2dd4bf', backgroundColor: 'rgba(45, 212, 191, 0.08)', tension: 0.32, fill: true },
                    { label: 'Citation Correctness', data: history.map((entry) => entry.metrics?.citation_correctness ?? entry.metrics?.citation_accuracy ?? null), borderColor: '#60a5fa', backgroundColor: 'rgba(96, 165, 250, 0.08)', tension: 0.32, fill: true },
                    { label: 'Retrieval Recall', data: history.map((entry) => entry.metrics?.retrieval_recall_proxy ?? entry.metrics?.context_recall ?? null), borderColor: '#fbbf24', backgroundColor: 'rgba(251, 191, 36, 0.08)', tension: 0.32, fill: true },
                    { label: 'Hallucinations', data: history.map((entry) => entry.metrics?.hallucination_rate ?? null), borderColor: '#f87171', backgroundColor: 'rgba(248, 113, 113, 0.08)', tension: 0.32, fill: true },
                ],
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                interaction: { mode: 'index', intersect: false },
                scales: {
                    y: {
                        min: 0,
                        max: 1,
                        ticks: { color: '#9ca3af' },
                        grid: { color: 'rgba(255,255,255,0.06)' },
                    },
                    x: {
                        ticks: { color: '#9ca3af' },
                        grid: { color: 'rgba(255,255,255,0.04)' },
                    },
                },
                plugins: {
                    legend: {
                        labels: { color: '#c8d1db', boxWidth: 12 },
                    },
                },
            },
        });
        this.charts.push(chart);
    }

    // ==========================================
    // FINE-TUNING & MODEL OPS TEMPLATES
    // ==========================================

    getOpsTemplate() {
        if (this.ftDisabledReason) {
            return `
                <div style="text-align: center; padding: 48px 24px; border: 1px dashed var(--border-subtle); border-radius: 20px;">
                    <div style="font-size: 2rem; margin-bottom: 12px;">⚠️</div>
                    <h3 style="margin-top: 0;">Fine-Tuning Feature Disabled</h3>
                    <p style="color: var(--text-secondary); max-width: 500px; margin: 8px auto 20px;">
                        ${escapeHtml(this.ftDisabledReason)}
                    </p>
                    <button class="button button--secondary" id="tab-refresh-btn">Retry Connection</button>
                </div>
            `;
        }

        return `
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px; flex-wrap: wrap; gap: 16px;">
                <div>
                    <h2 style="margin: 0; font-size: 1.4rem;">Model Fine-Tuning Registry</h2>
                    <p style="margin: 4px 0 0; font-size: 0.88rem; color: var(--text-dim);">
                        Launch new tuning runs, validate data shapes, and switch active model endpoints.
                    </p>
                </div>
                <button type="button" class="button button--secondary" id="tab-refresh-btn" style="min-height: 38px;">Refresh</button>
            </div>

            <div style="display: grid; grid-template-columns: 1fr; gap: 24px;">
                <!-- Datasets Section -->
                <section class="glass-panel ops-panel" style="padding: 20px;">
                    <div class="ops-panel__header" style="margin-bottom: 16px;">
                        <div class="eyebrow">Training Datasets</div>
                        <h3 style="margin: 4px 0 0; font-size: 1.15rem;">Manage Fine-Tuning Data</h3>
                    </div>
                    
                    <form id="create-dataset-form" class="ops-inline-form" style="display: flex; gap: 10px; margin-bottom: 20px; flex-wrap: wrap;">
                        <input id="dataset-name" class="field-input" placeholder="Dataset name" style="flex: 1; min-width: 150px; min-height: 38px;" required />
                        <input id="dataset-description" class="field-input" placeholder="Description" style="flex: 2; min-width: 250px; min-height: 38px;" />
                        <select id="dataset-template" class="field-input" style="width: 130px; min-height: 38px;">
                            <option value="alpaca">Alpaca</option>
                            <option value="chat">Chat</option>
                        </select>
                        <button class="button button--secondary" type="submit" style="min-height: 38px;">Create Dataset</button>
                    </form>

                    <div class="ops-list" style="display: flex; flex-direction: column; gap: 10px;">
                        ${this.datasets.map((dataset) => `
                            <article class="ops-list-row" style="display: flex; justify-content: space-between; align-items: center; padding: 12px 16px; background: rgba(255,255,255,0.02); border-radius: 14px; flex-wrap: wrap; gap: 12px;">
                                <div style="min-width: 250px;">
                                    <strong style="font-size: 0.95rem; color: var(--text-primary); display: block;">${escapeHtml(dataset.name || dataset.id)}</strong>
                                    <span style="font-size: 0.8rem; color: var(--text-muted); display: block; margin-top: 2px;">
                                        ${escapeHtml(String(dataset.sample_count || 0))} samples · Format: ${escapeHtml(dataset.template || 'template')} · Created: ${formatDate(dataset.created_at)}
                                    </span>
                                </div>
                                <div class="annotation-list__actions" style="display: flex; gap: 8px;">
                                    <button class="button button--secondary" style="min-height: 30px; padding: 0 12px; font-size: 0.8rem;" data-generate-dataset="${escapeHtml(dataset.id)}">Generate Samples</button>
                                    <button class="button button--secondary" style="min-height: 30px; padding: 0 12px; font-size: 0.8rem;" data-validate-dataset="${escapeHtml(dataset.id)}">Validate Shape</button>
                                    <button class="button button--ghost" style="min-height: 30px; padding: 0 12px; font-size: 0.8rem; border-color: rgba(248,113,113,0.2);" data-delete-dataset="${escapeHtml(dataset.id)}">Delete</button>
                                </div>
                            </article>
                        `).join('') || '<div class="empty-inline" style="padding: 16px; text-align: center; color: var(--text-muted);">No training datasets available.</div>'}
                    </div>

                    ${this.validationResult ? `
                        <div style="margin-top: 16px;">
                            <div class="eyebrow" style="margin-bottom: 6px;">Validation Results</div>
                            <pre class="ops-json" style="padding: 14px; background: #07090b; border-radius: 12px; font-size: 0.82rem; overflow: auto; border: 1px solid var(--border-subtle); color: #c8d1db; margin: 0;">${escapeHtml(JSON.stringify(this.validationResult, null, 2))}</pre>
                        </div>
                    ` : ''}
                </section>

                <!-- Training Jobs Section -->
                <section class="glass-panel ops-panel" style="padding: 20px;">
                    <div class="ops-panel__header" style="margin-bottom: 16px;">
                        <div class="eyebrow">Training Executions</div>
                        <h3 style="margin: 4px 0 0; font-size: 1.15rem;">Run and Monitor Fine-Tuning</h3>
                    </div>

                    <form id="start-training-form" class="ops-inline-form" style="display: flex; gap: 10px; margin-bottom: 20px; flex-wrap: wrap;">
                        <select id="training-dataset" class="field-input" style="flex: 1; min-width: 150px; min-height: 38px;" required>
                            <option value="">Select dataset…</option>
                            ${this.datasets.map((dataset) => `<option value="${escapeHtml(dataset.id)}">${escapeHtml(dataset.name || dataset.id)}</option>`).join('')}
                        </select>
                        <input id="training-adapter" class="field-input" placeholder="Adapter key (e.g. soap-gpt4)" style="flex: 1; min-width: 150px; min-height: 38px;" required />
                        <input id="training-base-model" class="field-input" placeholder="Base model key (optional)" style="flex: 1; min-width: 150px; min-height: 38px;" />
                        <button class="button button--primary" type="submit" style="min-height: 38px;">Start Training Run</button>
                    </form>

                    <div class="ops-list" style="display: flex; flex-direction: column; gap: 10px;">
                        ${this.jobs.map((job) => `
                            <article class="ops-list-row" style="display: flex; justify-content: space-between; align-items: center; padding: 12px 16px; background: rgba(255,255,255,0.02); border-radius: 14px; flex-wrap: wrap; gap: 12px;">
                                <div>
                                    <strong style="font-size: 0.95rem; color: var(--text-primary); display: block;">${escapeHtml(job.adapter_name || job.id)}</strong>
                                    <span style="font-size: 0.8rem; color: var(--text-muted); display: block; margin-top: 2px;">
                                        Status: <span style="color: ${String(job.status || '').toLowerCase() === 'completed' ? 'var(--success)' : String(job.status || '').toLowerCase() === 'failed' ? 'var(--danger)' : 'var(--warning)'}; font-weight: 600;">${escapeHtml(job.status || 'unknown')}</span> · 
                                        Loss: ${escapeHtml(job.final_loss ?? 'n/a')} · Created: ${formatDate(job.started_at)}
                                    </span>
                                </div>
                                <button class="button button--ghost" style="min-height: 30px; padding: 0 12px; font-size: 0.8rem; border-color: rgba(248,113,113,0.2);" data-cancel-job="${escapeHtml(job.id)}" ${['completed', 'failed', 'cancelled'].includes(String(job.status || '').toLowerCase()) ? 'disabled' : ''}>Cancel Run</button>
                            </article>
                        `).join('') || '<div class="empty-inline" style="padding: 16px; text-align: center; color: var(--text-muted);">No training runs found.</div>'}
                    </div>
                </section>

                <!-- Model Registry Section -->
                <section class="glass-panel ops-panel" style="padding: 20px;">
                    <div class="ops-panel__header" style="margin-bottom: 16px;">
                        <div class="eyebrow">Model Registry</div>
                        <h3 style="margin: 4px 0 0; font-size: 1.15rem;">Registered Adapters and Deployments</h3>
                    </div>

                    <form id="register-model-form" class="ops-inline-form" style="display: flex; gap: 10px; margin-bottom: 20px; flex-wrap: wrap;">
                        <input id="model-name" class="field-input" placeholder="Model key/name" style="flex: 1; min-width: 150px; min-height: 38px;" required />
                        <input id="model-base" class="field-input" placeholder="Base model key" style="flex: 1; min-width: 150px; min-height: 38px;" required />
                        <input id="model-dataset" class="field-input" placeholder="Origin dataset name" style="flex: 1; min-width: 150px; min-height: 38px;" />
                        <button class="button button--secondary" type="submit" style="min-height: 38px;">Register Adapter</button>
                    </form>

                    <div class="ops-table-wrap" style="overflow-x: auto;">
                        <table class="evaluation-table" style="width: 100%; border-collapse: collapse; min-width: 600px;">
                            <thead>
                                <tr style="border-bottom: 1px solid var(--border-subtle);">
                                    <th style="text-align: left; padding: 12px;">Model Name</th>
                                    <th style="text-align: left; padding: 12px;">Base Reference</th>
                                    <th style="text-align: center; padding: 12px; width: 90px;">Version</th>
                                    <th style="text-align: center; padding: 12px; width: 110px;">Status</th>
                                    <th style="text-align: right; padding: 12px;">Actions</th>
                                </tr>
                            </thead>
                            <tbody>
                                ${this.models.map((model) => `
                                    <tr style="border-bottom: 1px solid rgba(255,255,255,0.03);">
                                        <td style="padding: 12px; font-weight: 600; font-size: 0.9rem;">${escapeHtml(model.name || model.id)}</td>
                                        <td style="padding: 12px; font-size: 0.88rem; color: var(--text-dim);">${escapeHtml(model.base_model || '-')}</td>
                                        <td style="padding: 12px; text-align: center; font-size: 0.88rem;">${escapeHtml(model.version || '-')}</td>
                                        <td style="padding: 12px; text-align: center;">
                                            <span class="status-badge status-badge--${model.deployed || String(model.status || '').toLowerCase() === 'deployed' ? 'ready' : 'idle'}">
                                                ${escapeHtml(model.status || (model.deployed ? 'deployed' : 'registered'))}
                                            </span>
                                        </td>
                                        <td style="padding: 12px; text-align: right;">
                                            <div style="display: inline-flex; gap: 6px;">
                                                <button class="button button--secondary" style="min-height: 28px; padding: 0 10px; font-size: 0.78rem;" data-deploy-model="${escapeHtml(model.id)}">Deploy</button>
                                                <button class="button button--ghost" style="min-height: 28px; padding: 0 10px; font-size: 0.78rem;" data-undeploy-model="${escapeHtml(model.id)}">Undeploy</button>
                                                <button class="button button--ghost" style="min-height: 28px; padding: 0 10px; font-size: 0.78rem; border-color: rgba(248,113,113,0.2);" data-delete-model="${escapeHtml(model.id)}">Delete</button>
                                            </div>
                                        </td>
                                    </tr>
                                `).join('') || '<tr><td colspan="5" style="padding: 16px; text-align: center; color: var(--text-muted);">No registered adapters in catalog.</td></tr>'}
                            </tbody>
                        </table>
                    </div>
                </section>
            </div>
        `;
    }

    // ==========================================
    // ADMIN SETTINGS & AUDITING TEMPLATES
    // ==========================================

    getAdminTemplate() {
        return `
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px; flex-wrap: wrap; gap: 16px;">
                <div>
                    <h2 style="margin: 0; font-size: 1.4rem;">System Governance and Logging</h2>
                    <p style="margin: 4px 0 0; font-size: 0.88rem; color: var(--text-dim);">
                        Audit clinical access, export health markers, and execute compliance data purging actions.
                    </p>
                </div>
                <button type="button" class="button button--secondary" id="tab-refresh-btn" style="min-height: 38px;">Refresh</button>
            </div>

            <!-- Health Status Section -->
            <section class="glass-panel ops-panel" style="padding: 20px; margin-bottom: 24px;">
                <div class="ops-panel__header" style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px; flex-wrap: wrap; gap: 12px;">
                    <div>
                        <div class="eyebrow">Runtime Metrics</div>
                        <h3 style="margin: 4px 0 0; font-size: 1.15rem;">Runtime Vector Indexes & API Metrics</h3>
                    </div>
                    <span class="status-badge status-badge--${this.health?.status === 'healthy' ? 'ready' : 'processing'}">
                        System Uptime: ${escapeHtml(this.health?.uptime_human || 'Active')}
                    </span>
                </div>
                
                <div class="ops-metric-grid" style="display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: 16px; margin-bottom: 20px;">
                    <article class="ops-metric-card" style="padding: 16px; background: rgba(255,255,255,0.02); border-radius: 16px; border: 1px solid var(--border-subtle);">
                        <span class="eyebrow" style="font-size: 0.72rem; display: block; margin-bottom: 6px;">Total Index Chunks</span>
                        <strong style="font-size: 1.6rem; color: var(--text-primary);">${escapeHtml(String(this.health?.services?.vector_store?.total_chunks ?? 0))}</strong>
                    </article>
                    <article class="ops-metric-card" style="padding: 16px; background: rgba(255,255,255,0.02); border-radius: 16px; border: 1px solid var(--border-subtle);">
                        <span class="eyebrow" style="font-size: 0.72rem; display: block; margin-bottom: 6px;">Active Documents</span>
                        <strong style="font-size: 1.6rem; color: var(--text-primary);">${escapeHtml(String(this.health?.services?.vector_store?.total_documents ?? 0))}</strong>
                    </article>
                    <article class="ops-metric-card" style="padding: 16px; background: rgba(255,255,255,0.02); border-radius: 16px; border: 1px solid var(--border-subtle);">
                        <span class="eyebrow" style="font-size: 0.72rem; display: block; margin-bottom: 6px;">API Server Request Volume</span>
                        <strong style="font-size: 1.6rem; color: var(--text-primary);">${escapeHtml(String(this.metrics?.total_requests ?? 0))} reqs</strong>
                    </article>
                    <article class="ops-metric-card" style="padding: 16px; background: rgba(255,255,255,0.02); border-radius: 16px; border: 1px solid var(--border-subtle);">
                        <span class="eyebrow" style="font-size: 0.72rem; display: block; margin-bottom: 6px;">Graph Nodes / Edges</span>
                        <strong style="font-size: 1.4rem; color: var(--text-primary); overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">
                            ${escapeHtml(String(this.health?.services?.knowledge_graph?.nodes_count ?? 0))} n / ${escapeHtml(String(this.health?.services?.knowledge_graph?.edges_count ?? 0))} e
                        </strong>
                    </article>
                </div>

                <div style="border-top: 1px solid var(--border-subtle); padding-top: 16px;">
                    <div class="eyebrow" style="margin-bottom: 10px;">Subsystem Health Status</div>
                    <div style="display: flex; flex-direction: column; gap: 8px;">
                        ${Object.entries(this.health?.services || {}).map(([name, payload]) => `
                            <div style="display: flex; justify-content: space-between; align-items: center; padding: 8px 12px; background: rgba(255,255,255,0.01); border-radius: 10px; border: 1px solid rgba(255,255,255,0.02);">
                                <span style="font-size: 0.85rem; font-family: var(--font-mono); color: var(--text-secondary); text-transform: uppercase;">${escapeHtml(name.replaceAll('_', ' '))}</span>
                                <span class="status-chip" style="font-size: 0.78rem; padding: 2px 8px; border-radius: 6px; background: ${payload?.status === 'healthy' || payload?.status === 'up' ? 'var(--success-soft)' : 'var(--danger-soft)'}; color: ${payload?.status === 'healthy' || payload?.status === 'up' ? 'var(--success)' : 'var(--danger)'};">
                                    ${escapeHtml(payload?.status || 'Active')}
                                </span>
                            </div>
                        `).join('') || '<div style="color: var(--text-muted); font-size: 0.85rem;">No service telemetry available.</div>'}
                    </div>
                </div>
            </section>

            <!-- Configuration Options Section -->
            ${this.config ? `
                <section class="glass-panel ops-panel" style="padding: 20px; margin-bottom: 24px;">
                    <div class="ops-panel__header" style="margin-bottom: 16px;">
                        <div class="eyebrow">Settings Configuration</div>
                        <h3 style="margin: 4px 0 0; font-size: 1.15rem;">Active Retrieval & Clinical Model Configurations</h3>
                    </div>
                    <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 16px;">
                        <article style="padding: 12px; background: rgba(255,255,255,0.01); border-radius: 12px; border: 1px solid var(--border-subtle);">
                            <span class="eyebrow" style="font-size: 0.7rem; display: block;">Primary LLM Config</span>
                            <strong style="font-size: 0.92rem; display: block; margin-top: 4px; color: var(--text-primary);">${escapeHtml(this.config.llm ? `${this.config.llm.provider} / ${this.config.llm.model}` : 'Not Available')}</strong>
                        </article>
                        <article style="padding: 12px; background: rgba(255,255,255,0.01); border-radius: 12px; border: 1px solid var(--border-subtle);">
                            <span class="eyebrow" style="font-size: 0.7rem; display: block;">Vector Embeddings</span>
                            <strong style="font-size: 0.92rem; display: block; margin-top: 4px; color: var(--text-primary);">${escapeHtml(this.config.embedding ? `${this.config.embedding.model} (${this.config.embedding.dimension}d)` : 'Not Available')}</strong>
                        </article>
                        <article style="padding: 12px; background: rgba(255,255,255,0.01); border-radius: 12px; border: 1px solid var(--border-subtle);">
                            <span class="eyebrow" style="font-size: 0.7rem; display: block;">Search Mode</span>
                            <strong style="font-size: 0.92rem; display: block; margin-top: 4px; color: var(--text-primary);">${this.config.rag?.use_hybrid_search ? '🔍 Hybrid (Semantic + Keyword)' : '🔍 Classic Semantic'}</strong>
                        </article>
                        <article style="padding: 12px; background: rgba(255,255,255,0.01); border-radius: 12px; border: 1px solid var(--border-subtle);">
                            <span class="eyebrow" style="font-size: 0.7rem; display: block;">Reranking Pipeline</span>
                            <strong style="font-size: 0.92rem; display: block; margin-top: 4px; color: var(--text-primary);">${this.config.rag?.use_reranking ? '✅ Cohere Rerank Activated' : '❌ Reranking Bypassed'}</strong>
                        </article>
                    </div>
                </section>
            ` : ''}

            <!-- Access Management (Users) Section -->
            <section class="glass-panel ops-panel" style="padding: 20px; margin-bottom: 24px;">
                <div class="ops-panel__header" style="margin-bottom: 16px;">
                    <div class="eyebrow">Credential Controls</div>
                    <h3 style="margin: 4px 0 0; font-size: 1.15rem;">Access Control List & GDPR Portability</h3>
                </div>

                <form id="admin-create-user-form" class="ops-inline-form" style="display: flex; gap: 10px; margin-bottom: 20px; flex-wrap: wrap;">
                    <input class="field-input" id="admin-user-email" type="email" placeholder="clinical.staff@hospital.org" style="flex: 2; min-width: 200px; min-height: 38px;" required />
                    <input class="field-input" id="admin-user-name" placeholder="Staff member's full name" style="flex: 2; min-width: 200px; min-height: 38px;" required />
                    <select class="field-input" id="admin-user-role" style="flex: 1; min-width: 120px; min-height: 38px;">
                        <option value="viewer">Viewer (Read-only)</option>
                        <option value="physician">Physician (Draft SOAP)</option>
                        <option value="admin">Administrator</option>
                    </select>
                    <button class="button button--secondary" type="submit" style="min-height: 38px;">Provision Account</button>
                </form>

                <div class="ops-table-wrap" style="overflow-x: auto;">
                    <table class="evaluation-table" style="width: 100%; border-collapse: collapse; min-width: 600px;">
                        <thead>
                            <tr style="border-bottom: 1px solid var(--border-subtle);">
                                <th style="text-align: left; padding: 12px;">Full Name</th>
                                <th style="text-align: left; padding: 12px;">Email Address</th>
                                <th style="text-align: center; padding: 12px; width: 110px;">Role</th>
                                <th style="text-align: center; padding: 12px; width: 110px;">Account Status</th>
                                <th style="text-align: right; padding: 12px; width: 180px;">Compliance Actions</th>
                            </tr>
                        </thead>
                        <tbody>
                            ${this.users.map((user) => `
                                <tr style="border-bottom: 1px solid rgba(255,255,255,0.03);">
                                    <td style="padding: 12px; font-weight: 500; font-size: 0.9rem;">${escapeHtml(user.name || '-')}</td>
                                    <td style="padding: 12px; font-size: 0.88rem; color: var(--text-dim);">${escapeHtml(user.email || '-')}</td>
                                    <td style="padding: 12px; text-align: center; font-size: 0.88rem; text-transform: capitalize;">${escapeHtml(user.role || '-')}</td>
                                    <td style="padding: 12px; text-align: center;">
                                        <span class="status-badge status-badge--${user.is_active === false ? 'error' : 'ready'}">
                                            ${user.is_active === false ? 'Deactivated' : 'Active'}
                                        </span>
                                    </td>
                                    <td style="padding: 12px; text-align: right;">
                                        <div style="display: inline-flex; gap: 6px;">
                                            <button class="button button--ghost" style="min-height: 28px; padding: 0 10px; font-size: 0.78rem;" data-export-user="${escapeHtml(user.id)}">Export JSON</button>
                                            <button class="button button--ghost" style="min-height: 28px; padding: 0 10px; font-size: 0.78rem; border-color: rgba(248,113,113,0.2);" data-purge-user="${escapeHtml(user.id)}">Purge Data</button>
                                        </div>
                                    </td>
                                </tr>
                            `).join('') || '<tr><td colspan="5" style="padding: 16px; text-align: center; color: var(--text-muted);">No users in list.</td></tr>'}
                        </tbody>
                    </table>
                </div>
            </section>

            <!-- Export Results Preview Box -->
            ${this.exportResult ? `
                <section class="glass-panel ops-panel" style="padding: 20px; margin-bottom: 24px;">
                    <div class="ops-panel__header" style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px;">
                        <div>
                            <div class="eyebrow">GDPR Export Payload</div>
                            <h3 style="margin: 4px 0 0; font-size: 1.15rem;">Exported User Attributes & Session Contexts</h3>
                        </div>
                        <button class="button button--ghost" style="min-height: 28px; padding: 0 12px; font-size: 0.78rem;" id="clear-export-btn">Clear Export Cache</button>
                    </div>
                    <pre class="ops-json" style="padding: 14px; background: #07090b; border-radius: 12px; font-size: 0.82rem; overflow: auto; border: 1px solid var(--border-subtle); color: #c8d1db; margin: 0; max-height: 250px;">${escapeHtml(JSON.stringify(this.exportResult, null, 2))}</pre>
                </section>
            ` : ''}

            <!-- Sessions and Audit Logs Grid -->
            <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(360px, 1fr)); gap: 20px;">
                <section class="glass-panel ops-panel" style="padding: 20px;">
                    <div class="ops-panel__header" style="margin-bottom: 16px;">
                        <div class="eyebrow">Active Connections</div>
                        <h3 style="margin: 4px 0 0; font-size: 1.15rem;">Active Login Sessions</h3>
                    </div>
                    <div class="ops-list" style="display: flex; flex-direction: column; gap: 8px;">
                        ${this.sessions.slice(0, 8).map((session) => `
                            <article class="ops-list-row" style="display: flex; justify-content: space-between; align-items: center; padding: 10px 14px; background: rgba(255,255,255,0.01); border-radius: 12px; border: 1px solid rgba(255,255,255,0.02);">
                                <div>
                                    <strong style="font-size: 0.88rem; color: var(--text-primary); display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; max-width: 220px;">${escapeHtml(session.email || session.user_id || session.id)}</strong>
                                    <span style="font-size: 0.76rem; color: var(--text-muted); display: block; margin-top: 2px;">Last Seen: ${formatDate(session.created_at || session.last_seen_at)}</span>
                                </div>
                                <button class="button button--ghost" style="min-height: 28px; padding: 0 10px; font-size: 0.76rem; border-color: rgba(248,113,113,0.2);" data-revoke-session="${escapeHtml(session.id || session.session_id)}">Revoke</button>
                            </article>
                        `).join('') || '<div style="padding: 12px; color: var(--text-muted); font-size: 0.85rem; text-align: center;">No active web sessions detected.</div>'}
                    </div>
                </section>

                <section class="glass-panel ops-panel" style="padding: 20px;">
                    <div class="ops-panel__header" style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px; flex-wrap: wrap; gap: 8px;">
                        <div>
                            <div class="eyebrow">Audit Trails</div>
                            <h3 style="margin: 4px 0 0; font-size: 1.15rem;">Recent Security Activities</h3>
                        </div>
                        <span class="filter-pill" style="padding: 2px 8px; border-radius: 6px; font-size: 0.72rem;">${escapeHtml(String(this.audit.total || 0))} logs stored</span>
                    </div>
                    <div class="ops-list" style="display: flex; flex-direction: column; gap: 8px;">
                        ${(this.audit.items || []).slice(0, 8).map((item) => `
                            <article class="ops-list-row" style="padding: 10px 14px; background: rgba(255,255,255,0.01); border-radius: 12px; border: 1px solid rgba(255,255,255,0.02);">
                                <strong style="font-size: 0.88rem; color: var(--text-primary); display: block; text-transform: uppercase; font-family: var(--font-mono); letter-spacing: 0.02em;">${escapeHtml(item.action || 'event')}</strong>
                                <span style="font-size: 0.76rem; color: var(--text-muted); display: block; margin-top: 2px;">
                                    Type: ${escapeHtml(item.resource_type || 'resource')} · Timestamp: ${formatDate(item.timestamp)}
                                </span>
                            </article>
                        `).join('') || '<div style="padding: 12px; color: var(--text-muted); font-size: 0.85rem; text-align: center;">Audit logs empty.</div>'}
                    </div>
                </section>
            </div>
        `;
    }

    // ==========================================
    // EVENTS BINDING
    // ==========================================

    bindEvents() {
        // Retry/Refresh Buttons
        this.querySelector('#tab-retry-btn')?.addEventListener('click', () => this.loadTab(this.activeTab));
        this.querySelector('#tab-refresh-btn')?.addEventListener('click', () => this.loadTab(this.activeTab));

        // 1. Evaluations Tab Actions
        this.querySelector('#run-eval-btn')?.addEventListener('click', () => this.handleRunEvaluation());
        this.querySelector('#bless-baseline-btn')?.addEventListener('click', () => this.handleBlessBaseline());
        this.querySelectorAll('[data-review-case]').forEach((btn) => {
            btn.addEventListener('click', () => this.handleReviewCase(btn.getAttribute('data-review-case') || ''));
        });

        // 2. Fine-Tuning Tab Actions
        this.querySelector('#create-dataset-form')?.addEventListener('submit', (e) => this.handleCreateDataset(e));
        this.querySelector('#start-training-form')?.addEventListener('submit', (e) => this.handleStartTraining(e));
        this.querySelector('#register-model-form')?.addEventListener('submit', (e) => this.handleRegisterModel(e));
        
        this.querySelectorAll('[data-generate-dataset]').forEach((btn) => {
            btn.addEventListener('click', () => this.handleGenerateSamples(btn.getAttribute('data-generate-dataset')));
        });
        this.querySelectorAll('[data-validate-dataset]').forEach((btn) => {
            btn.addEventListener('click', () => this.handleValidateDataset(btn.getAttribute('data-validate-dataset')));
        });
        this.querySelectorAll('[data-delete-dataset]').forEach((btn) => {
            btn.addEventListener('click', () => this.handleDeleteDataset(btn.getAttribute('data-delete-dataset')));
        });
        this.querySelectorAll('[data-cancel-job]').forEach((btn) => {
            btn.addEventListener('click', () => this.handleCancelJob(btn.getAttribute('data-cancel-job')));
        });
        this.querySelectorAll('[data-deploy-model]').forEach((btn) => {
            btn.addEventListener('click', () => this.handleDeployModel(btn.getAttribute('data-deploy-model')));
        });
        this.querySelectorAll('[data-undeploy-model]').forEach((btn) => {
            btn.addEventListener('click', () => this.handleUndeployModel(btn.getAttribute('data-undeploy-model')));
        });
        this.querySelectorAll('[data-delete-model]').forEach((btn) => {
            btn.addEventListener('click', () => this.handleDeleteModel(btn.getAttribute('data-delete-model')));
        });

        // 3. Admin Settings Tab Actions
        this.querySelector('#admin-create-user-form')?.addEventListener('submit', (e) => this.handleCreateUser(e));
        this.querySelector('#clear-export-btn')?.addEventListener('click', () => {
            this.exportResult = null;
            this.renderTabContent();
            this.bindEvents();
        });
        this.querySelectorAll('[data-revoke-session]').forEach((btn) => {
            btn.addEventListener('click', () => this.handleRevokeSession(btn.getAttribute('data-revoke-session')));
        });
        this.querySelectorAll('[data-export-user]').forEach((btn) => {
            btn.addEventListener('click', () => this.handleExportUser(btn.getAttribute('data-export-user')));
        });
        this.querySelectorAll('[data-purge-user]').forEach((btn) => {
            btn.addEventListener('click', () => this.handlePurgeUser(btn.getAttribute('data-purge-user')));
        });
    }

    // ==========================================
    // EVENT HANDLERS
    // ==========================================

    // Evaluations Handlers
    async handleRunEvaluation() {
        if (this.isRunningEval) return;
        this.isRunningEval = true;
        this.renderTabContent();
        try {
            const previousTimestamp = this.latest?.timestamp || null;
            const result = await apiFetch('/evaluations/run', { method: 'POST' });
            showToast(`Evaluation suite launched (${result.job_id}).`, 'success');
            await this.pollForFreshReport(previousTimestamp);
        } catch (error) {
            showToast(error.message || 'Unable to launch evaluation.', 'error');
        } finally {
            this.isRunningEval = false;
            await this.loadTab('evaluations');
        }
    }

    async pollForFreshReport(previousTimestamp) {
        for (let attempt = 0; attempt < 10; attempt += 1) {
            await new Promise((resolve) => window.setTimeout(resolve, 3000));
            const latest = await apiFetch('/evaluations/latest', { silent: true, skipRedirect: true }).catch(() => null);
            if (!latest) continue;
            if (!previousTimestamp || latest.timestamp !== previousTimestamp) {
                this.latest = latest;
                const metrics = await apiFetch('/evaluations/metrics', { silent: true, skipRedirect: true }).catch(() => ({ data: [] }));
                this.history = metrics?.data || [];
                showToast('Evaluation report compiled.', 'success');
                return;
            }
        }
        showToast('Evaluation is processing in background. Refresh in a minute.', 'info');
    }

    async handleBlessBaseline() {
        if (!this.latest?.id) return;
        try {
            this.baseline = await blessEvaluationBaseline(this.latest.id, 'Blessed baseline from unified admin console');
            showToast('Selected run blessed as core safety baseline.', 'success');
            await this.loadTab('evaluations');
        } catch (error) {
            showToast(error.message || 'Unable to bless baseline.', 'error');
        }
    }

    async handleReviewCase(caseId) {
        if (!this.latest?.id || !caseId) return;
        try {
            this.latest = await reviewEvaluationCase(this.latest.id, {
                case_id: caseId,
                accepted: true,
                tags: ['admin-approved'],
                notes: 'Accepted via operational console.',
            });
            showToast('Evaluation test case marked approved.', 'success');
            await this.loadTab('evaluations');
        } catch (error) {
            showToast(error.message || 'Unable to accept case.', 'error');
        }
    }

    // Fine-Tuning Handlers
    async handleCreateDataset(e) {
        e.preventDefault();
        const name = this.querySelector('#dataset-name')?.value.trim();
        const description = this.querySelector('#dataset-description')?.value.trim() || '';
        const template = this.querySelector('#dataset-template')?.value || 'alpaca';
        if (!name) return;

        try {
            await createFineTuneDataset({ name, description, template });
            showToast('Fine-tuning dataset created successfully.', 'success');
            await this.loadTab('ops');
        } catch (error) {
            showToast(error.message || 'Unable to create dataset.', 'error');
        }
    }

    async handleStartTraining(e) {
        e.preventDefault();
        const datasetId = this.querySelector('#training-dataset')?.value;
        const adapterName = this.querySelector('#training-adapter')?.value.trim();
        const baseModel = this.querySelector('#training-base-model')?.value.trim() || '';
        if (!datasetId || !adapterName) return;

        try {
            await startFineTuneTraining({ dataset_id: datasetId, adapter_name: adapterName, base_model: baseModel });
            showToast('Tuning task submitted to backend training scheduler.', 'success');
            await this.loadTab('ops');
        } catch (error) {
            showToast(error.message || 'Unable to queue training run.', 'error');
        }
    }

    async handleRegisterModel(e) {
        e.preventDefault();
        const name = this.querySelector('#model-name')?.value.trim();
        const baseModel = this.querySelector('#model-base')?.value.trim();
        const datasetName = this.querySelector('#model-dataset')?.value.trim() || '';
        if (!name || !baseModel) return;

        try {
            await registerFineTuneModel({ name, base_model: baseModel, dataset_name: datasetName });
            showToast('Fine-tuned adapter registered in catalog.', 'success');
            await this.loadTab('ops');
        } catch (error) {
            showToast(error.message || 'Unable to register model adapter.', 'error');
        }
    }

    async handleGenerateSamples(datasetId) {
        if (!datasetId) return;
        try {
            const result = await generateFineTuneSamples(datasetId, 20);
            showToast(`Generated ${result.generated || 0} synthetic tuning samples.`, 'success');
            await this.loadTab('ops');
        } catch (error) {
            showToast(error.message || 'Unable to generate samples.', 'error');
        }
    }

    async handleValidateDataset(datasetId) {
        if (!datasetId) return;
        try {
            this.validationResult = await validateFineTuneDataset(datasetId);
            showToast('Format validation scan completed.', 'success');
            this.renderTabContent();
            this.bindEvents();
        } catch (error) {
            showToast(error.message || 'Unable to validate training dataset.', 'error');
        }
    }

    async handleDeleteDataset(datasetId) {
        if (!datasetId) return;
        const confirmed = await modal.confirm('Are you sure you want to permanently delete this training dataset?', {
            title: 'Delete Training Dataset',
            confirmLabel: 'Confirm Delete',
            destructive: true,
        });
        if (!confirmed) return;

        try {
            await deleteFineTuneDataset(datasetId);
            showToast('Dataset index destroyed.', 'success');
            if (this.validationResult) this.validationResult = null;
            await this.loadTab('ops');
        } catch (error) {
            showToast(error.message || 'Unable to delete dataset.', 'error');
        }
    }

    async handleCancelJob(jobId) {
        if (!jobId) return;
        try {
            await cancelFineTuneJob(jobId);
            showToast('Tuning job execution termination request sent.', 'success');
            await this.loadTab('ops');
        } catch (error) {
            showToast(error.message || 'Unable to abort training run.', 'error');
        }
    }

    async handleDeployModel(modelId) {
        if (!modelId) return;
        try {
            await deployFineTuneModel(modelId);
            showToast('Switching default inference endpoints to selected adapter.', 'success');
            await this.loadTab('ops');
        } catch (error) {
            showToast(error.message || 'Unable to deploy adapter.', 'error');
        }
    }

    async handleUndeployModel(modelId) {
        if (!modelId) return;
        try {
            await undeployFineTuneModel(modelId);
            showToast('Adapter unlinked from active routing. Falling back to default baseline.', 'success');
            await this.loadTab('ops');
        } catch (error) {
            showToast(error.message || 'Unable to undeploy adapter.', 'error');
        }
    }

    async handleDeleteModel(modelId) {
        if (!modelId) return;
        const confirmed = await modal.confirm('Are you sure you want to delete this adapter registration? The file artifacts remain but the routing name will be cleared.', {
            title: 'Delete Adapter Registration',
            confirmLabel: 'Confirm Delete',
            destructive: true,
        });
        if (!confirmed) return;

        try {
            await deleteFineTuneModel(modelId);
            showToast('Adapter entry deleted from registry.', 'success');
            await this.loadTab('ops');
        } catch (error) {
            showToast(error.message || 'Unable to delete adapter record.', 'error');
        }
    }

    // Admin Settings Handlers
    async handleCreateUser(e) {
        e.preventDefault();
        const email = this.querySelector('#admin-user-email')?.value.trim();
        const name = this.querySelector('#admin-user-name')?.value.trim();
        const role = this.querySelector('#admin-user-role')?.value || 'viewer';
        if (!email || !name) return;

        try {
            const response = await createAdminUser({ email, name, role, is_active: true });
            const password = response.generated_password ? ` Temp Password: ${response.generated_password}` : '';
            showToast(`User account generated successfully.${password}`, 'success', 6000);
            await this.loadTab('admin');
        } catch (error) {
            showToast(error.message || 'Unable to provision user.', 'error');
        }
    }

    async handleRevokeSession(sessionId) {
        if (!sessionId) return;
        try {
            await revokeAdminSession(sessionId);
            showToast('Web socket and browser tokens revoked.', 'success');
            await this.loadTab('admin');
        } catch (error) {
            showToast(error.message || 'Unable to revoke connection.', 'error');
        }
    }

    async handleExportUser(userId) {
        if (!userId) return;
        try {
            this.exportResult = await exportUserData(userId);
            showToast('User portability export completed.', 'success');
            this.renderTabContent();
            this.bindEvents();
        } catch (error) {
            showToast(error.message || 'Unable to compile export data.', 'error');
        }
    }

    async handlePurgeUser(userId) {
        if (!userId) return;
        const confirmed = await modal.confirm('PERMANENT COMPLIANCE PURGE: Are you sure you want to permanently erase this user account, and overwrite all their session trails?', {
            title: 'Compliance Data Purge',
            confirmLabel: 'Confirm Purge',
            destructive: true,
        });
        if (!confirmed) return;

        try {
            await purgeUserData(userId);
            showToast('Compliance purge execution succeeded. User records zeroed.', 'success');
            await this.loadTab('admin');
        } catch (error) {
            showToast(error.message || 'Unable to purge user files.', 'error');
        }
    }
}

customElements.define('quality-admin', QualityAdmin);
