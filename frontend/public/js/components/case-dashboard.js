import {
    listChatSessions,
    listDocuments,
    listImages,
    getDetailedHealth,
    uploadDocument,
    uploadImage,
    uploadAudioForTranscription,
    showToast,
} from '../api.js';
import { navigate } from '../router.js';

function escapeHtml(value = '') {
    return String(value)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}

class CaseDashboard extends HTMLElement {
    constructor() {
        super();
        this.sessions = [];
        this.activities = [];
        this.systemHealth = null;
        this.loading = true;
        this.isRecording = false;
        this.mediaRecorder = null;
        this.audioChunks = [];
        this.recordingTimer = null;
        this.recordingSeconds = 0;
    }

    async connectedCallback() {
        this.render();
        this.setupEvents();
        await this.loadData();
    }

    async loadData() {
        try {
            const [sessionsList, docsList, imgsList, healthData] = await Promise.all([
                listChatSessions().catch(() => []),
                listDocuments().catch(() => ({ documents: [] })),
                listImages().catch(() => ({ images: [] })),
                getDetailedHealth().catch(() => null),
            ]);

            this.sessions = sessionsList || [];
            this.systemHealth = healthData;

            // Gather all items processing or error/ready as "activity"
            const docs = Array.isArray(docsList?.documents) ? docsList.documents : [];
            const imgs = Array.isArray(imgsList?.images) ? imgsList.images : [];

            this.activities = [
                ...docs.map((d) => ({
                    id: d.id,
                    type: 'document',
                    name: d.filename,
                    status: d.status,
                    progress: d.processing_progress || 0,
                    time: d.created_at || new Date().toISOString(),
                })),
                ...imgs.map((i) => ({
                    id: i.id,
                    type: 'image',
                    name: i.original_filename || i.filename || 'Medical Image',
                    status: i.analysis_status || 'ready',
                    progress: i.analysis_status === 'processing' ? 50 : 100,
                    time: i.created_at || new Date().toISOString(),
                })),
            ];

            // Sort activities by recent time
            this.activities.sort((a, b) => new Date(b.time) - new Date(a.time));

        } catch (err) {
            console.error('Error loading dashboard data', err);
        } finally {
            this.loading = false;
            this.render();
            this.setupEvents();
        }
    }

    renderRecentSessions() {
        if (!this.sessions || this.sessions.length === 0) {
            return `<div class="empty-inline">No recent case workspaces. Click 'Start New Case' above to start.</div>`;
        }

        return `
            <div class="dashboard-recent-list">
                ${this.sessions.slice(0, 5).map((session) => `
                    <div class="dashboard-recent-item" data-open-session="${escapeHtml(session.id)}">
                        <span class="recent-icon">📂</span>
                        <div class="recent-details">
                            <div class="recent-title">${escapeHtml(session.title || 'Untitled Session')}</div>
                            <div class="recent-meta">Updated ${new Date(session.updated_at).toLocaleString()}</div>
                        </div>
                    </div>
                `).join('')}
            </div>
        `;
    }

    renderProcessingActivity() {
        const activeItems = this.activities.filter(a => ['queued', 'processing', 'error'].includes(a.status));
        if (activeItems.length === 0) {
            return `<div class="empty-inline">All clinical sources successfully indexed and ready.</div>`;
        }

        return `
            <div class="dashboard-active-list">
                ${activeItems.slice(0, 5).map((item) => `
                    <div class="dashboard-active-item">
                        <span class="active-icon">${item.type === 'image' ? '🖼️' : '📄'}</span>
                        <div class="active-details">
                            <div class="active-title">${escapeHtml(item.name)}</div>
                            <div class="active-progress-wrap">
                                <div class="active-progress-bar" style="width: ${item.progress}%"></div>
                            </div>
                        </div>
                        <span class="status-badge status-badge--${escapeHtml(item.status)}">${escapeHtml(item.status)}</span>
                    </div>
                `).join('')}
            </div>
        `;
    }

