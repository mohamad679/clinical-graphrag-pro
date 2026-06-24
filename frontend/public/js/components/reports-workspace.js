import {
    getChatSession,
    getDetailedHealth,
    listAdminUsers,
    listAuditLog,
    listChatSessions,
    listDocuments,
    listImages,
    showToast,
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

function formatDate(value) {
    if (!value) return 'Not available';
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return String(value);
    return date.toLocaleString();
}

function formatBytes(bytes = 0) {
    const value = Number(bytes);
    if (!Number.isFinite(value) || value <= 0) return '0 B';
    if (value < 1024) return `${value} B`;
    if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`;
    return `${(value / (1024 * 1024)).toFixed(1)} MB`;
}

function markdownEscape(value = '') {
    return String(value || '').replace(/\r\n/g, '\n').trim();
}

function getSessionTitle(session) {
    return session?.title || session?.name || 'Untitled case session';
}

function sourceLabel(source = {}, index = 0) {
    return source.document_name || source.filename || `Evidence ${index + 1}`;
}

class ReportsWorkspace extends HTMLElement {
    constructor() {
        super();
        this.loading = true;
        this.reportType = 'case';
        this.reportTitle = 'Clinical Case Report';
        this.clinicianNote = '';
        this.selectedSessionId = '';
        this.selectedImageId = '';
        this.sessions = [];
        this.sessionPayload = null;
        this.documents = [];
        this.images = [];
        this.auditLog = [];
        this.users = [];
        this.health = null;
        this.auditUnavailable = false;
        this.generatedAt = new Date();
    }

    async connectedCallback() {
        await this.loadData();
        this.render();
        this.setupEvents();
    }

    async loadData() {
        this.loading = true;
        this.render();
        try {
            const [sessions, documents, images, health, audit, users] = await Promise.all([
                listChatSessions().catch(() => []),
                listDocuments().catch(() => ({ documents: [] })),
                listImages().catch(() => ({ images: [] })),
                getDetailedHealth().catch(() => null),
                listAuditLog({ page: 1, pageSize: 30 }).catch(() => null),
                listAdminUsers().catch(() => []),
            ]);

            this.sessions = Array.isArray(sessions) ? sessions : [];
            this.documents = Array.isArray(documents?.documents) ? documents.documents : [];
            this.images = Array.isArray(images?.images) ? images.images : [];
            this.health = health;
            this.auditUnavailable = !audit;
            this.auditLog = Array.isArray(audit?.items) ? audit.items : Array.isArray(audit?.data) ? audit.data : [];
            this.users = Array.isArray(users) ? users : Array.isArray(users?.users) ? users.users : [];

            if (!this.selectedSessionId && this.sessions.length) {
                this.selectedSessionId = String(this.sessions[0].id);
            }
            if (!this.selectedImageId && this.images.length) {
                this.selectedImageId = String(this.images[0].id);
            }
            await this.loadSelectedSession();
        } finally {
            this.loading = false;
        }
    }

    async loadSelectedSession() {
        if (!this.selectedSessionId) {
            this.sessionPayload = null;
            return;
        }
        try {
            this.sessionPayload = await getChatSession(this.selectedSessionId);
        } catch (_) {
            this.sessionPayload = null;
        }
    }

    getSelectedImage() {
        return this.images.find((image) => String(image.id) === String(this.selectedImageId)) || null;
    }

    getSelectedSessionSummary() {
        if (this.sessionPayload) return this.sessionPayload;
        return this.sessions.find((session) => String(session.id) === String(this.selectedSessionId)) || null;
    }

    getAssistantMessages() {
        return (this.sessionPayload?.messages || []).filter((message) => message.role === 'assistant');
    }

    getUserMessages() {
        return (this.sessionPayload?.messages || []).filter((message) => message.role === 'user');
    }

    getAllSources() {
        return this.getAssistantMessages().flatMap((message) => Array.isArray(message.sources) ? message.sources : []);
    }

    buildCaseReport() {
        const session = this.getSelectedSessionSummary();
        const messages = this.sessionPayload?.messages || [];
        const assistantMessages = this.getAssistantMessages();
        const sources = this.getAllSources();
        const latestAnswer = [...assistantMessages].reverse().find((message) => message.content)?.content || 'No assistant answer recorded yet.';

        return {
            title: this.reportTitle || 'Clinical Case Report',
            sections: [
                {
                    heading: 'Case Overview',
                    body: [
                        `Session: ${getSessionTitle(session)}`,
                        `Updated: ${formatDate(session?.updated_at || session?.created_at)}`,
                        `Conversation messages: ${messages.length}`,
                        `Indexed documents: ${this.documents.length}`,
                        `Medical images: ${this.images.length}`,
                    ],
                },
                {
                    heading: 'Clinical Summary',
                    body: [latestAnswer],
                },
                {
                    heading: 'Source Evidence',
                    body: sources.length
                        ? sources.slice(0, 12).map((source, index) => `${sourceLabel(source, index)}: ${source.text || source.chunk_text || 'Evidence text unavailable.'}`)
                        : ['No cited evidence is attached to this session yet.'],
                },
                {
                    heading: 'Clinician Note',
                    body: [this.clinicianNote || 'No additional clinician note entered.'],
                },
            ],
        };
    }

    buildSoapReport() {
        const session = this.getSelectedSessionSummary();
        const note = this.sessionPayload?.soap_note || '';
        return {
            title: this.reportTitle || 'SOAP Note Report',
            sections: [
                {
                    heading: 'Session',
                    body: [
                        `Session: ${getSessionTitle(session)}`,
                        `Generated from messages: ${(this.sessionPayload?.messages || []).length}`,
                    ],
                },
                {
                    heading: 'SOAP Note',
                    body: [note || 'No SOAP note has been generated for this session yet. Generate it from Ask & Draft first.'],
                },
                {
                    heading: 'Clinician Note',
                    body: [this.clinicianNote || 'No additional clinician note entered.'],
                },
            ],
        };
    }

    buildImagingReport() {
        const image = this.getSelectedImage();
        const findings = Array.isArray(image?.analysis_result?.findings) ? image.analysis_result.findings : [];
        const annotations = Array.isArray(image?.annotations) ? image.annotations : [];
        const recommendations = Array.isArray(image?.analysis_result?.recommendations) ? image.analysis_result.recommendations : [];

        return {
            title: this.reportTitle || 'Imaging Review Report',
            image,
            sections: [
                {
                    heading: 'Image Summary',
                    body: image ? [
                        `Image: ${image.original_filename || image.filename}`,
                        `Status: ${image.analysis_status}`,
                        `Size: ${formatBytes(image.file_size)}`,
                        `Dimensions: ${image.width || '?'} x ${image.height || '?'}`,
                    ] : ['No image selected.'],
                },
                {
                    heading: 'AI Findings',
                    body: findings.length
                        ? findings.map((finding) => `${finding.description || 'Finding'} - ${finding.location || 'location not specified'} - confidence ${Math.round(Number(finding.confidence || 0) * 100)}%`)
                        : ['No automated findings available.'],
                },
                {
                    heading: 'Clinician Annotations / Corrections',
                    body: annotations.length
                        ? annotations.map((annotation) => {
                            const geometry = annotation.geometry || {};
                            return `${annotation.label}: ${annotation.description || 'No description'} | x ${Math.round(Number(geometry.x || 0) * 100)}%, y ${Math.round(Number(geometry.y || 0) * 100)}%, width ${Math.round(Number(geometry.width || 0) * 100)}%, height ${Math.round(Number(geometry.height || 0) * 100)}% | status ${annotation.review_status}`;
                        })
                        : ['No manual annotations saved.'],
                },
                {
                    heading: 'Recommendations',
                    body: recommendations.length ? recommendations : ['No recommendations available.'],
                },
                {
                    heading: 'Clinician Note',
                    body: [this.clinicianNote || 'No additional clinician note entered.'],
                },
            ],
        };
    }

    buildEvidenceReport() {
        const session = this.getSelectedSessionSummary();
        const sources = this.getAllSources();
        return {
            title: this.reportTitle || 'Evidence and Citation Report',
            sections: [
                {
                    heading: 'Session',
                    body: [`Session: ${getSessionTitle(session)}`],
                },
                {
                    heading: 'Cited Evidence Blocks',
                    body: sources.length
                        ? sources.map((source, index) => `${index + 1}. ${sourceLabel(source, index)} - ${source.text || source.chunk_text || 'Evidence text unavailable.'}`)
                        : ['No cited evidence available for this session.'],
                },
                {
                    heading: 'Source Inventory',
                    body: [
                        `Documents: ${this.documents.map((doc) => doc.filename).join(', ') || 'None'}`,
                        `Images: ${this.images.map((image) => image.original_filename || image.filename).join(', ') || 'None'}`,
                    ],
                },
            ],
        };
    }

    buildAuditReport() {
        return {
            title: this.reportTitle || 'Quality and Audit Report',
            sections: [
                {
                    heading: 'System Capability',
                    body: [
                        `Health status: ${this.health?.status || 'Unknown'}`,
                        `Documents indexed: ${this.documents.length}`,
                        `Images uploaded: ${this.images.length}`,
                        `Users visible: ${this.users.length}`,
                    ],
                },
                {
                    heading: 'Recent Audit Activity',
                    body: this.auditUnavailable
                        ? ['Audit log is unavailable to this user or backend mode.']
                        : this.auditLog.length
                            ? this.auditLog.map((entry) => `${formatDate(entry.created_at || entry.timestamp)} - ${entry.action || entry.event_type || 'event'} - ${entry.resource_type || 'resource'} ${entry.resource_id || ''}`)
                            : ['No audit entries returned.'],
                },
                {
                    heading: 'Clinician Note',
                    body: [this.clinicianNote || 'No additional admin note entered.'],
                },
            ],
        };
    }

    buildReport() {
        const builders = {
            case: () => this.buildCaseReport(),
            soap: () => this.buildSoapReport(),
            imaging: () => this.buildImagingReport(),
            evidence: () => this.buildEvidenceReport(),
            audit: () => this.buildAuditReport(),
        };
        return (builders[this.reportType] || builders.case)();
    }

    reportToMarkdown(report = this.buildReport()) {
        const lines = [
            `# ${markdownEscape(report.title)}`,
            '',
            `Generated: ${formatDate(this.generatedAt)}`,
            '',
        ];

        report.sections.forEach((section) => {
            lines.push(`## ${markdownEscape(section.heading)}`, '');
            section.body.forEach((item) => {
                const text = markdownEscape(item);
                if (!text) return;
                if (text.includes('\n')) lines.push(text, '');
                else lines.push(`- ${text}`);
            });
            lines.push('');
        });

        lines.push('## Review Notice', '');
        lines.push('- AI-generated content must be verified against original clinical sources before clinical use.');
        return lines.join('\n');
    }

    reportToHtml(report = this.buildReport()) {
        const image = report.image;
        return `
            <article class="report-document">
                <header class="report-document__header">
                    <div>
                        <div class="eyebrow">ClinicalAI Pro Report</div>
                        <h1>${escapeHtml(report.title)}</h1>
                        <p>Generated ${escapeHtml(formatDate(this.generatedAt))}</p>
                    </div>
                </header>
                ${image?.image_url ? `
                    <section class="report-section">
                        <h2>Annotated Image</h2>
                        <div class="report-image-frame">
                            <img src="${escapeAttr(image.image_url)}" alt="${escapeAttr(image.original_filename || image.filename)}" />
                            ${(image.annotations || []).map((annotation) => {
                                const geometry = annotation.geometry || {};
                                return `
                                    <span class="report-annotation-box" style="left:${Number(geometry.x || 0) * 100}%;top:${Number(geometry.y || 0) * 100}%;width:${Number(geometry.width || 0) * 100}%;height:${Number(geometry.height || 0) * 100}%;">
                                        ${escapeHtml(annotation.label || 'Finding')}
                                    </span>
                                `;
                            }).join('')}
                        </div>
                    </section>
                ` : ''}
                ${report.sections.map((section) => `
                    <section class="report-section">
                        <h2>${escapeHtml(section.heading)}</h2>
                        ${section.body.map((item) => `<p>${escapeHtml(item).replace(/\n/g, '<br />')}</p>`).join('')}
                    </section>
                `).join('')}
                <footer class="report-document__footer">
                    AI-generated content must be verified against original clinical sources before clinical use.
                </footer>
            </article>
        `;
    }

    downloadMarkdown() {
        this.generatedAt = new Date();
        const report = this.buildReport();
        const markdown = this.reportToMarkdown(report);
        const blob = new Blob([markdown], { type: 'text/markdown;charset=utf-8' });
        const url = URL.createObjectURL(blob);
        const link = document.createElement('a');
        link.href = url;
        link.download = `${(report.title || 'clinical-report').toLowerCase().replace(/[^a-z0-9]+/g, '-')}.md`;
        document.body.appendChild(link);
        link.click();
        link.remove();
        URL.revokeObjectURL(url);
        showToast('Markdown report downloaded.', 'success');
    }

    printPdf() {
        this.generatedAt = new Date();
        this.renderPrintSurface();
        requestAnimationFrame(() => {
            window.print();
        });
        showToast('Print dialog opened. Choose Save as PDF to download.', 'info');
    }

    renderPrintSurface() {
        const existing = document.getElementById('report-print-surface');
        existing?.remove();
        const report = this.buildReport();
        const surface = document.createElement('div');
        surface.id = 'report-print-surface';
        surface.innerHTML = this.reportToHtml(report);
        document.body.appendChild(surface);
    }

    renderReportSelector() {
        const types = [
            ['case', 'Case Report', 'Session summary, latest answer, evidence, and note.'],
            ['soap', 'SOAP Note', 'Generated note with review context.'],
            ['imaging', 'Imaging Report', 'Image, findings, annotations, and corrections.'],
            ['evidence', 'Evidence Report', 'Citations and retrieved source blocks.'],
            ['audit', 'Audit Report', 'Quality, capability, and recent audit activity.'],
        ];

        return `
            <div class="report-type-grid">
                ${types.map(([id, title, copy]) => `
                    <button type="button" class="report-type-card ${this.reportType === id ? 'is-selected' : ''}" data-report-type="${escapeAttr(id)}">
                        <strong>${escapeHtml(title)}</strong>
                        <span>${escapeHtml(copy)}</span>
                    </button>
                `).join('')}
            </div>
        `;
    }

    renderControls() {
        return `
            <section class="report-builder glass-panel">
                <div class="report-builder__header">
                    <div>
                        <div class="eyebrow">Report Builder</div>
                        <h2>Compose Clinical Output</h2>
                    </div>
                    <button type="button" id="refresh-report-data" class="button button--secondary">Refresh Data</button>
                </div>
                ${this.renderReportSelector()}
                <div class="report-form-grid">
                    <label class="field">
                        <span class="field-label">Report title</span>
                        <input id="report-title-input" class="field-input" value="${escapeAttr(this.reportTitle)}" />
                    </label>
                    <label class="field">
                        <span class="field-label">Chat session</span>
                        <select id="report-session-select" class="field-input">
                            <option value="">No session selected</option>
                            ${this.sessions.map((session) => `
                                <option value="${escapeAttr(session.id)}" ${String(session.id) === String(this.selectedSessionId) ? 'selected' : ''}>
                                    ${escapeHtml(getSessionTitle(session))}
                                </option>
                            `).join('')}
                        </select>
                    </label>
                    <label class="field">
                        <span class="field-label">Image study</span>
                        <select id="report-image-select" class="field-input">
                            <option value="">No image selected</option>
                            ${this.images.map((image) => `
                                <option value="${escapeAttr(image.id)}" ${String(image.id) === String(this.selectedImageId) ? 'selected' : ''}>
                                    ${escapeHtml(image.original_filename || image.filename)}
                                </option>
                            `).join('')}
                        </select>
                    </label>
                </div>
                <label class="field">
                    <span class="field-label">Clinician / reviewer note</span>
                    <textarea id="report-note-input" class="field-input" rows="5" placeholder="Add interpretation, limitations, follow-up plan, or sign-off note.">${escapeHtml(this.clinicianNote)}</textarea>
                </label>
                <div class="report-actions">
                    <button type="button" id="print-report-btn" class="button button--primary">Print / Save PDF</button>
                    <button type="button" id="download-report-btn" class="button button--secondary">Download Markdown</button>
                </div>
            </section>
        `;
    }

    renderPreview() {
        const report = this.buildReport();
        return `
            <section class="report-preview glass-panel">
                <div class="report-preview__top">
                    <div>
                        <div class="eyebrow">Live Preview</div>
                        <h2>${escapeHtml(report.title)}</h2>
                    </div>
                    <span class="status-badge status-badge--ready">${escapeHtml(this.reportType)}</span>
                </div>
                <div class="report-preview__body">
                    ${this.reportToHtml(report)}
                </div>
            </section>
        `;
    }

    render() {
        if (this.loading) {
            this.innerHTML = `
                <section class="docs-view reports-view">
                    <header class="page-header">
                        <div>
                            <div class="eyebrow">Clinical Reporting</div>
                            <h1 class="page-title">Reports</h1>
                            <p class="page-subtitle">Loading reportable case data...</p>
                        </div>
                    </header>
                    <div class="skeleton" style="height: 260px;"></div>
                </section>
            `;
            return;
        }

        this.innerHTML = `
            <section class="docs-view reports-view">
                <header class="page-header">
                    <div>
                        <div class="eyebrow">Clinical Reporting</div>
                        <h1 class="page-title">Reports</h1>
                        <p class="page-subtitle">Create case summaries, SOAP notes, imaging reports, evidence packets, and audit reports from existing workspace data.</p>
                    </div>
                </header>
                <div class="reports-layout">
                    ${this.renderControls()}
                    ${this.renderPreview()}
                </div>
            </section>
        `;
    }

    setupEvents() {
        this.querySelectorAll('[data-report-type]').forEach((button) => {
            button.addEventListener('click', () => {
                this.reportType = button.getAttribute('data-report-type') || 'case';
                const defaultTitles = {
                    case: 'Clinical Case Report',
                    soap: 'SOAP Note Report',
                    imaging: 'Imaging Review Report',
                    evidence: 'Evidence and Citation Report',
                    audit: 'Quality and Audit Report',
                };
                this.reportTitle = defaultTitles[this.reportType] || this.reportTitle;
                this.render();
                this.setupEvents();
            });
        });

        this.querySelector('#report-title-input')?.addEventListener('input', (event) => {
            this.reportTitle = event.target.value;
            this.renderPreviewOnly();
        });

        this.querySelector('#report-note-input')?.addEventListener('input', (event) => {
            this.clinicianNote = event.target.value;
            this.renderPreviewOnly();
        });

        this.querySelector('#report-session-select')?.addEventListener('change', async (event) => {
            this.selectedSessionId = event.target.value;
            await this.loadSelectedSession();
            this.render();
            this.setupEvents();
        });

        this.querySelector('#report-image-select')?.addEventListener('change', (event) => {
            this.selectedImageId = event.target.value;
            this.render();
            this.setupEvents();
        });

        this.querySelector('#print-report-btn')?.addEventListener('click', () => this.printPdf());
        this.querySelector('#download-report-btn')?.addEventListener('click', () => this.downloadMarkdown());
        this.querySelector('#refresh-report-data')?.addEventListener('click', async () => {
            await this.loadData();
            this.render();
            this.setupEvents();
            showToast('Report data refreshed.', 'success');
        });
    }

    renderPreviewOnly() {
        const preview = this.querySelector('.report-preview');
        if (!preview) return;
        const wrapper = document.createElement('div');
        wrapper.innerHTML = this.renderPreview();
        preview.replaceWith(wrapper.firstElementChild);
    }
}

customElements.define('reports-workspace', ReportsWorkspace);
export default ReportsWorkspace;
