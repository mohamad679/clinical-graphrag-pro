import {
    listDocuments,
    uploadDocument,
    deleteDocument,
    retryDocumentProcessing,
    getDocumentStatus,
    listImages,
    uploadImage,
    deleteImage,
    transcribeAudio,
    showToast,
} from '../api.js';
import { navigate } from '../router.js';
import { modal } from '../lib/modal.js';

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

function formatBytes(bytes = 0) {
    const value = Number(bytes);
    if (!value || value <= 0) return '0 B';
    if (value < 1024) return `${value} B`;
    if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`;
    return `${(value / (1024 * 1024)).toFixed(1)} MB`;
}

class SourceLibrary extends HTMLElement {
    constructor() {
        super();
        this.activeTab = 'documents'; // documents, images, audio
        this.documents = [];
        this.images = [];
        this.loading = true;
        this.searchTerm = '';
        this.documentPollers = new Map();
        
        // Voice transcription state
        this.isRecording = false;
        this.mediaRecorder = null;
        this.audioChunks = [];
        this.transcribing = false;
        this.lastTranscript = '';
        this.timer = null;
        this.seconds = 0;
    }

    connectedCallback() {
        this.render();
        this.setupEvents();
        this.loadSources();
    }

    disconnectedCallback() {
        this.documentPollers.forEach(p => clearInterval(p));
        this.documentPollers.clear();
        clearInterval(this.timer);
    }

    async loadSources() {
        this.loading = true;
        this.render();
        this.setupEvents();
        try {
            const [docsPayload, imgsPayload] = await Promise.all([
                listDocuments().catch(() => ({ documents: [] })),
                listImages().catch(() => ({ images: [] })),
            ]);
            this.documents = Array.isArray(docsPayload?.documents) ? docsPayload.documents : [];
            this.images = Array.isArray(imgsPayload?.images) ? imgsPayload.images : [];
            
            // Poll any documents still processing
            this.documents.forEach(d => {
                if (['queued', 'processing'].includes(d.status)) {
                    this.pollDocStatus(d.id);
                }
            });
        } catch (err) {
            showToast(err.message || 'Unable to retrieve clinical sources.', 'error');
        } finally {
            this.loading = false;
            this.render();
            this.setupEvents();
        }
    }

    pollDocStatus(docId) {
        if (this.documentPollers.has(docId)) return;
        const interval = setInterval(async () => {
            try {
                const status = await getDocumentStatus(docId);
                this.documents = this.documents.map(d => d.id === docId ? {
                    ...d,
                    status: status.status,
                    processing_progress: status.progress,
                    chunk_count: status.chunk_count,
                    error_message: status.error_message,
                } : d);

                if (['ready', 'error'].includes(status.status)) {
                    clearInterval(interval);
                    this.documentPollers.delete(docId);
                    if (status.status === 'ready') {
                        showToast(`Document indexed and ready.`, 'success');
                    } else {
                        showToast(status.error_message || 'Indexing failed.', 'error');
                    }
                }
                this.render();
                this.setupEvents();
            } catch (_) {
                clearInterval(interval);
                this.documentPollers.delete(docId);
            }
        }, 3000);
        this.documentPollers.set(docId, interval);
    }

    getFilteredDocs() {
        const query = this.searchTerm.trim().toLowerCase();
        if (!query) return this.documents;
        return this.documents.filter(d => d.filename.toLowerCase().includes(query));
    }

    getFilteredImages() {
        const query = this.searchTerm.trim().toLowerCase();
        if (!query) return this.images;
        return this.images.filter(i => (i.original_filename || i.filename || '').toLowerCase().includes(query));
    }

    renderDocuments() {
        const docs = this.getFilteredDocs();
        if (docs.length === 0) {
            return `<div class="empty-inline">No clinical documents found. Drag a document into the zone above to begin indexing.</div>`;
        }

        return `
            <div class="document-list">
                ${docs.map((doc) => `
                    <article class="document-card">
                        <div class="document-card__header">
                            <div class="document-card__icon">DOC</div>
                            <div class="document-card__copy">
                                <div class="document-card__title">${escapeHtml(doc.filename)}</div>
                                <div class="document-card__meta">
                                    ${escapeHtml(formatBytes(doc.file_size))} · ${doc.chunk_count || 0} chunks
                                </div>
                            </div>
                            <span class="status-badge status-badge--${escapeHtml(doc.status)}">${escapeHtml(doc.status)}</span>
                        </div>
                        ${['queued', 'processing'].includes(doc.status) ? `
                            <div class="progress-track"><div class="progress-fill" style="width:${doc.processing_progress || 10}%"></div></div>
                        ` : ''}
                        ${doc.error_message ? `<div class="form-error" style="margin-top:8px;">${escapeHtml(doc.error_message)}</div>` : ''}
                        
                        <div class="document-card__actions" style="margin-top:12px; display:flex; gap:8px;">
                            <button type="button" class="button button--secondary" data-chat-doc="${escapeAttr(doc.id)}" ${doc.status !== 'ready' ? 'disabled' : ''}>Use in Chat</button>
                            ${doc.status === 'error' ? `<button type="button" class="button button--secondary" data-retry-doc="${escapeAttr(doc.id)}">Retry</button>` : ''}
                            <button type="button" class="button button--ghost" data-delete-doc="${escapeAttr(doc.id)}">Delete</button>
                        </div>
                    </article>
                `).join('')}
            </div>
        `;
    }

    renderImages() {
        const imgs = this.getFilteredImages();
        if (imgs.length === 0) {
            return `<div class="empty-inline">No medical scans found. Upload a scan to review annotations and run vision model runs.</div>`;
        }

        return `
            <div class="document-list">
                ${imgs.map((img) => `
                    <article class="document-card">
                        <div class="document-card__header">
                            <div class="document-card__icon" style="background:rgba(96,165,250,0.15);color:#60a5fa;">IMG</div>
                            <div class="document-card__copy">
                                <div class="document-card__title">${escapeHtml(img.original_filename || img.filename)}</div>
                                <div class="document-card__meta">
                                    ${escapeHtml(formatBytes(img.file_size))}
                                </div>
                            </div>
                            <span class="status-badge status-badge--ready">Ready</span>
                        </div>
                        <div class="document-card__actions" style="margin-top:12px; display:flex; gap:8px;">
                            <button type="button" class="button button--secondary" data-chat-img="${escapeAttr(img.id)}">Use in Chat</button>
                            <button type="button" class="button button--ghost" data-delete-img="${escapeAttr(img.id)}">Delete</button>
                        </div>
                    </article>
                `).join('')}
            </div>
        `;
    }

    renderAudioTranscribeSection() {
        return `
            <div class="audio-transcription-section glass-panel" style="padding:24px; display:flex; flex-direction:column; gap:20px;">
                <div class="audio-controls flex-row" style="justify-content:space-between; gap:16px;">
                    <div>
                        <h4 style="margin:0; font-size:16px;">Clinician Audio Recording</h4>
                        <p style="margin:4px 0 0; color:var(--text-muted); font-size:13px;">Record dictations directly or drag-drop pre-recorded .webm notes.</p>
                    </div>
                    
                    <div class="flex-row" style="gap:12px;">
                        <button type="button" class="button ${this.isRecording ? 'button--danger' : 'button--secondary'}" id="record-source-btn">
                            ${this.isRecording ? `🛑 Stop (${this.seconds}s)` : '🎤 Record Dictation'}
                        </button>
                        
                        <label class="button button--secondary" style="margin:0;">
                            <input id="audio-file-input" type="file" accept="audio/*" hidden />
                            Upload Audio File
                        </label>
                    </div>
                </div>

                ${this.transcribing ? `
                    <div class="empty-inline flex-row" style="gap:12px;">
                        <span class="status-pulse is-live"></span>
                        <span>Transcribing clinical dictation... please wait.</span>
                    </div>
                ` : ''}

                ${this.lastTranscript ? `
                    <div class="transcript-editor-box" style="display:flex; flex-direction:column; gap:8px;">
                        <div class="field-label">Transcript Output Preview</div>
                        <textarea class="field-input" rows="6" id="audio-transcript-result" style="font-family:inherit;">${escapeHtml(this.lastTranscript)}</textarea>
                        <div class="flex-row" style="gap:8px; margin-top:8px;">
                            <button type="button" class="button button--primary" id="use-transcript-btn">Use in Case Chat</button>
                            <button type="button" class="button button--secondary" id="copy-transcript-btn">Copy Text</button>
                            <button type="button" class="button button--ghost" id="clear-transcript-btn">Discard</button>
                        </div>
                    </div>
                ` : ''}
            </div>
        `;
    }

    render() {
        this.innerHTML = `
            <section class="docs-view">
                <header class="page-header">
                    <div>
                        <div class="eyebrow">Evidence Repository</div>
                        <h1 class="page-title">Source Library</h1>
                        <p class="page-subtitle">Unified file storage. Index histories, view medical scans, transcribe audio dictations, and verify pipeline indexing logs.</p>
                    </div>
                </header>

                <!-- Unified Drop Ingestion Zone -->
                <div class="docs-toolbar" style="grid-template-columns: 1fr;">
                    <label class="upload-zone" id="library-upload-zone" style="min-height: 120px; padding:16px;">
                        <input id="library-file-input" type="file" accept=".pdf,.txt,.md,.csv,image/*" hidden />
                        <span class="upload-zone__icon" style="width:40px; height:40px; font-size:1.2rem;">+</span>
                        <span class="upload-zone__title" style="font-size:1rem;">Ingest Clinical File / Image Scan</span>
                        <span class="upload-zone__subtitle" style="font-size:12px;">Drag PDFs, TXT, CSV, or medical images directly here.</span>
                    </label>
                </div>

                <!-- Tabs + Search -->
                <div class="library-filter-row flex-row" style="justify-content:space-between; margin-top:20px; border-bottom:1px solid var(--border-subtle); padding-bottom:12px; gap:20px; flex-wrap:wrap;">
                    <div class="library-tabs flex-row" style="gap:8px;">
                        <button type="button" class="button ${this.activeTab === 'documents' ? 'button--primary' : 'button--secondary'}" data-tab="documents" style="min-height:36px; padding:0 14px;">Documents</button>
                        <button type="button" class="button ${this.activeTab === 'images' ? 'button--primary' : 'button--secondary'}" data-tab="images" style="min-height:36px; padding:0 14px;">Medical Scans</button>
                        <button type="button" class="button ${this.activeTab === 'audio' ? 'button--primary' : 'button--secondary'}" data-tab="audio" style="min-height:36px; padding:0 14px;">Audio Dictations</button>
                    </div>

                    <input id="library-search" class="field-input" type="search" placeholder="Search filenames..." value="${escapeAttr(this.searchTerm)}" style="max-width:320px; border-radius:12px; padding:8px 12px; min-height:36px;" />
                </div>

                <div class="library-results-content" style="margin-top:20px;">
                    ${this.loading ? `
                        <div class="document-list">
                            <div class="skeleton" style="height:100px;"></div>
                            <div class="skeleton" style="height:100px;"></div>
                        </div>
                    ` : `
                        ${this.activeTab === 'documents' ? this.renderDocuments() : ''}
                        ${this.activeTab === 'images' ? this.renderImages() : ''}
                        ${this.activeTab === 'audio' ? this.renderAudioTranscribeSection() : ''}
                    `}
                </div>
            </section>
        `;
    }

    setupEvents() {
        // Tab switching
        this.querySelectorAll('[data-tab]').forEach((btn) => {
            btn.addEventListener('click', () => {
                this.activeTab = btn.getAttribute('data-tab');
                this.render();
                this.setupEvents();
            });
        });

        // Search input
        const search = this.querySelector('#library-search');
        search?.addEventListener('input', () => {
            this.searchTerm = search.value;
            this.render();
            this.setupEvents();
        });

        // Unified Drag Drop
        const uploadZone = this.querySelector('#library-upload-zone');
        const fileInput = this.querySelector('#library-file-input');

        uploadZone?.addEventListener('dragover', (event) => {
            event.preventDefault();
            uploadZone.classList.add('is-dragover');
        });
        uploadZone?.addEventListener('dragleave', () => uploadZone.classList.remove('is-dragover'));
        uploadZone?.addEventListener('drop', async (event) => {
            event.preventDefault();
            uploadZone.classList.remove('is-dragover');
            const file = event.dataTransfer?.files?.[0];
            if (file) await this.handleDirectUpload(file);
        });

        fileInput?.addEventListener('change', async () => {
            const file = fileInput.files?.[0];
            if (file) await this.handleDirectUpload(file);
            fileInput.value = '';
        });

	        // Delegated source actions survive list re-renders after delete/retry.
	        const resultsContent = this.querySelector('.library-results-content');
	        if (resultsContent) {
	            resultsContent.onclick = async (event) => {
	                const button = event.target.closest('button[data-chat-doc], button[data-retry-doc], button[data-delete-doc], button[data-chat-img], button[data-delete-img]');
	                if (!button || !resultsContent.contains(button)) return;

	                const docChatId = button.getAttribute('data-chat-doc');
	                if (docChatId) {
	                    const doc = this.documents.find(d => String(d.id) === docChatId);
	                    if (!doc) return;
	                    window.sessionStorage.setItem('clinical_graphrag_pending_attachment', JSON.stringify({
	                        id: doc.id,
	                        name: doc.filename,
	                        type: 'document',
	                        size: doc.file_size,
	                        chunkCount: doc.chunk_count,
	                        progress: 100,
	                        status: 'ready',
	                    }));
	                    window.sessionStorage.removeItem('clinical_loaded_session_payload');
	                    window.dispatchEvent(new CustomEvent('clinical:new-chat'));
	                    navigate('/workspace');
	                    showToast(`Attached ${doc.filename} to a new workspace session.`, 'success');
	                    return;
	                }

	                const retryDocId = button.getAttribute('data-retry-doc');
	                if (retryDocId) {
	                    try {
	                        button.disabled = true;
	                        await retryDocumentProcessing(retryDocId);
	                        showToast('Retrying processing...', 'info');
	                        await this.loadSources();
	                    } catch (err) {
	                        button.disabled = false;
	                        showToast(err.message || 'Retry failed.', 'error');
	                    }
	                    return;
	                }

	                const deleteDocId = button.getAttribute('data-delete-doc');
	                if (deleteDocId) {
	                    const confirmed = await modal.confirm('Permanently delete this document and all indexed vectors?', {
	                        title: 'Delete Document',
	                        confirmLabel: 'Delete',
	                        destructive: true,
	                    });
	                    modal.forceClose();
	                    if (!confirmed) return;
	                    try {
	                        button.disabled = true;
	                        await deleteDocument(deleteDocId);
	                        this.documents = this.documents.filter((doc) => String(doc.id) !== String(deleteDocId));
	                        const poller = this.documentPollers.get(deleteDocId);
	                        if (poller) clearInterval(poller);
	                        this.documentPollers.delete(deleteDocId);
	                        this.render();
	                        this.setupEvents();
	                        modal.forceClose();
	                        showToast('Document deleted.', 'success');
	                    } catch (err) {
	                        button.disabled = false;
	                        modal.forceClose();
	                        showToast(err.message || 'Delete failed.', 'error');
	                    }
	                    return;
	                }

	                const imgChatId = button.getAttribute('data-chat-img');
	                if (imgChatId) {
	                    const img = this.images.find(i => String(i.id) === imgChatId);
	                    if (!img) return;
	                    window.sessionStorage.setItem('clinical_graphrag_pending_attachment', JSON.stringify({
	                        id: img.id,
	                        name: img.original_filename || img.filename,
	                        type: 'image',
	                        previewUrl: img.thumbnail_url || img.image_url,
	                        progress: 100,
	                    }));
	                    window.sessionStorage.removeItem('clinical_loaded_session_payload');
	                    window.dispatchEvent(new CustomEvent('clinical:new-chat'));
	                    navigate('/workspace');
	                    showToast(`Attached image scan to a new workspace session.`, 'success');
	                    return;
	                }

	                const deleteImgId = button.getAttribute('data-delete-img');
	                if (deleteImgId) {
	                    const confirmed = await modal.confirm('Permanently delete this scan?', {
	                        title: 'Delete Scan',
	                        confirmLabel: 'Delete',
	                        destructive: true,
	                    });
	                    modal.forceClose();
	                    if (!confirmed) return;
	                    try {
	                        button.disabled = true;
	                        await deleteImage(deleteImgId);
	                        this.images = this.images.filter((img) => String(img.id) !== String(deleteImgId));
	                        this.render();
	                        this.setupEvents();
	                        modal.forceClose();
	                        showToast('Scan deleted.', 'success');
	                    } catch (err) {
	                        button.disabled = false;
	                        modal.forceClose();
	                        showToast(err.message || 'Delete failed.', 'error');
	                    }
	                }
	            };
	        }

        // Audio controls
        const recordBtn = this.querySelector('#record-source-btn');
        recordBtn?.addEventListener('click', async () => {
            await this.toggleRecording();
        });

        const audioFileInput = this.querySelector('#audio-file-input');
        audioFileInput?.addEventListener('change', async () => {
            const file = audioFileInput.files?.[0];
            if (file) await this.handleAudioTranscription(file);
            audioFileInput.value = '';
        });

        // Transcript actions
        this.querySelector('#copy-transcript-btn')?.addEventListener('click', async () => {
            const txt = this.querySelector('#audio-transcript-result')?.value;
            if (txt) {
                await navigator.clipboard.writeText(txt);
                showToast('Transcript copied.', 'success');
            }
        });

        this.querySelector('#clear-transcript-btn')?.addEventListener('click', () => {
            this.lastTranscript = '';
            this.render();
            this.setupEvents();
        });

        this.querySelector('#use-transcript-btn')?.addEventListener('click', () => {
            const txt = this.querySelector('#audio-transcript-result')?.value;
            if (txt) {
                window.sessionStorage.setItem('clinical_pending_draft', txt);
                navigate('/workspace');
                showToast('Draft transcript copied to workspace editor.', 'success');
            }
        });
    }

    async handleDirectUpload(file) {
        const mime = file.type.toLowerCase();
        const isImg = mime.startsWith('image/');
        showToast(`Uploading ${file.name}...`, 'info');
        try {
            if (isImg) {
                await uploadImage(file, () => {});
            } else {
                await uploadDocument(file, () => {});
            }
            showToast(`Upload completed.`, 'success');
            await this.loadSources();
        } catch (err) {
            showToast(err.message || 'File upload failed.', 'error');
        }
    }

    async toggleRecording() {
        if (this.isRecording) {
            if (this.mediaRecorder && this.mediaRecorder.state !== 'inactive') {
                this.mediaRecorder.stop();
            }
            this.isRecording = false;
            clearInterval(this.timer);
            this.seconds = 0;
            this.render();
            this.setupEvents();
        } else {
            try {
                const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
                this.audioChunks = [];
                this.mediaRecorder = new MediaRecorder(stream, { mimeType: 'audio/webm' });

                this.mediaRecorder.addEventListener('dataavailable', (event) => {
                    if (event.data.size > 0) this.audioChunks.push(event.data);
                });

                this.mediaRecorder.addEventListener('stop', async () => {
                    const audioBlob = new Blob(this.audioChunks, { type: 'audio/webm' });
                    const file = new File([audioBlob], `recorded-dictation.webm`, { type: 'audio/webm' });
                    await this.handleAudioTranscription(file);
                });

                this.mediaRecorder.start();
                this.isRecording = true;
                this.seconds = 0;
                this.timer = setInterval(() => {
                    this.seconds++;
                    const btn = this.querySelector('#record-source-btn');
                    if (btn) btn.textContent = `🛑 Stop (${this.seconds}s)`;
                }, 1000);

                showToast('Recording voice note...', 'info');
            } catch (_) {
                showToast('Unable to open recording device.', 'error');
            }
        }
    }

    async handleAudioTranscription(file) {
        this.transcribing = true;
        this.lastTranscript = '';
        this.render();
        this.setupEvents();
        try {
            const response = await transcribeAudio(file);
            if (response && response.transcript) {
                this.lastTranscript = response.transcript;
                showToast('Audio transcribed successfully.', 'success');
            } else {
                showToast('Audio parsed, no transcription text yielded.', 'warning');
            }
        } catch (err) {
            showToast(err.message || 'Failed to transcribe audio file.', 'error');
        } finally {
            this.transcribing = false;
            this.render();
            this.setupEvents();
        }
    }
}

customElements.define('source-library', SourceLibrary);
export default SourceLibrary;
