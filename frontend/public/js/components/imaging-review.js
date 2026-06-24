import {
    analyzeImage,
    createImageAnnotation,
    deleteImage,
    deleteImageAnnotation,
    getImage,
    listImages,
    primeChatContext,
    showToast,
    updateImageAnnotation,
    uploadImage,
} from '../api.js';
import { modal } from '../lib/modal.js';
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

function formatBytes(bytes = 0) {
    const value = Number(bytes);
    if (!Number.isFinite(value) || value <= 0) return '0 B';
    if (value < 1024) return `${value} B`;
    if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`;
    return `${(value / (1024 * 1024)).toFixed(1)} MB`;
}

function severityTone(severity = '') {
    const normalized = String(severity || '').toLowerCase();
    if (normalized === 'severe' || normalized === 'critical') return 'critical';
    if (normalized === 'mild' || normalized === 'moderate' || normalized === 'warning') return 'warning';
    return 'normal';
}

function formatStatus(status = '') {
    const normalized = String(status || '').toLowerCase();
    if (['ai_generated', 'clinician_reviewed', 'corrected', 'completed'].includes(normalized)) return 'ready';
    if (normalized === 'failed') return 'error';
    if (normalized === 'analyzing') return 'processing';
    if (normalized === 'pending') return 'queued';
    if (normalized === 'uploaded') return 'uploaded';
    return normalized || 'queued';
}

function friendlyAnalysisMessage(message = '') {
    const raw = String(message || '').trim();
    if (!raw) return '';
    const lowered = raw.toLowerCase();
    const transportMarkers = [
        'tcptransport',
        'handler is closed',
        'connection closed',
        'remote protocol',
        'readerror',
        'connecterror',
        'timeout',
    ];
    if (transportMarkers.some((marker) => lowered.includes(marker))) {
        return 'The vision model connection closed before analysis completed. Check the API key/network connection and try analysis again.';
    }
    return raw;
}

class ImagingReview extends HTMLElement {
    constructor() {
        super();
        this.loading = true;
        this.error = '';
        this.dragActive = false;
        this.images = [];
        this.selectedImageId = '';
        this.uploadingItem = null;
        this.analyzingIds = new Set();
        this.analysisPollers = new Map();
        this.deletingImageIds = new Set();
        this.editingAnnotationId = '';
        this.pendingDeleteImageId = '';
    }

    async connectedCallback() {
        this.clearModalArtifacts();
        this.renderLoading();
        try {
            await this.loadImages();
            this.images.forEach((image) => {
                const status = formatStatus(image.analysis_status);
                if (['queued', 'processing'].includes(status)) {
                    this.startAnalysisPolling(String(image.id));
                }
            });
            this.loading = false;
            this.render();
            this.setupEvents();
        } catch (error) {
            this.error = error.message || 'Unable to load medical images.';
            this.render();
            this.setupEvents();
        }
    }

    disconnectedCallback() {
        this.analysisPollers.forEach((timer) => window.clearTimeout(timer));
        this.analysisPollers.clear();
    }

    async loadImages() {
        const response = await listImages();
        this.images = Array.isArray(response?.images) ? response.images : [];
        if (!this.selectedImageId && this.images.length) {
            this.selectedImageId = String(this.images[0].id);
        }
    }

    renderLoading() {
        this.innerHTML = `
            <section class="docs-view images-view">
                <header class="page-header">
                    <div>
                        <div class="eyebrow">Imaging Review</div>
                        <h1 class="page-title">Loading Image Workspace</h1>
                        <p class="page-subtitle">Fetching uploaded studies, thumbnails, and analysis states...</p>
                    </div>
                </header>
                <div class="skeleton" style="height: 180px; margin-top:20px;"></div>
            </section>
        `;
    }

    getSelectedImage() {
        return this.images.find((image) => String(image.id) === String(this.selectedImageId)) || null;
    }

    clearModalArtifacts() {
        modal.forceClose?.();
        const root = document.getElementById('global-modal-root');
        if (root) root.innerHTML = '';
        document.body.classList.remove('modal-open');
    }

    renderUploadZone() {
        return `
            <section class="docs-toolbar docs-toolbar--images">
                <button type="button" id="image-upload-zone" class="upload-zone ${this.dragActive ? 'is-dragover' : ''}">
                    <div class="upload-zone__icon">IMG</div>
                    <div class="upload-zone__title">Upload Medical Scans</div>
                    <div class="upload-zone__subtitle">Drop PNG, JPEG, or DICOM studies. Click to select files.</div>
                </button>
                <section class="glass-panel images-upload-summary">
                    <div class="eyebrow">Upload Queue</div>
                    ${this.uploadingItem ? `
                        <div class="images-upload-summary__item">
                            <div class="images-upload-summary__title">${escapeHtml(this.uploadingItem.name)}</div>
                            <div class="progress-track"><div class="progress-fill" style="width:${this.uploadingItem.progress}%"></div></div>
                        </div>
                    ` : '<div class="empty-inline">No active uploads.</div>'}
                </section>
            </section>
        `;
    }

    renderGrid() {
        if (!this.images.length) {
            return `
                <section class="empty-state">
                    <div class="empty-state__icon">XR</div>
                    <h2 class="empty-state__title">No Images Reviewed</h2>
                    <p class="empty-state__body">Upload a case study or chest X-ray to start the analysis pipeline.</p>
                </section>
            `;
        }

        return `
            <section class="image-grid">
                ${this.images.map((image) => {
                    const imageId = String(image.id);
                    const selected = imageId === String(this.selectedImageId);
                    const status = formatStatus(image.analysis_status);
                    const name = image.original_filename || image.filename || 'Medical scan';
                    const preview = image.thumbnail_url || image.image_url;
                    const confirmingDelete = this.pendingDeleteImageId === imageId;
                    const deleting = this.deletingImageIds.has(imageId);
                    return `
                        <article class="document-card image-card ${selected ? 'is-selected' : ''} ${confirmingDelete ? 'is-confirming-delete' : ''}" data-image-card="${escapeAttr(imageId)}">
                            <div class="image-card__preview">
                                ${preview ? `<img src="${escapeAttr(preview)}" alt="${escapeAttr(name)} preview" />` : '<div class="image-card__placeholder">IMG</div>'}
                                <span class="status-badge status-badge--${escapeAttr(status)}">${escapeHtml(status)}</span>
                            </div>
                            <div class="image-card__body">
                                <div class="document-card__copy">
                                    <div class="document-card__title" title="${escapeAttr(name)}">${escapeHtml(name)}</div>
                                    <div class="document-card__meta">${escapeHtml([formatBytes(image.file_size), image.modality].filter(Boolean).join(' · '))}</div>
                                </div>
                                <div class="image-card__actions">
                                    <button type="button" class="button button--secondary" data-card-chat-image="${escapeAttr(imageId)}" ${deleting ? 'disabled' : ''}>Use</button>
                                    <button type="button" class="button button--ghost image-card__delete ${confirmingDelete ? 'is-confirming' : ''}" data-card-delete-image="${escapeAttr(imageId)}" ${deleting ? 'disabled' : ''}>
                                        ${deleting ? 'Deleting...' : confirmingDelete ? 'Confirm' : 'Delete'}
                                    </button>
                                </div>
                            </div>
                        </article>
                    `;
                }).join('')}
            </section>
        `;
    }

    renderAnnotationOverlay(image) {
        if (!Array.isArray(image.annotations) || !image.annotations.length) return '';
        return `
            <div class="image-detail__overlay" style="position: absolute; inset:0; pointer-events: none;">
                ${image.annotations.map((annotation) => {
                    const geometry = annotation.geometry || {};
                    if (annotation.annotation_type !== 'bbox') return '';
                    const left = Number(geometry.x || 0) * 100;
                    const top = Number(geometry.y || 0) * 100;
                    const width = Number(geometry.width || 0) * 100;
                    const height = Number(geometry.height || 0) * 100;
                    return `
                        <div class="image-annotation-box" style="position:absolute; left:${left}%; top:${top}%; width:${width}%; height:${height}%; border: 2px solid ${escapeAttr(annotation.color || '#ef4444')}; box-sizing:border-box;">
                            <span class="image-annotation-box__label" style="position:absolute; top:-20px; left:0; background:${escapeAttr(annotation.color || '#ef4444')}; color:#fff; font-size:10px; padding:2px 4px; border-radius:4px; white-space:nowrap;">
                                ${escapeHtml(annotation.label || 'Finding')}
                            </span>
                        </div>
                    `;
                }).join('')}
            </div>
        `;
    }

    renderFindings(image) {
        const findings = Array.isArray(image.analysis_result?.findings) ? image.analysis_result.findings : [];
        if (!findings.length) return '<div class="empty-inline">No automated findings reported.</div>';

        return findings.map((finding) => {
            const tone = severityTone(finding.severity);
            const confidence = Math.max(0, Math.min(100, Math.round(Number(finding.confidence || 0) * 100)));
            return `
                <article class="image-finding image-finding--${escapeAttr(tone)}">
                    <div class="image-finding__top">
                        <div>
                            <div class="image-finding__title">${escapeHtml(finding.description || 'Finding')}</div>
                            <div class="image-finding__meta">${escapeHtml(finding.location || 'Location not specified')}</div>
                        </div>
                        <span class="status-badge status-badge--${escapeAttr(tone === 'critical' ? 'error' : tone === 'warning' ? 'processing' : 'ready')}">${escapeHtml(tone)}</span>
                    </div>
                    <div class="image-finding__confidence">
                        <div class="progress-track"><div class="progress-fill" style="width:${confidence}%"></div></div>
                        <div class="image-finding__score">${confidence}% confidence</div>
                    </div>
                </article>
            `;
        }).join('');
    }

    getEditingAnnotation(image) {
        if (!this.editingAnnotationId) return null;
        return (image.annotations || []).find((annotation) => String(annotation.id) === String(this.editingAnnotationId)) || null;
    }

    renderAnnotationManager(image) {
        const annotations = Array.isArray(image.annotations) ? image.annotations : [];
        const editing = this.getEditingAnnotation(image);
        const geometry = editing?.geometry || {};
        const formValue = (key, fallback = '') => {
            const raw = geometry[key];
            if (raw === undefined || raw === null) return fallback;
            return Math.round(Number(raw) * 100);
        };
        return `
            <section class="image-detail__section image-annotation-manager" style="margin-top:24px;">
                <div class="image-annotation-manager__header flex-row" style="justify-content:space-between;">
                    <div>
                        <div class="field-label">Clinician Annotations</div>
                        <p class="image-annotation-manager__copy" style="font-size:12px;color:var(--text-muted);">Inspect or manually edit finding coordinates.</p>
                    </div>
                    ${editing ? '<span class="status-badge status-badge--processing">Editing</span>' : '<span class="status-badge status-badge--ready">Ready</span>'}
                </div>
                <form id="annotation-form" class="annotation-form" style="display:flex; flex-direction:column; gap:12px; margin-top:12px;">
                    <input type="hidden" id="annotation-editing-id" value="${escapeAttr(this.editingAnnotationId)}" />
                    <label class="field">
                        <span class="field-label">Label</span>
                        <input id="annotation-label" class="field-input" value="${escapeAttr(editing?.label || '')}" placeholder="e.g. nodule, effusion" />
                    </label>
                    <label class="field">
                        <span class="field-label">Description</span>
                        <input id="annotation-description" class="field-input" value="${escapeAttr(editing?.description || '')}" placeholder="Clinical notes..." />
                    </label>
                    <div class="annotation-form__grid" style="display:grid; grid-template-columns: repeat(4, 1fr); gap:8px;">
                        <label class="field">
                            <span class="field-label">X %</span>
                            <input id="annotation-x" class="field-input" type="number" min="0" max="100" value="${escapeAttr(formValue('x', 10))}" />
                        </label>
                        <label class="field">
                            <span class="field-label">Y %</span>
                            <input id="annotation-y" class="field-input" type="number" min="0" max="100" value="${escapeAttr(formValue('y', 10))}" />
                        </label>
                        <label class="field">
                            <span class="field-label">Width %</span>
                            <input id="annotation-width" class="field-input" type="number" min="1" max="100" value="${escapeAttr(formValue('width', 20))}" />
                        </label>
                        <label class="field">
                            <span class="field-label">Height %</span>
                            <input id="annotation-height" class="field-input" type="number" min="1" max="100" value="${escapeAttr(formValue('height', 20))}" />
                        </label>
                    </div>
                    <div class="annotation-form__actions flex-row" style="gap:8px;">
                        <button type="submit" class="button button--primary" style="flex:1;">${editing ? 'Save Correction' : 'Add Annotation'}</button>
                        ${editing ? '<button type="button" id="cancel-annotation-edit" class="button button--ghost">Cancel</button>' : ''}
                    </div>
                </form>
                <div class="annotation-list" style="margin-top:16px; display:flex; flex-direction:column; gap:8px;">
                    ${annotations.map((annotation) => `
                        <article class="annotation-list__item image-annotation-row">
                            <div class="annotation-list__copy">
                                <strong class="annotation-list__title">${escapeHtml(annotation.label)}</strong>
                                <div class="annotation-list__description">${escapeHtml(annotation.description || 'No description')}</div>
                            </div>
                            <div class="annotation-list__actions flex-row" style="gap:6px;">
                                <button type="button" class="button button--secondary" data-edit-annotation="${escapeAttr(annotation.id)}" style="min-height:28px; padding:0 8px; font-size:11px;">Edit</button>
                                <button type="button" class="button button--ghost" data-delete-annotation="${escapeAttr(annotation.id)}" style="min-height:28px; padding:0 8px; font-size:11px;">×</button>
                            </div>
                        </article>
                    `).join('')}
                </div>
            </section>
        `;
    }

    renderDetailPanel() {
        const image = this.getSelectedImage();
        if (!image) return '';

        const analyzing = this.analyzingIds.has(String(image.id)) || image.analysis_status === 'analyzing';
        const analysisReady = ['ready', 'clinician_reviewed', 'corrected', 'ai_generated', 'completed'].includes(formatStatus(image.analysis_status));
        const analyzeLabel = analysisReady ? 'Re-run AI Analysis' : 'Run AI Analysis';
        const analysisHint = analyzing
            ? 'Analysis is running. Findings will appear here when the vision model returns a result.'
            : friendlyAnalysisMessage(image.last_error || image.analysis_result?.error)
                || 'Review modality and run visual models.';
        const imageId = String(image.id);
        const confirmingDelete = this.pendingDeleteImageId === imageId;
        const deleting = this.deletingImageIds.has(imageId);

        return `
            <section class="glass-panel image-detail" style="margin-top:24px;">
                <div class="image-detail__header flex-row" style="justify-content:space-between; flex-wrap:wrap; gap:16px;">
                    <div>
                        <div class="eyebrow">Interactive Viewer</div>
                        <h2 class="page-title page-title--compact">${escapeHtml(image.original_filename || image.filename)}</h2>
                        <p class="page-subtitle">${escapeHtml(analysisHint)}</p>
                    </div>
                    <div class="image-detail__actions flex-row" style="gap:8px;">
                        <button type="button" class="button button--secondary" id="image-workspace-chat-btn" data-chat-image="${escapeAttr(String(image.id))}">Attach to Chat</button>
                        <button type="button" class="button button--primary" data-reanalyze-image="${escapeAttr(String(image.id))}" ${analyzing || !image.analysis_available ? 'disabled' : ''}>
                            ${analyzing ? 'Running Analysis...' : analyzeLabel}
                        </button>
                        <button type="button" class="button button--ghost image-card__delete ${confirmingDelete ? 'is-confirming' : ''}" data-delete-image="${escapeAttr(imageId)}" ${deleting ? 'disabled' : ''}>
                            ${deleting ? 'Deleting...' : confirmingDelete ? 'Confirm delete' : 'Delete study'}
                        </button>
                    </div>
                </div>
                
                <div class="image-detail__layout" style="display:grid; grid-template-columns: 1fr 340px; gap:20px; margin-top:20px;">
                    <div class="image-detail__viewer" style="position:relative; background:#000; border-radius:18px; overflow:hidden; min-height:400px; display:grid; place-items:center;">
                        ${image.image_url ? `
                            <div class="image-detail__frame" style="position:relative; display:inline-block;">
                                <img src="${escapeAttr(image.image_url)}" alt="Scan" style="max-height:550px; display:block; margin:auto;" />
                                ${this.renderAnnotationOverlay(image)}
                            </div>
                        ` : '<div class="empty-inline">Imaging frame payload empty.</div>'}
                    </div>

                    <div class="image-detail__insights" style="max-height:600px; overflow-y:auto; padding-right:8px;">
                        <section class="image-detail__section">
                            <div class="field-label">Findings</div>
                            ${this.renderFindings(image)}
                        </section>
                        <section class="image-detail__section" style="margin-top:16px;">
                            <div class="field-label">AI Recommendations</div>
                            ${(image.analysis_result?.recommendations || []).map(r => `<div style="font-size:13px; margin-top:6px; padding:6px 10px; background:rgba(255,255,255,0.03); border-radius:6px;">${escapeHtml(r)}</div>`).join('') || '<div class="empty-inline">No automated recommendations.</div>'}
                        </section>
                        ${this.renderAnnotationManager(image)}
                    </div>
                </div>
            </section>
        `;
    }

    render() {
        if (this.loading) {
            this.renderLoading();
            return;
        }

        this.innerHTML = `
            <section class="docs-view images-view">
                <header class="page-header">
                    <div>
                        <div class="eyebrow">Clinical Diagnostics</div>
                        <h1 class="page-title">Imaging Review</h1>
                        <p class="page-subtitle">Interactive visual workspace. Annotate lung zones, review AI bounding box detections, and send findings to case threads.</p>
                    </div>
                </header>
                ${this.renderUploadZone()}
                ${this.renderGrid()}
                ${this.renderDetailPanel()}
                <input id="image-upload-input" type="file" accept="image/png,image/jpeg,image/webp,.dcm,.dicom" hidden />
            </section>
        `;
    }

    async attachImageToChat(imageId) {
        const image = this.images.find((item) => String(item.id) === String(imageId));
        if (!image) return;
        this.pendingDeleteImageId = '';
        primeChatContext({
            attachment: {
                id: image.id,
                name: image.original_filename || image.filename,
                type: 'image',
                size: image.file_size,
                previewUrl: image.thumbnail_url || image.image_url || null,
                imageUrl: image.image_url || null,
            },
            draft: `Reviewing scan findings for ${image.original_filename || image.filename}:`,
            resetSession: true,
        });
        await navigate('/workspace');
        showToast('Scan attached to fresh case workspace.', 'success');
    }

    async deleteImageById(imageId) {
        if (!imageId) return;
        this.clearModalArtifacts();
        if (this.pendingDeleteImageId !== String(imageId)) {
            this.pendingDeleteImageId = String(imageId);
            this.render();
            this.setupEvents();
            return;
        }

        this.deletingImageIds.add(String(imageId));
        const poller = this.analysisPollers.get(String(imageId));
        if (poller) window.clearTimeout(poller);
        this.analysisPollers.delete(String(imageId));
        this.render();
        this.setupEvents();
        try {
            await deleteImage(imageId);
            this.images = this.images.filter((image) => String(image.id) !== String(imageId));
            if (String(this.selectedImageId) === String(imageId)) {
                this.selectedImageId = this.images[0] ? String(this.images[0].id) : '';
            }
            this.pendingDeleteImageId = '';
            this.render();
            this.setupEvents();
            showToast('Scan deleted.', 'success');
        } catch (error) {
            showToast('Delete failed.', 'error');
        } finally {
            this.deletingImageIds.delete(String(imageId));
            this.clearModalArtifacts();
            this.render();
            this.setupEvents();
        }
    }

    startAnalysisPolling(imageId) {
        const normalizedId = String(imageId);
        if (!normalizedId || this.analysisPollers.has(normalizedId)) return;
        this.analyzingIds.add(normalizedId);

        const poll = async () => {
            try {
                const refreshed = await getImage(normalizedId);
                this.images = this.images.map((item) => String(item.id) === normalizedId ? refreshed : item);
                const status = formatStatus(refreshed.analysis_status);
                if (['queued', 'processing'].includes(status)) {
                    const timer = window.setTimeout(poll, 2500);
                    this.analysisPollers.set(normalizedId, timer);
                } else {
                    this.analysisPollers.delete(normalizedId);
                    this.analyzingIds.delete(normalizedId);
                    if (status === 'error') {
                        showToast(friendlyAnalysisMessage(refreshed.last_error || refreshed.analysis_result?.error) || 'AI analysis failed.', 'error');
                    } else {
                        showToast('AI analysis completed.', 'success');
                    }
                }
                this.render();
                this.setupEvents();
            } catch (_) {
                this.analysisPollers.delete(normalizedId);
                this.analyzingIds.delete(normalizedId);
                this.render();
                this.setupEvents();
            }
        };

        const timer = window.setTimeout(poll, 2500);
        this.analysisPollers.set(normalizedId, timer);
    }

    setupEvents() {
        this.clearModalArtifacts();
        const uploadZone = this.querySelector('#image-upload-zone');
        const uploadInput = this.querySelector('#image-upload-input');

        uploadZone?.addEventListener('click', () => uploadInput?.click());
        uploadInput?.addEventListener('change', async () => {
            const file = uploadInput.files?.[0];
            if (file) await this.handleUpload(file);
            uploadInput.value = '';
        });

        this.querySelectorAll('[data-image-card]').forEach((card) => {
            card.addEventListener('click', () => {
                this.selectedImageId = card.getAttribute('data-image-card') || '';
                this.editingAnnotationId = '';
                this.render();
                this.setupEvents();
            });
        });

        this.querySelectorAll('[data-card-chat-image]').forEach((button) => {
            button.addEventListener('click', async (event) => {
                event.stopPropagation();
                await this.attachImageToChat(button.getAttribute('data-card-chat-image') || '');
            });
        });

        this.querySelectorAll('[data-card-delete-image]').forEach((button) => {
            button.addEventListener('click', async (event) => {
                event.stopPropagation();
                await this.deleteImageById(button.getAttribute('data-card-delete-image') || '');
            });
        });

        this.querySelectorAll('[data-reanalyze-image]').forEach((button) => {
            button.addEventListener('click', async () => {
                await this.runAnalysis(button.getAttribute('data-reanalyze-image') || '');
            });
        });

        this.querySelector('#image-workspace-chat-btn')?.addEventListener('click', async () => {
            const image = this.getSelectedImage();
            if (!image) return;
            await this.attachImageToChat(image.id);
        });

        this.querySelectorAll('[data-delete-image]').forEach((button) => {
            button.addEventListener('click', async (event) => {
                event.stopPropagation();
                await this.deleteImageById(button.getAttribute('data-delete-image') || '');
            });
        });

        const annotationForm = this.querySelector('#annotation-form');
        annotationForm?.addEventListener('submit', async (event) => {
            event.preventDefault();
            await this.saveAnnotation();
        });

        const cancelAnnotationEdit = this.querySelector('#cancel-annotation-edit');
        cancelAnnotationEdit?.addEventListener('click', () => {
            this.editingAnnotationId = '';
            this.render();
            this.setupEvents();
        });

        this.querySelectorAll('[data-edit-annotation]').forEach((button) => {
            button.addEventListener('click', () => {
                this.editingAnnotationId = button.getAttribute('data-edit-annotation') || '';
                this.render();
                this.setupEvents();
            });
        });

        this.querySelectorAll('[data-delete-annotation]').forEach((button) => {
            button.addEventListener('click', async () => {
                await this.removeAnnotation(button.getAttribute('data-delete-annotation') || '');
            });
        });
    }

    readAnnotationForm() {
        const label = this.querySelector('#annotation-label')?.value.trim() || '';
        if (!label) {
            showToast('Provide an annotation label.', 'warning');
            return null;
        }
        const toRatio = (selector, fallback) => {
            const value = Number(this.querySelector(selector)?.value || fallback);
            return Math.max(0, Math.min(1, value / 100));
        };
        return {
            annotation_type: 'bbox',
            label,
            description: this.querySelector('#annotation-description')?.value.trim() || null,
            color: '#ef4444',
            geometry: {
                x: toRatio('#annotation-x', 10),
                y: toRatio('#annotation-y', 10),
                width: toRatio('#annotation-width', 20),
                height: toRatio('#annotation-height', 20),
            },
            source: 'user',
        };
    }

    async saveAnnotation() {
        const image = this.getSelectedImage();
        if (!image?.id) return;
        const payload = this.readAnnotationForm();
        if (!payload) return;
        try {
            if (this.editingAnnotationId) {
                await updateImageAnnotation(image.id, this.editingAnnotationId, payload);
                showToast('Annotation saved.', 'success');
            } else {
                await createImageAnnotation(image.id, payload);
                showToast('Annotation added.', 'success');
            }
            const refreshed = await getImage(image.id);
            this.images = this.images.map((item) => String(item.id) === String(image.id) ? refreshed : item);
            this.editingAnnotationId = '';
            this.render();
            this.setupEvents();
        } catch (error) {
            showToast('Failed to save annotation.', 'error');
        }
    }

    async removeAnnotation(annotationId) {
        const image = this.getSelectedImage();
        if (!image?.id || !annotationId) return;
        try {
            await deleteImageAnnotation(image.id, annotationId);
            const refreshed = await getImage(image.id);
            this.images = this.images.map((item) => String(item.id) === String(image.id) ? refreshed : item);
            if (String(this.editingAnnotationId) === String(annotationId)) this.editingAnnotationId = '';
            this.render();
            this.setupEvents();
            showToast('Annotation deleted.', 'success');
        } catch (error) {
            showToast('Failed to delete annotation.', 'error');
        }
    }

    async handleUpload(file) {
        this.uploadingItem = { name: file.name, progress: 0 };
        this.render();
        this.setupEvents();
        try {
            const uploaded = await uploadImage(file, (progress) => {
                this.uploadingItem = { ...this.uploadingItem, progress };
                this.render();
                this.setupEvents();
            });
            await this.loadImages();
            this.uploadingItem = null;
            this.selectedImageId = String(uploaded.id);
            this.render();
            this.setupEvents();
            showToast('Scan uploaded.', 'success');
            if (uploaded.analysis_available && uploaded.auto_analysis_enabled) {
                await this.runAnalysis(String(uploaded.id));
            }
        } catch (err) {
            this.uploadingItem = null;
            this.render();
            this.setupEvents();
            showToast('Upload failed.', 'error');
        }
    }

    async runAnalysis(imageId) {
        if (!imageId) return;
        const image = this.images.find((item) => String(item.id) === String(imageId));
        if (image) {
            image.analysis_status = 'analyzing';
        }
        this.analyzingIds.add(String(imageId));
        this.render();
        this.setupEvents();
        try {
            await analyzeImage(imageId, '');
            const refreshed = await getImage(imageId);
            this.images = this.images.map((item) => String(item.id) === String(imageId) ? refreshed : item);
            const status = formatStatus(refreshed.analysis_status);
            if (['queued', 'processing'].includes(status)) {
                this.startAnalysisPolling(String(imageId));
            } else if (status === 'error') {
                this.analyzingIds.delete(String(imageId));
                showToast(friendlyAnalysisMessage(refreshed.last_error || refreshed.analysis_result?.error) || 'AI analysis failed.', 'error');
            } else {
                this.analyzingIds.delete(String(imageId));
                showToast('AI analysis completed.', 'success');
            }
        } catch (err) {
            this.analyzingIds.delete(String(imageId));
            showToast(friendlyAnalysisMessage(err.message) || 'AI analysis failed.', 'error');
        } finally {
            this.render();
            this.setupEvents();
        }
    }
}

customElements.define('imaging-review', ImagingReview);
export default ImagingReview;