    renderHealthStatus() {
        const services = this.systemHealth?.services || {};

        const postgres = services.postgres?.status === 'healthy' || services.postgres?.status === 'ok';
        const vector_store = services.vector_store?.status === 'healthy' || services.vector_store?.status === 'ok';
        const llm_provider = services.llm_provider?.status === 'healthy' || services.llm_provider?.status === 'ok';
        const neo4j = services.neo4j?.status === 'healthy' || services.neo4j?.status === 'ok';
        const background_jobs = services.background_jobs?.status === 'healthy' || services.background_jobs?.status === 'ok';
        const redis = services.redis?.status === 'healthy' || services.redis?.status === 'ok';

        const ragReady = postgres && vector_store && llm_provider;
        const visionReady = llm_provider;
        const audioReady = redis && background_jobs;
        const graphReady = neo4j;
        const adminReady = postgres && background_jobs;

        const getBadge = (ready) => ready ? 'ready' : 'error';
        const getLabel = (ready) => ready ? 'Ready' : 'Offline';

        return `
            <div class="dashboard-health-chips" style="display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 16px; margin-top: 12px; width: 100%;">
                <div class="health-chip flex-row" style="background: rgba(255,255,255,0.01); border: 1px solid var(--border-subtle); padding: 12px 16px; border-radius: 16px; display: flex; align-items: center; justify-content: space-between; gap: 8px;">
                    <div style="display: flex; align-items: center; gap: 8px;">
                        <span class="status-pulse status-pulse--${getBadge(ragReady)}"></span>
                        <span style="font-size: 0.88rem; font-weight: 600;">RAG Search</span>
                    </div>
                    <span class="status-badge status-badge--${getBadge(ragReady)}" style="font-size: 0.72rem; padding: 2px 8px;">${getLabel(ragReady)}</span>
                </div>
                <div class="health-chip flex-row" style="background: rgba(255,255,255,0.01); border: 1px solid var(--border-subtle); padding: 12px 16px; border-radius: 16px; display: flex; align-items: center; justify-content: space-between; gap: 8px;">
                    <div style="display: flex; align-items: center; gap: 8px;">
                        <span class="status-pulse status-pulse--${getBadge(visionReady)}"></span>
                        <span style="font-size: 0.88rem; font-weight: 600;">Vision (Scans)</span>
                    </div>
                    <span class="status-badge status-badge--${getBadge(visionReady)}" style="font-size: 0.72rem; padding: 2px 8px;">${getLabel(visionReady)}</span>
                </div>
                <div class="health-chip flex-row" style="background: rgba(255,255,255,0.01); border: 1px solid var(--border-subtle); padding: 12px 16px; border-radius: 16px; display: flex; align-items: center; justify-content: space-between; gap: 8px;">
                    <div style="display: flex; align-items: center; gap: 8px;">
                        <span class="status-pulse status-pulse--${getBadge(audioReady)}"></span>
                        <span style="font-size: 0.88rem; font-weight: 600;">Audio Dictation</span>
                    </div>
                    <span class="status-badge status-badge--${getBadge(audioReady)}" style="font-size: 0.72rem; padding: 2px 8px;">${getLabel(audioReady)}</span>
                </div>
                <div class="health-chip flex-row" style="background: rgba(255,255,255,0.01); border: 1px solid var(--border-subtle); padding: 12px 16px; border-radius: 16px; display: flex; align-items: center; justify-content: space-between; gap: 8px;">
                    <div style="display: flex; align-items: center; gap: 8px;">
                        <span class="status-pulse status-pulse--${getBadge(graphReady)}"></span>
                        <span style="font-size: 0.88rem; font-weight: 600;">Knowledge Graph</span>
                    </div>
                    <span class="status-badge status-badge--${getBadge(graphReady)}" style="font-size: 0.72rem; padding: 2px 8px;">${getLabel(graphReady)}</span>
                </div>
                <div class="health-chip flex-row" style="background: rgba(255,255,255,0.01); border: 1px solid var(--border-subtle); padding: 12px 16px; border-radius: 16px; display: flex; align-items: center; justify-content: space-between; gap: 8px;">
                    <div style="display: flex; align-items: center; gap: 8px;">
                        <span class="status-pulse status-pulse--${getBadge(adminReady)}"></span>
                        <span style="font-size: 0.88rem; font-weight: 600;">Quality & Evals</span>
                    </div>
                    <span class="status-badge status-badge--${getBadge(adminReady)}" style="font-size: 0.72rem; padding: 2px 8px;">${getLabel(adminReady)}</span>
                </div>
            </div>
        `;
    }

    render() {
        this.innerHTML = `
            <section class="docs-view dashboard-view">
                <header class="page-header" style="margin-bottom: 24px;">
                    <div>
                        <div class="eyebrow">Clinical Intelligence Shell</div>
                        <h1 class="page-title" style="margin-bottom: 8px;">Home Dashboard</h1>
                        <p class="page-subtitle">Initialize case workspaces, upload medical reports, dictate audio clinical summaries, and monitor capability states.</p>
                    </div>
                </header>

                <div class="dashboard-grid" style="display: grid; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); gap: 20px; margin-bottom: 24px;">
                    <article class="glass-panel dashboard-card-action" id="btn-dashboard-new-case" style="padding: 24px; cursor: pointer; transition: border-color var(--transition-fast);">
                        <div class="dashboard-card-action__icon" style="font-size: 2.2rem; margin-bottom: 12px;">⚕️</div>
                        <h3 style="margin: 0 0 6px; font-size: 1.15rem;">Start Fresh Case</h3>
                        <p style="font-size: 0.88rem; color: var(--text-secondary); margin-bottom: 20px;">Open a fresh clinical chat interface without starting attachments.</p>
                        <button class="button button--primary button--full" style="min-height: 38px;">New Case Session</button>
                    </article>

                    <label class="glass-panel dashboard-card-action" id="btn-dashboard-upload-doc" style="padding: 24px; cursor: pointer; transition: border-color var(--transition-fast); display: block;">
                        <input id="dashboard-doc-input" type="file" accept=".pdf,.txt,.md,.csv" hidden />
                        <div class="dashboard-card-action__icon" style="font-size: 2.2rem; margin-bottom: 12px;">📄</div>
                        <h3 style="margin: 0 0 6px; font-size: 1.15rem;">Start with Document</h3>
                        <p style="font-size: 0.88rem; color: var(--text-secondary); margin-bottom: 20px;">Upload charts, records, or patient summaries to auto-start workspace.</p>
                        <span class="button button--secondary button--full" style="min-height: 38px; display: inline-flex; align-items: center; justify-content: center; width: 100%;">Select Document</span>
                    </label>

                    <label class="glass-panel dashboard-card-action" id="btn-dashboard-upload-img" style="padding: 24px; cursor: pointer; transition: border-color var(--transition-fast); display: block;">
                        <input id="dashboard-img-input" type="file" accept="image/png,image/jpeg,image/gif,image/webp" hidden />
                        <div class="dashboard-card-action__icon" style="font-size: 2.2rem; margin-bottom: 12px;">🖼️</div>
                        <h3 style="margin: 0 0 6px; font-size: 1.15rem;">Start with Scan</h3>
                        <p style="font-size: 0.88rem; color: var(--text-secondary); margin-bottom: 20px;">Upload diagnostic scans or image panels to immediately analyze context.</p>
                        <span class="button button--secondary button--full" style="min-height: 38px; display: inline-flex; align-items: center; justify-content: center; width: 100%;">Select Medical Scan</span>
                    </label>

                    <article class="glass-panel dashboard-card-action ${this.isRecording ? 'is-recording' : ''}" id="btn-dashboard-record-audio" style="padding: 24px; cursor: pointer; transition: border-color var(--transition-fast);">
                        <div class="dashboard-card-action__icon" style="font-size: 2.2rem; margin-bottom: 12px;">${this.isRecording ? '🛑' : '🎤'}</div>
                        <h3 style="margin: 0 0 6px; font-size: 1.15rem;">${this.isRecording ? 'Recording Audio…' : 'Dictate Case Note'}</h3>
                        <p style="font-size: 0.88rem; color: var(--text-secondary); margin-bottom: 20px;">
                            ${this.isRecording ? `Capture time: ${this.recordingSeconds}s. Click stop to transcribe.` : 'Capture verbal case outlines and convert to SOAP editor text.'}
                        </p>
                        <button class="button ${this.isRecording ? 'button--danger' : 'button--secondary'} button--full" style="min-height: 38px;">
                            ${this.isRecording ? 'Stop Recording' : 'Start Recording'}
                        </button>
                    </article>
                </div>

                <div class="dashboard-middle-grid" style="display: grid; grid-template-columns: repeat(auto-fit, minmax(400px, 1fr)); gap: 24px; margin-bottom: 24px;">
                    <section class="glass-panel dashboard-sessions" style="padding: 20px;">
                        <div class="eyebrow" style="margin-bottom: 4px;">Recent Workspaces</div>
                        <h3 style="margin: 0 0 16px; font-size: 1.15rem;">Recent Case Sessions</h3>
                        ${this.loading ? '<div class="skeleton" style="height: 120px; border-radius: 12px;"></div>' : this.renderRecentSessions()}
                    </section>

                    <section class="glass-panel dashboard-processing" style="padding: 20px;">
                        <div class="eyebrow" style="margin-bottom: 4px;">Background Jobs</div>
                        <h3 style="margin: 0 0 16px; font-size: 1.15rem;">Indexing & Extraction Pipeline</h3>
                        ${this.loading ? '<div class="skeleton" style="height: 120px; border-radius: 12px;"></div>' : this.renderProcessingActivity()}
                    </section>
                </div>

                <section class="glass-panel dashboard-status" style="padding: 20px;">
                    <div class="eyebrow" style="margin-bottom: 4px;">System Health</div>
                    <h3 style="margin: 0 0 16px; font-size: 1.15rem;">System Capability Status</h3>
                    ${this.loading ? '<div class="skeleton" style="height: 48px; border-radius: 12px;"></div>' : this.renderHealthStatus()}
                </section>
            </section>
        `;
    }

    setupEvents() {
        // Start New Case
        this.querySelector('#btn-dashboard-new-case')?.addEventListener('click', () => {
            window.sessionStorage.removeItem('clinical_active_session_id');
            window.sessionStorage.removeItem('clinical_loaded_session_payload');
            window.dispatchEvent(new CustomEvent('clinical:new-chat'));
            navigate('/workspace');
            showToast('Started new clinical case.', 'success');
        });

        // Document upload
        const docInput = this.querySelector('#dashboard-doc-input');
        docInput?.addEventListener('change', async () => {
            const file = docInput.files?.[0];
            if (!file) return;
            showToast(`Uploading ${file.name}...`, 'info');
            try {
                const response = await uploadDocument(file, () => {});
                showToast(`Successfully uploaded ${file.name}. Starting case workspace…`, 'success');
                const attachment = {
                    id: response.id,
                    name: response.filename,
                    type: 'document',
                    size: response.file_size || file.size,
                    status: response.status || 'ready',
                    progress: 100
                };
                window.sessionStorage.setItem('clinical_graphrag_pending_attachment', JSON.stringify(attachment));
                window.sessionStorage.removeItem('clinical_active_session_id');
                window.sessionStorage.removeItem('clinical_loaded_session_payload');
                window.dispatchEvent(new CustomEvent('clinical:new-chat'));
                navigate('/workspace');
            } catch (err) {
                showToast(err.message || 'Document upload failed.', 'error');
            }
        });

        // Image upload
        const imgInput = this.querySelector('#dashboard-img-input');
        imgInput?.addEventListener('change', async () => {
            const file = imgInput.files?.[0];
            if (!file) return;
            showToast(`Uploading ${file.name}...`, 'info');
            try {
                const response = await uploadImage(file, () => {});
                showToast(`Successfully uploaded scan ${file.name}. Starting case workspace…`, 'success');
                const attachment = {
                    id: response.id,
                    name: response.original_filename || response.filename || file.name,
                    type: 'image',
                    previewUrl: response.thumbnail_url || response.image_url,
                    progress: 100
                };
                window.sessionStorage.setItem('clinical_graphrag_pending_attachment', JSON.stringify(attachment));
                window.sessionStorage.removeItem('clinical_active_session_id');
                window.sessionStorage.removeItem('clinical_loaded_session_payload');
                window.dispatchEvent(new CustomEvent('clinical:new-chat'));
                navigate('/workspace');
            } catch (err) {
                showToast(err.message || 'Image upload failed.', 'error');
            }
        });

        // Record Audio Toggle
        this.querySelector('#btn-dashboard-record-audio')?.addEventListener('click', async () => {
            await this.toggleRecording();
        });

        // Click recent session items
        this.querySelectorAll('[data-open-session]').forEach((item) => {
            item.addEventListener('click', async () => {
                const sessionId = item.getAttribute('data-open-session');
                if (sessionId) {
                    window.sessionStorage.setItem('clinical_active_session_id', sessionId);
                    navigate('/workspace');
                }
            });
        });
    }

    async toggleRecording() {
        if (this.isRecording) {
            // Stop recording
            if (this.mediaRecorder && this.mediaRecorder.state !== 'inactive') {
                this.mediaRecorder.stop();
            }
            this.isRecording = false;
            clearInterval(this.recordingTimer);
            this.recordingSeconds = 0;
            showToast('Transcribing audio note...', 'info');
        } else {
            // Start recording
            try {
                const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
                this.audioChunks = [];
                this.mediaRecorder = new MediaRecorder(stream, { mimeType: 'audio/webm' });

                this.mediaRecorder.addEventListener('dataavailable', (event) => {
                    if (event.data.size > 0) this.audioChunks.push(event.data);
                });

                this.mediaRecorder.addEventListener('stop', async () => {
                    const audioBlob = new Blob(this.audioChunks, { type: 'audio/webm' });
                    const file = new File([audioBlob], `recording-${Date.now()}.webm`, { type: 'audio/webm' });
                    try {
                        const response = await uploadAudioForTranscription(file);
                        if (response && response.transcript) {
                            showToast('Voice note transcribed successfully.', 'success');
                            // Prime context and navigate to workspace
                            window.sessionStorage.setItem('clinical_pending_draft', response.transcript);
                            navigate('/workspace');
                        } else {
                            showToast('Transcribed audio yielded no text.', 'warning');
                        }
                    } catch (err) {
                        showToast(err.message || 'Audio transcription failed.', 'error');
                    }
                });

                this.mediaRecorder.start();
                this.isRecording = true;
                this.recordingSeconds = 0;
                this.recordingTimer = setInterval(() => {
                    this.recordingSeconds++;
                    this.render();
                    this.setupEvents();
                }, 1000);

                this.render();
                this.setupEvents();
                showToast('Recording voice note...', 'info');

            } catch (err) {
                console.error(err);
                showToast('Unable to access recording device.', 'error');
            }
        }
    }
}

customElements.define('case-dashboard', CaseDashboard);
