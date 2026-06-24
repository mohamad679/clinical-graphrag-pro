import {
    CHAT_ATTACHMENT_STORAGE_KEY,
    CHAT_DRAFT_STORAGE_KEY,
    CHAT_SESSION_PAYLOAD_KEY,
    generateSoapNote,
    getDetailedHealth,
    getDocumentStatus,
    getChatSession,
    listDocuments,
    listImages,
    showToast,
    streamChat,
    submitFeedback,
    transcribeAudio,
    uploadDocument,
    uploadImage,
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

function escapeAttr(value = '') {
    return escapeHtml(value).replace(/`/g, '&#96;');
}

function formatBytes(bytes = 0) {
    const value = Number(bytes);
    if (!Number.isFinite(value) || value <= 0) return '';
    if (value < 1024) return `${value} B`;
    if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`;
    return `${(value / (1024 * 1024)).toFixed(1)} MB`;
}

function sanitizeUrl(raw = '') {
    const trimmed = String(raw || '').trim();
    if (!trimmed) return '#';
    if (trimmed.startsWith('/') || trimmed.startsWith('#')) return trimmed;
    try {
        const parsed = new URL(trimmed, window.location.origin);
        return ['http:', 'https:', 'mailto:', 'blob:'].includes(parsed.protocol) ? parsed.href : '#';
    } catch (_) {
        return '#';
    }
}

function renderMath(raw = '', displayMode = false) {
    const source = String(raw || '').trim();
    if (!source) return '';
    if (window.katex?.renderToString) {
        try {
            return window.katex.renderToString(source, {
                displayMode,
                throwOnError: false,
                strict: 'ignore',
            });
        } catch (_) {
            return `<span class="${displayMode ? 'math-block' : 'math-inline'}">${escapeHtml(source)}</span>`;
        }
    }
    return `<span class="${displayMode ? 'math-block' : 'math-inline'}">${escapeHtml(source)}</span>`;
}

function renderCodeBlock(code = '', language = '') {
    const normalizedLanguage = String(language || '').trim().replace(/[^a-z0-9_+-]/gi, '').slice(0, 32);
    const rawCode = String(code || '').replace(/\n+$/g, '');
    let rendered = escapeHtml(rawCode);

    if (window.hljs && rawCode) {
        try {
            rendered = normalizedLanguage
                ? window.hljs.highlight(rawCode, { language: normalizedLanguage, ignoreIllegals: true }).value
                : window.hljs.highlightAuto(rawCode).value;
        } catch (_) {
            rendered = escapeHtml(rawCode);
        }
    }

    return `
        <div class="md-code-shell">
            <div class="md-code-toolbar">
                <span>${escapeHtml(normalizedLanguage || 'code')}</span>
                <button type="button" class="md-code-copy" data-copy-code="${escapeAttr(rawCode)}">Copy</button>
            </div>
            <pre class="md-code"><code class="${normalizedLanguage ? `language-${escapeAttr(normalizedLanguage)}` : ''}">${rendered}</code></pre>
        </div>
    `;
}

function renderImage(url = '', alt = 'Generated image') {
    const safeUrl = sanitizeUrl(url);
    if (safeUrl === '#') return escapeHtml(url);
    return `
        <figure class="md-image-card">
            <img src="${escapeAttr(safeUrl)}" alt="${escapeAttr(alt)}" loading="lazy" />
            ${alt ? `<figcaption>${escapeHtml(alt)}</figcaption>` : ''}
        </figure>
    `;
}

function inlineMarkdown(text = '') {
    const citationPattern = /\[((?:SRC|DOC|IMG)\d+|GRAPH(?:\d+|-[A-Z]+-\d{3}))\]/g;
    let rendered = escapeHtml(text);

    rendered = rendered
        .replace(/!\[([^\]]*)\]\(([^)]+)\)/g, (_match, alt, url) => renderImage(url, alt || 'Generated image'))
        .replace(/\\\((.+?)\\\)/g, (_match, math) => renderMath(math, false))
        .replace(/\$([^$\n]+?)\$/g, (_match, math) => renderMath(math, false))
        .replace(/\*\*\*(.+?)\*\*\*/g, '<strong><em>$1</em></strong>')
        .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
        .replace(/(^|[\s(])\*(?!\s)(.+?)(?<!\s)\*/g, '$1<em>$2</em>')
        .replace(/`([^`]+)`/g, '<code>$1</code>')
        .replace(/\[([^\]]+)\]\(([^)]+)\)/g, (_match, label, url) => (
            `<a href="${escapeAttr(sanitizeUrl(url))}" target="_blank" rel="noreferrer noopener">${escapeHtml(label)}</a>`
        ))
        .replace(citationPattern, (_match, citationId) => (
            `<span class="citation-badge" data-citation="${escapeAttr(citationId)}">[${escapeHtml(citationId)}]</span>`
        ));

    return rendered;
}

function extractConfidence(text = '') {
    const match = String(text).match(/\[CONFIDENCE:\s*([\d.]+)\]/i);
    if (!match) return null;
    const score = parseFloat(match[1]);
    return Number.isFinite(score) ? Math.min(1, Math.max(0, score)) : null;
}

function stripConfidenceTag(text = '') {
    return String(text)
        .replace(/\[EVIDENCE_SUPPORT:\s*[\d.]+\]/gi, '')
        .replace(/\[CONFIDENCE:\s*[\d.]+\]/gi, '')
        .trimEnd();
}

function isAssistantErrorContent(text = '', force = false) {
    const value = stripConfidenceTag(text).trim();
    if (force) return true;
    return /^error:\s*/i.test(value)
        || /unable to complete the request safely/i.test(value)
        || /failed to send message/i.test(value)
        || /streaming error/i.test(value);
}

function cleanAssistantError(text = '') {
    const cleaned = stripConfidenceTag(text)
        .replace(/^error:\s*/i, '')
        .trim();
    if (!cleaned || /unable to complete the request safely/i.test(cleaned) || /streaming error/i.test(cleaned)) {
        return 'I could not complete this turn. Attach a ready document, image, or case source and try again. If the file was just uploaded, wait until indexing is ready.';
    }
    return cleaned || 'Unable to complete the request safely.';
}

function renderAssistantErrorNotice(text = '') {
    const message = cleanAssistantError(text);
    const lower = message.toLowerCase();
    const title = lower.includes('rate limit')
        ? 'Provider limit reached'
        : lower.includes('attach') || lower.includes('indexing') || lower.includes('source')
            ? 'Action needed'
        : lower.includes('network') || lower.includes('connection')
            ? 'Connection interrupted'
            : 'Could not complete safely';

    return `
        <div class="message-error-notice" role="status">
            <span class="message-error-dot" aria-hidden="true"></span>
            <span class="message-error-copy">
                <strong>${escapeHtml(title)}</strong>
                <span>${escapeHtml(message)}</span>
            </span>
        </div>
    `;
}

function renderConfidenceBadge(score) {
    if (score === null) return '';
    const normalizedScore = Math.min(1, Math.max(0, Number(score)));
    if (!Number.isFinite(normalizedScore)) return '';

    let level = 'low';
    let label = 'Low evidence support';
    if (normalizedScore >= 0.85) {
        level = 'high';
        label = 'High evidence support';
    } else if (normalizedScore >= 0.65) {
        level = 'medium';
        label = 'Moderate evidence support';
    }

    const percent = Math.round(normalizedScore * 100);
    return `
        <div class="confidence-badge confidence--${level}" title="Heuristic evidence-support score, not calibrated clinical confidence: ${percent}%">
            <div class="confidence-bar">
                <div class="confidence-fill" style="width:${percent}%"></div>
            </div>
            <span class="confidence-label">${label} · ${percent}%</span>
        </div>
    `;
}

function renderMarkdown(text = '') {
    const sanitized = String(text || '')
        .replace(/\[Source:.*?\]/gi, '')
        .trim();

    if (!sanitized) return '';

    const lines = sanitized.split('\n');
    const html = [];
    let inCode = false;
    let codeLanguage = '';
    let codeBuffer = [];
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
                    <thead><tr>${header.map((cell) => `<th>${inlineMarkdown(cell)}</th>`).join('')}</tr></thead>
                    <tbody>
                        ${body.map((row) => `<tr>${row.map((cell) => `<td>${inlineMarkdown(cell)}</td>`).join('')}</tr>`).join('')}
                    </tbody>
                </table>
            </div>
        `);
        tableRows = [];
    };

    lines.forEach((line) => {
        const trimmed = line.trim();

        if (trimmed.startsWith('```')) {
            flushTable();
            closeLists();
            if (inCode) {
                html.push(renderCodeBlock(codeBuffer.join('\n'), codeLanguage));
                codeBuffer = [];
                codeLanguage = '';
                inCode = false;
            } else {
                inCode = true;
                codeLanguage = trimmed.replace(/^```/, '').trim();
            }
            return;
        }

        if (inCode) {
            codeBuffer.push(line);
            return;
        }

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

        if (/^\$\$.*\$\$$/.test(trimmed)) {
            closeLists();
            html.push(`<div class="math-display">${renderMath(trimmed.replace(/^\$\$|\$\$$/g, ''), true)}</div>`);
            return;
        }

        if (/^(https?:\/\/\S+\.(?:png|jpe?g|gif|webp|svg)(?:\?\S*)?|data:image\/[a-z+.-]+;base64,[A-Za-z0-9+/=]+)$/i.test(trimmed)) {
            closeLists();
            html.push(renderImage(trimmed, 'Model generated image'));
            return;
        }

        if (trimmed.startsWith('#### ')) {
            closeLists();
            html.push(`<h4>${inlineMarkdown(trimmed.slice(5))}</h4>`);
            return;
        }
        if (trimmed.startsWith('### ')) {
            closeLists();
            html.push(`<h3>${inlineMarkdown(trimmed.slice(4))}</h3>`);
            return;
        }
        if (trimmed.startsWith('## ')) {
            closeLists();
            html.push(`<h2>${inlineMarkdown(trimmed.slice(3))}</h2>`);
            return;
        }
        if (trimmed.startsWith('# ')) {
            closeLists();
            html.push(`<h1>${inlineMarkdown(trimmed.slice(2))}</h1>`);
            return;
        }

        if (/^[-*_]{3,}$/.test(trimmed)) {
            closeLists();
            html.push('<hr />');
            return;
        }

        if (trimmed.startsWith('> ')) {
            closeLists();
            html.push(`<blockquote>${inlineMarkdown(trimmed.slice(2))}</blockquote>`);
            return;
        }

        if (/^[*-+] /.test(trimmed)) {
            if (!inUl) {
                closeLists();
                html.push('<ul>');
                inUl = true;
            }
            html.push(`<li>${inlineMarkdown(trimmed.replace(/^[*-+] /, ''))}</li>`);
            return;
        }

        if (/^\d+\. /.test(trimmed)) {
            if (!inOl) {
                closeLists();
                html.push('<ol>');
                inOl = true;
            }
            html.push(`<li>${inlineMarkdown(trimmed.replace(/^\d+\. /, ''))}</li>`);
            return;
        }

        closeLists();
        html.push(`<p>${inlineMarkdown(trimmed)}</p>`);
    });

    flushTable();
    closeLists();

    if (inCode) {
        html.push(renderCodeBlock(codeBuffer.join('\n'), codeLanguage));
    }

    return html.join('');
}

function parseSoapSections(note = '') {
    const sectionMap = {
        subjective: '',
        objective: '',
        assessment: '',
        plan: '',
    };

    let currentSection = '';
    note.split('\n').forEach((line) => {
        const normalized = line.trim().replace(/[:#*\-]/g, '').toLowerCase();
        if (normalized.startsWith('subjective') || normalized === 's') currentSection = 'subjective';
        else if (normalized.startsWith('objective') || normalized === 'o') currentSection = 'objective';
        else if (normalized.startsWith('assessment') || normalized === 'a') currentSection = 'assessment';
        else if (normalized.startsWith('plan') || normalized === 'p') currentSection = 'plan';
        else if (currentSection) sectionMap[currentSection] += `${line}\n`;
    });

    return sectionMap;
}

function formatDuration(milliseconds = 0) {
    const totalSeconds = Math.max(0, Math.floor(Number(milliseconds || 0) / 1000));
    const minutes = Math.floor(totalSeconds / 60);
    const seconds = totalSeconds % 60;
    return `${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}`;
}

function renderComposerIcon(name) {
    const icons = {
        attach: `
            <svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">
                <path d="M8.5 12.5 14.86 6.14a3.5 3.5 0 1 1 4.95 4.95l-8.13 8.13a5.5 5.5 0 1 1-7.78-7.78l8.49-8.48" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="1.8"/>
            </svg>
        `,
        mic: `
            <svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">
                <path d="M12 15a3 3 0 0 0 3-3V7a3 3 0 1 0-6 0v5a3 3 0 0 0 3 3Z" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="1.8"/>
                <path d="M19 11.5a7 7 0 0 1-14 0M12 18.5V22M8.5 22h7" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="1.8"/>
            </svg>
        `,
        stop: `
            <svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">
                <rect x="7" y="7" width="10" height="10" rx="2.4" fill="currentColor"/>
            </svg>
        `,
        send: `
            <svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">
                <path d="M20 4 9 15" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="1.8"/>
                <path d="M20 4 13 20l-4-5-5-4 16-7Z" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="1.8"/>
            </svg>
        `,
        close: `
            <svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">
                <path d="m6 6 12 12M18 6 6 18" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="1.8"/>
            </svg>
        `,
    };
    return icons[name] || '';
}

class CaseWorkspace extends HTMLElement {
    constructor() {
        super();
        this.messages = [];
        this.sessionId = '';
        this.attachedFile = null;
        this.uploadingAttachment = null;
        this.isUploading = false;
        this.isGenerating = false;
        this.expandedReasoningKeys = new Set();
        this.feedbackSelections = new Map();
        this.isAttachmentMenuOpen = false;
        this.isRecording = false;
        this.mediaRecorder = null;
        this.audioChunks = [];
        this.isSoapLoading = false;
        this.soapNote = '';
        this.isSoapPaneOpen = false;
        this.modalState = null;
        this.draftText = '';
        this.currentAnswer = '';
        this.documentAttachmentPollTimer = null;
        this.recordingStartedAt = 0;
        this.recordingElapsedMs = 0;
        this.recordingClockTimer = null;
        this.discardRecordingOnStop = false;
        this.workspaceContext = {
            loaded: false,
            documents: [],
            images: [],
            health: null,
        };
        this._listenerBindings = [];
        this.selectedCitation = null;
    }

    connectedCallback() {
        this.restoreAttachment();
        this.restoreDraft();
        this.restoreSessionPayload();
        this.resumeAttachmentPolling();
        this.render();
        this.setupEvents();
        this.loadWorkspaceContext();
    }

    async loadWorkspaceContext() {
        try {
            const [documents, images, health] = await Promise.all([
                listDocuments().catch(() => ({ documents: [] })),
                listImages().catch(() => ({ images: [] })),
                getDetailedHealth().catch(() => null),
            ]);
            this.workspaceContext = {
                loaded: true,
                documents: Array.isArray(documents?.documents) ? documents.documents : [],
                images: Array.isArray(images?.images) ? images.images : [],
                health,
            };
            this.render();
            this.setupEvents();
        } catch (_) {
            this.workspaceContext = { ...this.workspaceContext, loaded: true };
        }
    }

    disconnectedCallback() {
        this.stopAttachmentPolling();
        this.stopRecordingClock({ reset: true });
        if (this.mediaRecorder?.state && this.mediaRecorder.state !== 'inactive') {
            this.discardRecordingOnStop = true;
            this.mediaRecorder.stop();
        }
        this._cleanup();
    }

    _bindListener(node, type, handler) {
        if (!node) return;
        node.addEventListener(type, handler);
        this._listenerBindings.push({ node, type, handler });
    }

    _cleanup() {
        this._listenerBindings.forEach(({ node, type, handler }) => {
            node.removeEventListener(type, handler);
        });
        this._listenerBindings = [];
    }

    _cleanupBindingsForRoot(root) {
        this._listenerBindings = this._listenerBindings.filter(({ node, type, handler }) => {
            if (root.contains(node)) {
                node.removeEventListener(type, handler);
                return false;
            }
            return true;
        });
    }

    restoreAttachment() {
        try {
            const raw = window.sessionStorage.getItem(CHAT_ATTACHMENT_STORAGE_KEY);
            this.attachedFile = raw ? JSON.parse(raw) : null;
        } catch (_) {
            this.attachedFile = null;
        }
    }

    persistAttachment() {
        if (this.attachedFile) {
            window.sessionStorage.setItem(CHAT_ATTACHMENT_STORAGE_KEY, JSON.stringify(this.attachedFile));
        } else {
            window.sessionStorage.removeItem(CHAT_ATTACHMENT_STORAGE_KEY);
        }
    }

    restoreDraft() {
        this.draftText = window.sessionStorage.getItem(CHAT_DRAFT_STORAGE_KEY) || '';
    }

    persistDraft() {
        if (this.draftText && this.draftText.trim()) {
            window.sessionStorage.setItem(CHAT_DRAFT_STORAGE_KEY, this.draftText);
        } else {
            window.sessionStorage.removeItem(CHAT_DRAFT_STORAGE_KEY);
        }
    }

    restoreSessionPayload() {
        try {
            const rawId = window.sessionStorage.getItem('clinical_active_session_id');
            const rawPayload = window.sessionStorage.getItem(CHAT_SESSION_PAYLOAD_KEY);
            if (rawId) {
                this.sessionId = rawId;
                if (rawPayload) {
                    const payload = JSON.parse(rawPayload);
                    this.hydrateSession(payload);
                }
            } else {
                this.sessionId = '';
                this.messages = [];
            }
        } catch (_) {
            this.sessionId = '';
            this.messages = [];
        }
    }

    hydrateSession(payload) {
        this.sessionId = payload.id || '';
        this.messages = Array.isArray(payload.messages) ? payload.messages.map((item) => this.mapMessage(item)) : [];
        this.soapNote = payload.soap_note || '';
        if (this.soapNote) {
            this.isSoapPaneOpen = true;
        }
    }

    mapMessage(message) {
        let attachment = null;
        if (message.attached_document) {
            attachment = {
                id: message.attached_document.id,
                name: message.attached_document.filename,
                type: 'document',
                size: message.attached_document.file_size,
                status: message.attached_document.status,
                progress: 100,
            };
        } else if (message.attached_image) {
            attachment = {
                id: message.attached_image.id,
                name: message.attached_image.original_filename || message.attached_image.filename || 'Scans',
                type: 'image',
                previewUrl: message.attached_image.thumbnail_url || message.attached_image.image_url,
                progress: 100,
            };
        }

        return {
            id: message.id,
            role: message.role || 'user',
            content: message.content || '',
            attachment,
            sources: Array.isArray(message.sources) ? message.sources : [],
            reasoningSteps: Array.isArray(message.reasoning_steps) ? message.reasoning_steps.map((r, index) => ({
                step: r.step_number ?? index,
                title: r.title,
                description: r.description,
                status: r.status || 'done',
            })) : [],
            confidenceScore: message.heuristic_evidence_support_score ?? message.confidence_score ?? null,
            feedbackRating: message.feedback_rating ?? null,
            isError: isAssistantErrorContent(message.content || ''),
        };
    }

    isDocumentAttachmentReady(attachment = this.attachedFile) {
        if (!attachment || attachment.type !== 'document') return true;
        return String(attachment.status || '').toLowerCase() === 'ready';
    }

    isDocumentAttachmentBlocked(attachment = this.attachedFile) {
        if (!attachment || attachment.type !== 'document') return false;
        const state = String(attachment.status || '').toLowerCase();
        return ['queued', 'processing'].includes(state);
    }

    getAttachmentMeta(attachment = this.attachedFile) {
        if (!attachment) return '';
        if (attachment.type === 'document') {
            const count = attachment.chunkCount || 0;
            const sizeLabel = formatBytes(attachment.size);
            return [sizeLabel, count ? `${count} chunks` : ''].filter(Boolean).join(' · ');
        }
        if (attachment.type === 'image') {
            const dim = attachment.width && attachment.height ? `${attachment.width}x${attachment.height}` : '';
            return [dim, formatBytes(attachment.size)].filter(Boolean).join(' · ');
        }
        return '';
    }

    getDefaultAttachmentPrompt(attachment) {
        if (!attachment) return '';
        if (attachment.type === 'image') return 'Analyze this clinical image and summarize key findings.';
        return 'Summarize the attached document in clean Markdown. Include key points, clinically relevant findings, limitations, and cite each point from the document.';
    }

    isSourceDependentPrompt(message = '') {
        const normalized = String(message || '').toLowerCase();
        return /\b(summarize|summary|analy[sz]e|review|explain|outline)\b/.test(normalized)
            && /\b(it|this|that|document|paper|article|report|case|patient|file|source)\b/.test(normalized);
    }

    hasPriorSourceContext() {
        return this.messages.some((message) => (
            message.attachment
            || (Array.isArray(message.sources) && message.sources.length)
        ));
    }

    readyWorkspaceSourceCount() {
        const readyDocs = this.workspaceContext.documents.filter((doc) => String(doc.status || '').toLowerCase() === 'ready');
        const readyImages = this.workspaceContext.images.filter((img) => {
            const status = String(img.analysis_status || img.status || '').toLowerCase();
            return ['ready', 'ai_generated'].includes(status);
        });
        return readyDocs.length + readyImages.length;
    }

    upsertWorkspaceDocument(document) {
        if (!document?.id) return;
        const normalized = {
            ...document,
            filename: document.filename || document.name || 'Document',
            file_size: document.file_size ?? document.size,
            chunk_count: document.chunk_count ?? document.chunkCount ?? 0,
        };
        const current = this.workspaceContext.documents.filter((doc) => String(doc.id) !== String(normalized.id));
        this.workspaceContext = {
            ...this.workspaceContext,
            documents: [normalized, ...current],
        };
    }

    upsertWorkspaceImage(image) {
        if (!image?.id) return;
        const normalized = {
            ...image,
            original_filename: image.original_filename || image.name || image.filename || 'Image',
        };
        const current = this.workspaceContext.images.filter((img) => String(img.id) !== String(normalized.id));
        this.workspaceContext = {
            ...this.workspaceContext,
            images: [normalized, ...current],
        };
    }

    scrollToBottom() {
        const scroller = this.querySelector('#chat-scroll');
        if (scroller) {
            scroller.scrollTop = scroller.scrollHeight;
        }
    }

    _isNearBottom(element, threshold = 120) {
        return element.scrollHeight - element.scrollTop - element.clientHeight <= threshold;
    }

    resumeAttachmentPolling() {
        if (this.attachedFile?.type === 'document' && this.isDocumentAttachmentBlocked()) {
            this.scheduleAttachmentPoll(this.attachedFile.id);
        }
    }

    scheduleAttachmentPoll(documentId, delay = 2000) {
        this.stopAttachmentPolling();
        this.documentAttachmentPollTimer = window.setTimeout(async () => {
            try {
                const status = await this.pollAttachedDocumentStatus(documentId);
                if (status && ['queued', 'processing'].includes(status.status)) {
                    this.scheduleAttachmentPoll(documentId);
                }
            } catch (_) {
                this.stopAttachmentPolling();
            }
        }, delay);
    }

    stopAttachmentPolling() {
        if (this.documentAttachmentPollTimer) {
            window.clearTimeout(this.documentAttachmentPollTimer);
            this.documentAttachmentPollTimer = null;
        }
    }

    async pollAttachedDocumentStatus(documentId, { rerender = true, notify = true } = {}) {
        try {
            const response = await getDocumentStatus(documentId);
            if (this.attachedFile && String(this.attachedFile.id) === String(documentId)) {
                const updated = {
                    ...this.attachedFile,
                    status: response.status,
                    stage: response.stage || response.status,
                    progress: response.progress || 0,
                    chunkCount: response.chunk_count || 0,
                    errorMessage: response.error_message || null,
                };
                this.attachedFile = updated;
                this.persistAttachment();
                this.upsertWorkspaceDocument({
                    id: updated.id,
                    filename: updated.name,
                    file_size: updated.size,
                    status: updated.status,
                    stage: updated.stage,
                    chunk_count: updated.chunkCount,
                });

                if (rerender) {
                    this.render();
                    this.setupEvents();
                }

                if (response.status === 'ready' && notify) {
                    showToast('Attached document is indexed and ready to query.', 'success', 2500);
                } else if (response.status === 'error' && notify) {
                    showToast(response.error_message || 'Indexing failed.', 'error');
                }
            }
            return response;
        } catch (error) {
            console.error('Failed to poll document status', error);
            return null;
        }
    }

    async handleSubmit() {
        if (this.isGenerating) return;
        const input = this.querySelector('#chat-input');
        const draft = this.draftText.trim();
        if (!draft && !this.attachedFile) return;

        const currentAttachment = this.attachedFile;
        if (!currentAttachment && this.isSourceDependentPrompt(draft) && !this.hasPriorSourceContext()) {
            const message = this.readyWorkspaceSourceCount()
                ? 'Attach the document, image, or source first, then ask to summarize it.'
                : 'Upload or attach a ready source before asking to summarize it.';
            showToast(message, 'warning', 3600);
            return;
        }
        if (currentAttachment?.type === 'document' && currentAttachment.id) {
            const latestStatus = await this.pollAttachedDocumentStatus(currentAttachment.id, { rerender: false, notify: false });
            const normalizedStatus = String(latestStatus?.status || currentAttachment.status || '').toLowerCase();
            const stageKnown = Boolean(latestStatus?.stage || currentAttachment.stage);
            const normalizedStage = String(latestStatus?.stage || currentAttachment.stage || '').toLowerCase();
            const progress = latestStatus?.progress ?? currentAttachment.progress ?? 0;
            if (normalizedStatus === 'error') {
                showToast(latestStatus?.error_message || currentAttachment.errorMessage || 'This document failed to process.', 'error');
                this.render();
                this.setupEvents();
                return;
            }
            if (normalizedStatus !== 'ready' || (stageKnown && normalizedStage !== 'ready')) {
                const stageLabel = normalizedStage || normalizedStatus || 'processing';
                showToast(`This document is still indexing (${stageLabel}, ${progress}% complete). Please wait until it is ready.`, 'warning');
                this.render();
                this.setupEvents();
                return;
            }
        }
        const requestMessage = draft || this.getDefaultAttachmentPrompt(currentAttachment);
        const userMessage = {
            role: 'user',
            content: draft || this.getDefaultAttachmentPrompt(currentAttachment),
            attachment: currentAttachment,
            sources: [],
            reasoningSteps: [],
            feedbackRating: null,
        };
        const assistantMessage = {
            id: null,
            role: 'assistant',
            content: '',
            sources: [],
            reasoningSteps: [],
            confidenceScore: null,
            feedbackRating: null,
            isError: false,
        };

        this.messages = [...this.messages, userMessage, assistantMessage];
        const assistantIndex = this.messages.length - 1;
        this.stopAttachmentPolling();
        this.attachedFile = null;
        this.persistAttachment();
        this.isGenerating = true;
        this.currentAnswer = '';
        this.draftText = '';
        this.persistDraft();
        if (input) {
            input.value = '';
            input.style.height = 'auto';
        }
        this.render();
        this.setupEvents();

        await streamChat({
            message: requestMessage,
            sessionId: this.sessionId || null,
            attachedDocumentId: currentAttachment?.type === 'document' ? currentAttachment.id : null,
            attachedImageId: currentAttachment?.type === 'image' ? currentAttachment.id : null,
            onToken: (chunk) => {
                const scroller = this.querySelector('#chat-scroll');
                const shouldScroll = !scroller || this._isNearBottom(scroller);
                this.currentAnswer += chunk;
                this.messages[assistantIndex].content += chunk;
                this.updateStreamingMessage(assistantIndex, shouldScroll);
            },
            onReasoning: (step) => {
                const message = this.messages[assistantIndex];
                const existing = message.reasoningSteps.findIndex((item) => item.step === step.step && item.title === step.title);
                if (existing >= 0) message.reasoningSteps[existing] = step;
                else message.reasoningSteps.push(step);
                this.expandedReasoningKeys.add(assistantIndex);
                this.updateStreamingMessage(assistantIndex);
            },
            onSources: (sources) => {
                this.messages[assistantIndex].sources = Array.isArray(sources) ? sources : [];
                this.updateStreamingMessage(assistantIndex);
            },
            onDone: async ({ session_id }) => {
                this.finalizeStreamingConfidence(assistantIndex);
                this.sessionId = session_id || this.sessionId;
                await this.syncSessionFromServer(assistantIndex);
                this.isGenerating = false;
                this.currentAnswer = '';
                this.render();
                this.setupEvents();
                window.dispatchEvent(new CustomEvent('clinical:sessions-changed', { detail: { sessionId: this.sessionId } }));
            },
            onError: (error) => {
                this.messages[assistantIndex].content = cleanAssistantError(error.message || 'Unable to complete the request safely.');
                this.messages[assistantIndex].isError = true;
                this.isGenerating = false;
                this.currentAnswer = '';
                this.render();
                this.setupEvents();
                showToast(cleanAssistantError(error.message || 'Unable to complete the request safely.'), 'error');
            },
        });
    }

    async syncSessionFromServer(assistantIndex) {
        if (!this.sessionId) return;
        try {
            const payload = await getChatSession(this.sessionId);
            const localAssistant = this.messages[assistantIndex];
            this.messages = payload.messages.map((message) => this.mapMessage(message));
            const latestAssistant = [...this.messages].reverse().find((message) => message.role === 'assistant');
            if (latestAssistant && (!latestAssistant.reasoningSteps?.length) && localAssistant?.reasoningSteps?.length) {
                latestAssistant.reasoningSteps = localAssistant.reasoningSteps;
            }
            if (latestAssistant && latestAssistant.confidenceScore == null && localAssistant?.confidenceScore != null) {
                latestAssistant.confidenceScore = localAssistant.confidenceScore;
            }
            window.sessionStorage.setItem(CHAT_SESSION_PAYLOAD_KEY, JSON.stringify(payload));
        } catch (_) {
            // Keep local state if the persistence sync fails.
        }
    }

    bindDynamicMessageControls(root) {
        if (!root) return;

        root.querySelectorAll('[data-toggle-reasoning]').forEach((btn) => {
            this._bindListener(btn, 'click', () => {
                const idx = parseInt(btn.getAttribute('data-toggle-reasoning'), 10);
                if (!Number.isFinite(idx)) return;
                if (this.expandedReasoningKeys.has(idx)) {
                    this.expandedReasoningKeys.delete(idx);
                } else {
                    this.expandedReasoningKeys.add(idx);
                }
                this.updateStreamingMessage(idx, false);
            });
        });

        root.querySelectorAll('[data-open-source]').forEach((btn) => {
            this._bindListener(btn, 'click', () => {
                const [messageIndexRaw, sourceIndexRaw] = String(btn.getAttribute('data-open-source') || '').split(':');
                const messageIndex = parseInt(messageIndexRaw, 10);
                const sourceIndex = parseInt(sourceIndexRaw, 10);
                const source = this.messages[messageIndex]?.sources?.[sourceIndex];
                if (!source) return;
                this.selectedCitation = {
                    id: source.marker || source.citation_id || `SRC${sourceIndex + 1}`,
                    source: source.document_name || 'Clinical source',
                    text: source.text || source.chunk_text || source.page_reference || 'Source metadata available.',
                };
                this.render();
                this.setupEvents();
            });
        });

        root.querySelectorAll('.citation-badge').forEach((badge) => {
            this._bindListener(badge, 'click', () => {
                const citId = badge.getAttribute('data-citation');
                const msgEl = badge.closest('[data-message-index]');
                if (!citId || !msgEl) return;
                const msgIdx = parseInt(msgEl.getAttribute('data-message-index'), 10);
                const sources = this.messages[msgIdx]?.sources || [];
                const source = sources.find((item) => (
                    item.marker === citId
                    || item.citation_id === citId
                    || `[${item.marker || item.citation_id}]` === `[${citId}]`
                )) || sources[parseInt(String(citId).match(/(\d+)/)?.[1] || '0', 10) - 1];
                if (!source) return;
                this.selectedCitation = {
                    id: citId,
                    source: source.document_name || 'Clinical source',
                    text: source.text || source.chunk_text || source.page_reference || 'Source metadata available.',
                };
                this.render();
                this.setupEvents();
            });
        });

        root.querySelectorAll('[data-feedback]').forEach((btn) => {
            this._bindListener(btn, 'click', async () => {
                const [indexStr, ratingStr] = String(btn.getAttribute('data-feedback') || '').split(':');
                const index = parseInt(indexStr, 10);
                const message = this.messages[index];
                if (!message?.id) return;
                const rating = ratingStr === 'up' ? 5 : 1;
                try {
                    await submitFeedback(message.id, rating);
                    this.feedbackSelections.set(message.id, rating);
                    showToast('Feedback submitted.', 'success');
                    this.render();
                    this.setupEvents();
                } catch (_) {
                    showToast('Unable to submit feedback.', 'error');
                }
            });
        });

        root.querySelectorAll('[data-copy-message]').forEach((btn) => {
            this._bindListener(btn, 'click', async () => {
                const index = parseInt(btn.getAttribute('data-copy-message'), 10);
                const content = stripConfidenceTag(this.messages[index]?.content || '').trim();
                if (!content) return;
                try {
                    await navigator.clipboard.writeText(content);
                    showToast('Response copied.', 'success', 1800);
                } catch (_) {
                    showToast('Unable to copy response.', 'error');
                }
            });
        });

        root.querySelectorAll('[data-share-message]').forEach((btn) => {
            this._bindListener(btn, 'click', async () => {
                const index = parseInt(btn.getAttribute('data-share-message'), 10);
                const content = stripConfidenceTag(this.messages[index]?.content || '').trim();
                if (!content) return;
                try {
                    if (navigator.share) {
                        await navigator.share({ title: 'ClinicalAI Pro response', text: content });
                    } else {
                        await navigator.clipboard.writeText(content);
                        showToast('Share text copied.', 'success', 1800);
                    }
                } catch (_) {
                    // Native share dialogs throw when dismissed; no toast needed.
                }
            });
        });

        root.querySelectorAll('[data-copy-code]').forEach((btn) => {
            this._bindListener(btn, 'click', async () => {
                const code = btn.getAttribute('data-copy-code') || '';
                try {
                    await navigator.clipboard.writeText(code);
                    btn.textContent = 'Copied';
                    window.setTimeout(() => { btn.textContent = 'Copy'; }, 1400);
                } catch (_) {
                    showToast('Unable to copy code.', 'error');
                }
            });
        });
    }

    updateStreamingMessage(index, shouldScroll = true) {
        const article = this.querySelector(`[data-message-index="${index}"]`);
        if (!article) {
            this.render();
            this.setupEvents();
            return;
        }
        this._cleanupBindingsForRoot(article);
        const bubble = article.querySelector('.message-bubble');
        if (bubble) {
            const confidence = extractConfidence(this.messages[index].content)
                ?? extractConfidence(`[CONFIDENCE: ${this.messages[index].confidenceScore}]`);
            const cleanContent = stripConfidenceTag(this.messages[index].content);
            const reasoning = this.renderReasoningAccordion(this.messages[index], index);
            const sources = this.renderSourceChips(this.messages[index], index);
            const actions = this.renderMessageActions(this.messages[index], index);
            const attachment = this.messages[index].attachment ? this.renderAttachmentCard(this.messages[index].attachment, true) : '';
            const contentMarkup = isAssistantErrorContent(cleanContent, this.messages[index].isError)
                ? renderAssistantErrorNotice(cleanContent)
                : (cleanContent ? renderMarkdown(cleanContent) : '<div class="typing-indicator"><span></span><span></span><span></span></div>');
            const confidenceMarkup = this.isGenerating && index === this.messages.length - 1
                ? '<div class="confidence-badge" data-confidence-placeholder hidden></div>'
                : renderConfidenceBadge(confidence);
            bubble.innerHTML = `
                ${attachment}
                ${reasoning}
                <div class="message-content markdown-body ${isAssistantErrorContent(cleanContent, this.messages[index].isError) ? 'is-error' : ''}">${contentMarkup}</div>
                ${confidenceMarkup}
                ${sources}
                ${actions}
            `;
        }
        this.bindDynamicMessageControls(article);
        if (shouldScroll) this.scrollToBottom();
    }

    finalizeStreamingConfidence(index) {
        const message = this.messages[index];
        if (!message || message.role !== 'assistant') return;

        const rawContent = this.currentAnswer || message.content || '';
        const confidence = extractConfidence(rawContent);
        const cleanContent = stripConfidenceTag(rawContent);

        message.content = cleanContent;
        message.confidenceScore = confidence;

        const article = this.querySelector(`[data-message-index="${index}"]`);
        if (!article) return;

        const contentNode = article.querySelector('.message-content');
        if (contentNode) {
            contentNode.innerHTML = cleanContent ? renderMarkdown(cleanContent) : '';
        }

        const placeholder = article.querySelector('.confidence-badge[data-confidence-placeholder]');
        const existingBadge = article.querySelector('.confidence-badge:not([data-confidence-placeholder])');
        const badgeMarkup = renderConfidenceBadge(confidence);

        if (placeholder) {
            if (badgeMarkup) placeholder.outerHTML = badgeMarkup;
            else placeholder.remove();
            return;
        }

        if (!badgeMarkup) return;
        if (existingBadge) {
            existingBadge.outerHTML = badgeMarkup;
            return;
        }

        const bubble = article.querySelector('.message-bubble');
        const sources = article.querySelector('.source-chip-row');
        const actions = article.querySelector('.message-actions');
        if (bubble) {
            if (sources) {
                sources.insertAdjacentHTML('beforebegin', badgeMarkup);
            } else if (actions) {
                actions.insertAdjacentHTML('beforebegin', badgeMarkup);
            } else {
                bubble.insertAdjacentHTML('beforeend', badgeMarkup);
            }
        }
    }

    async toggleRecording() {
        if (this.isRecording) {
            if (this.mediaRecorder && this.mediaRecorder.state !== 'inactive') {
                this.mediaRecorder.stop();
            }
            this.isRecording = false;
            this.stopRecordingClock({ reset: false });
            this.render();
            this.setupEvents();
            showToast('Processing transcript note...', 'info');
        } else {
            try {
                const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
                this.audioChunks = [];
                this.mediaRecorder = new MediaRecorder(stream, { mimeType: 'audio/webm' });

                this.mediaRecorder.addEventListener('dataavailable', (event) => {
                    if (event.data.size > 0) this.audioChunks.push(event.data);
                });

                this.mediaRecorder.addEventListener('stop', async () => {
                    if (this.discardRecordingOnStop) {
                        this.audioChunks = [];
                        this.discardRecordingOnStop = false;
                        showToast('Voice note recording discarded.', 'info');
                        return;
                    }

                    const audioBlob = new Blob(this.audioChunks, { type: 'audio/webm' });
                    const file = new File([audioBlob], 'voicenote.webm', { type: 'audio/webm' });
                    this.isUploading = true;
                    this.uploadingAttachment = { type: 'audio', name: file.name };
                    this.render();
                    this.setupEvents();

                    try {
                        const res = await transcribeAudio(file);
                        if (res && res.transcript) {
                            const textarea = this.querySelector('#chat-input');
                            this.draftText = (this.draftText ? this.draftText + '\n' : '') + res.transcript;
                            this.persistDraft();
                            if (textarea) {
                                textarea.value = this.draftText;
                                textarea.dispatchEvent(new Event('input'));
                            }
                            showToast('Voice note transcribed successfully.', 'success');
                        } else {
                            showToast('No transcript text returned.', 'warning');
                        }
                    } catch (error) {
                        showToast(error.message || 'Voice transcription failed.', 'error');
                    } finally {
                        this.isUploading = false;
                        this.uploadingAttachment = null;
                        this.render();
                        this.setupEvents();
                    }
                });

                this.mediaRecorder.start();
                this.isRecording = true;
                this.recordingStartedAt = Date.now();
                this.recordingElapsedMs = 0;
                this.startRecordingClock();
                this.render();
                this.setupEvents();
                showToast('Recording voice note...', 'info');

            } catch (_) {
                showToast('Unable to start recording device.', 'error');
            }
        }
    }

    startRecordingClock() {
        this.stopRecordingClock({ reset: true });
        this.recordingClockTimer = window.setInterval(() => {
            this.recordingElapsedMs = Date.now() - this.recordingStartedAt;
            const node = this.querySelector('[data-recording-timer]');
            if (node) {
                node.textContent = formatDuration(this.recordingElapsedMs);
            }
        }, 333);
    }

    stopRecordingClock({ reset = false } = {}) {
        if (this.recordingClockTimer) {
            window.clearInterval(this.recordingClockTimer);
            this.recordingClockTimer = null;
        }
        if (reset) {
            this.recordingElapsedMs = 0;
            this.recordingStartedAt = 0;
        }
    }

    async toggleSoapPane() {
        if (this.isSoapPaneOpen) {
            this.isSoapPaneOpen = false;
            this.render();
            this.setupEvents();
        } else {
            if (!this.soapNote && this.sessionId) {
                await this.generateSoapNoteFromSession();
            } else {
                this.isSoapPaneOpen = true;
                this.render();
                this.setupEvents();
            }
        }
    }

    async generateSoapNoteFromSession() {
        if (!this.sessionId) {
            showToast('SOAP note can be generated once the chat session contains messages.', 'warning');
            return;
        }
        this.isSoapPaneOpen = true;
        this.isSoapLoading = true;
        this.soapNote = '';
        this.render();
        this.setupEvents();

        try {
            const response = await generateSoapNote(this.sessionId);
            this.soapNote = response.soap_note || '';
            const payload = {
                id: this.sessionId,
                messages: this.messages.map(m => ({
                    role: m.role,
                    content: m.content,
                    sources: m.sources,
                })),
                soap_note: this.soapNote,
            };
            window.sessionStorage.setItem(CHAT_SESSION_PAYLOAD_KEY, JSON.stringify(payload));
            showToast('SOAP note generated successfully.', 'success');
        } catch (error) {
            showToast(error.message || 'SOAP note generation failed.', 'error');
        } finally {
            this.isSoapLoading = false;
            this.render();
            this.setupEvents();
        }
    }

    renderDisclaimer() {
        return '';
    }

    renderToolbar() {
        return `
            <header class="chat-toolbar">
                <div>
                    <div class="eyebrow">Case Workspace</div>
                    <h2 class="page-title page-title--compact">Ask & Draft</h2>
                    <p class="chat-toolbar__subtitle">Ask case-grounded questions, verify evidence, and turn the conversation into clinical notes.</p>
                </div>
                <div class="chat-toolbar__actions">
                    <button type="button" id="workspace-source-manage-btn" class="button button--secondary">Sources</button>
                    <button type="button" id="workspace-new-session-btn" class="button button--secondary">New Case</button>
                    <button type="button" id="workspace-soap-toggle-btn" class="button button--primary" ${!this.sessionId || !this.messages.length ? 'disabled' : ''}>
                        ${this.isSoapPaneOpen ? 'Hide SOAP Note' : 'Generate SOAP Note'}
                    </button>
                </div>
            </header>
        `;
    }

    renderEmptyState() {
        const readyDocs = this.workspaceContext.documents.filter((d) => d.status === 'ready');
        const readyImages = this.workspaceContext.images.filter((i) => i.analysis_status === 'ready');
        const summarizePrompt = this.attachedFile?.type === 'document'
            ? 'Summarize the attached document in clean Markdown. Include key points, clinically relevant findings, limitations, and cite each point from the document.'
            : 'Summarize the most important clinical facts in this case with citations.';

        return `
            <section class="chat-empty">
                <div class="chat-empty__mark">∿</div>
                <h2>How can I help with this case?</h2>
                <p class="chat-empty__copy">Ask a clinical question, attach a source, dictate a note, or generate a draft from the conversation.</p>
                <div class="prompt-grid">
                    <button type="button" class="prompt-card" data-use-prompt="${escapeAttr(summarizePrompt)}">
                        <span>${this.attachedFile?.type === 'document' ? 'Summarize document' : 'Summarize case'}</span>
                        <small>${this.attachedFile?.type === 'document' ? 'Key points with citations' : 'Key facts with evidence'}</small>
                    </button>
                    <button type="button" class="prompt-card" data-use-prompt="List the active problems, relevant medications, and abnormal labs with source citations.">
                        <span>Review problems</span>
                        <small>Problems, meds, labs</small>
                    </button>
                    <button type="button" class="prompt-card" data-use-prompt="Compare the recent findings and identify changes that may affect the assessment and plan.">
                        <span>Compare findings</span>
                        <small>Trends and changes</small>
                    </button>
                    <button type="button" class="prompt-card" data-use-prompt="Draft a concise SOAP note from the available case context.">
                        <span>Draft SOAP</span>
                        <small>Clinical note starter</small>
                    </button>
                </div>
                ${(readyDocs.length || readyImages.length) ? `
                    <div class="compact-source-strip">
                        ${readyDocs.slice(0, 2).map((doc) => `
                            <button type="button" class="source-chip" data-attach-workspace-doc="${escapeAttr(doc.id)}">
                                ${escapeHtml(doc.filename)}
                            </button>
                        `).join('')}
                        ${readyImages.slice(0, 2).map((img) => `
                            <button type="button" class="source-chip" data-attach-workspace-image="${escapeAttr(img.id)}">
                                ${escapeHtml(img.original_filename || img.filename)}
                            </button>
                        `).join('')}
                    </div>
                ` : `
                    <button type="button" id="workspace-empty-source-btn" class="button button--secondary">Upload sources first</button>
                `}
            </section>
        `;
    }

    renderAttachmentCard(attachment, removable = false) {
        if (!attachment) return '';
        return `
            <div class="composer-chip">
                <div class="composer-chip__icon">${attachment.type === 'image' ? 'IMG' : 'DOC'}</div>
                <div class="composer-chip__copy">
                    <div class="composer-chip__title">${escapeHtml(attachment.name || 'File')}</div>
                    <div class="composer-chip__meta">${escapeHtml(this.getAttachmentMeta(attachment))}</div>
                </div>
                ${removable ? `<button type="button" class="composer-chip__remove icon-button icon-button--ghost" data-remove-attachment>×</button>` : ''}
            </div>
        `;
    }

    getReasoningLabel(step = {}, index = 0) {
        const text = `${step.title || ''} ${step.description || ''}`.toLowerCase();
        if (/(document|ground|source|retriev|knowledge|citation|passage|evidence)/.test(text)) return 'Searching knowledge';
        if (/(image|vision|scan|visual|thumbnail)/.test(text)) return 'Reading image';
        if (/(agent|tool|workflow|function)/.test(text)) return 'Running agent';
        if (/(generat|answer|respond|response|draft|compose|summar)/.test(text)) return 'Generating response';
        if (/(prepare|request|message|attach|save|check|plan)/.test(text)) return 'Planning';
        return ['Thinking', 'Planning', 'Searching knowledge', 'Generating response'][Math.min(index, 3)];
    }

    getMinimalReasoningSteps(steps = [], isActiveAssistant = false) {
        const rawLabels = steps.length
            ? steps.map((step, index) => this.getReasoningLabel(step, index))
            : ['Thinking'];
        const labels = rawLabels.reduce((items, label) => (
            items[items.length - 1] === label ? items : [...items, label]
        ), []).slice(-4);
        const currentIndex = isActiveAssistant ? labels.length - 1 : -1;

        return labels.map((label, index) => ({
            label: currentIndex === index && !label.endsWith('...') ? `${label}...` : label,
            state: currentIndex === index ? 'current' : 'complete',
        }));
    }

    renderReasoningAccordion(message, index) {
        const isActiveAssistant = this.isGenerating && index === this.messages.length - 1 && message.role === 'assistant';
        const steps = Array.isArray(message.reasoningSteps) ? message.reasoningSteps : [];
        if (!steps.length && !isActiveAssistant) return '';
        const compactSteps = this.getMinimalReasoningSteps(steps, isActiveAssistant);
        const indicator = isActiveAssistant
            ? '<span class="thinking-spinner" aria-hidden="true"></span>'
            : '<span class="thinking-check" aria-hidden="true"></span>';

        return `
            <div class="thinking-line ${isActiveAssistant ? 'is-active' : 'is-complete'}" aria-live="${isActiveAssistant ? 'polite' : 'off'}">
                ${indicator}
                <span class="thinking-steps" aria-label="${isActiveAssistant ? 'Thinking status' : 'Reasoning summary'}">
                    ${compactSteps.map((step, stepIndex) => `
                        <span class="thinking-step is-${step.state}">${escapeHtml(step.label)}</span>
                        ${stepIndex < compactSteps.length - 1 ? '<span class="thinking-separator" aria-hidden="true">/</span>' : ''}
                    `).join('')}
                </span>
            </div>
        `;
    }

    renderSourceChips(message, index) {
        if (!message.sources || !message.sources.length) return '';
        return `
            <div class="source-chip-row">
                ${message.sources.map((source, sourceIdx) => `
                    <button type="button" class="source-chip" data-open-source="${index}:${sourceIdx}">
                        <span>${escapeHtml(source.document_name || 'Evidence')} [SRC${sourceIdx + 1}]</span>
                    </button>
                `).join('')}
            </div>
        `;
    }

    renderMessageActions(message, index) {
        if (message.role !== 'assistant') return '';
        const currentRating = this.feedbackSelections.get(message.id) || message.feedbackRating;
        return `
            <div class="message-actions">
                <button type="button" class="message-action" data-copy-message="${index}" title="Copy response">Copy</button>
                <button type="button" class="message-action" data-share-message="${index}" title="Share response">Share</button>
                ${message.id ? `
                    <span class="message-actions__divider"></span>
                    <button type="button" class="message-action ${currentRating === 5 ? 'is-selected' : ''}" data-feedback="${index}:up" title="Helpful">Good</button>
                    <button type="button" class="message-action ${currentRating === 1 ? 'is-selected' : ''}" data-feedback="${index}:down" title="Not helpful">Needs work</button>
                ` : ''}
            </div>
        `;
    }

    renderMessage(message, index) {
        const isUser = message.role === 'user';
        const bubbleContent = isUser
            ? `
                ${message.attachment ? this.renderAttachmentCard(message.attachment, false) : ''}
                <div class="message-content">${escapeHtml(message.content)}</div>
            `
            : `
                ${message.attachment ? this.renderAttachmentCard(message.attachment, false) : ''}
                ${this.renderReasoningAccordion(message, index)}
                <div class="message-content markdown-body ${isAssistantErrorContent(message.content, message.isError) ? 'is-error' : ''}">
                    ${isAssistantErrorContent(message.content, message.isError) ? renderAssistantErrorNotice(message.content) : renderMarkdown(message.content)}
                </div>
                ${renderConfidenceBadge(message.confidenceScore)}
                ${this.renderSourceChips(message, index)}
                ${this.renderMessageActions(message, index)}
            `;

        return `
            <article class="message-item ${isUser ? 'message-item--user' : 'message-item--assistant'}" data-message-index="${index}">
                ${!isUser ? '<div class="message-avatar message-avatar--assistant">AI</div>' : ''}
                <div class="message-stack">
                    <div class="message-meta">${isUser ? 'You' : 'ClinicalAI Pro'}</div>
                    <div class="message-bubble">
                        ${bubbleContent}
                    </div>
                </div>
                ${isUser ? '<div class="message-avatar message-avatar--user">You</div>' : ''}
            </article>
        `;
    }

    renderComposerStatusRail() {
        if (this.isRecording) {
            return `
                <div class="composer-status composer-status--danger">
                    <span class="composer-status__pulse is-live"></span>
                    <div class="composer-status__copy">
                        <div class="composer-status__label">Recording voice note...</div>
                        <div class="composer-status__hint">Speak naturally. Click Stop Mic to transcribe.</div>
                    </div>
                    <div class="composer-status__meta" data-recording-timer>${formatDuration(this.recordingElapsedMs)}</div>
                </div>
            `;
        }
        if (this.isUploading) {
            const uploadType = this.uploadingAttachment?.type || 'audio';
            const labels = {
                audio: {
                    label: 'Transcribing audio...',
                    hint: 'Converting voice note to text content.',
                    meta: 'Processing',
                },
                document: {
                    label: 'Uploading document...',
                    hint: 'Saving the file and preparing it for indexing.',
                    meta: 'Uploading',
                },
                image: {
                    label: 'Uploading image...',
                    hint: 'Saving the scan and preparing image review.',
                    meta: 'Uploading',
                },
            };
            const status = labels[uploadType] || labels.document;
            return `
                <div class="composer-status composer-status--info">
                    <span class="composer-status__pulse"></span>
                    <div class="composer-status__copy">
                        <div class="composer-status__label">${escapeHtml(status.label)}</div>
                        <div class="composer-status__hint">${escapeHtml(status.hint)}</div>
                    </div>
                    <div class="composer-status__meta">${escapeHtml(status.meta)}</div>
                </div>
            `;
        }
        return '';
    }

    renderComposer() {
        const attachmentChips = [];
        if (this.attachedFile) {
            attachmentChips.push(this.renderAttachmentCard(this.attachedFile, true));
        }

        return `
            <footer class="composer-shell">
                ${this.renderComposerStatusRail()}
                <form id="chat-form" class="composer">
                    <div class="composer-dock">
                        ${attachmentChips.length ? `<div class="composer-chip-row">${attachmentChips.join('')}</div>` : ''}
                        <div class="composer-main">
                            <div class="composer__left">
                                <button type="button" id="attach-btn" class="icon-button composer-action" aria-label="Add file attachment">
                                    ${renderComposerIcon('attach')}
                                </button>
                                <div id="attach-menu" class="attachment-menu ${this.isAttachmentMenuOpen ? 'is-open' : ''}">
                                    <button type="button" class="attachment-menu__item" id="trigger-image-upload">Attach photo</button>
                                    <button type="button" class="attachment-menu__item" id="trigger-document-upload">Attach document</button>
                                </div>
                            </div>
                            <div class="composer__body">
                                <textarea id="chat-input" class="composer__input" rows="1" placeholder="Ask about this case...">${escapeHtml(this.draftText)}</textarea>
                            </div>
                            <div class="composer__right">
                                <button type="button" id="record-audio-btn" class="icon-button composer-action composer-action--mic" aria-label="Record voice note">
                                    ${this.isRecording ? renderComposerIcon('stop') : renderComposerIcon('mic')}
                                </button>
                                <button type="submit" class="send-button composer-send-button" aria-label="Send message" ${this.isGenerating || this.isUploading ? 'disabled' : ''}>
                                    ${renderComposerIcon('send')}
                                </button>
                            </div>
                        </div>
                    </div>
                </form>
                <div class="composer-note">
                    <div>Enter to send. Shift+Enter for a new line.</div>
                    <div>Verify important claims against cited sources.</div>
                </div>
                <input id="upload-image" type="file" accept="image/png,image/jpeg,image/gif,image/webp" hidden />
                <input id="upload-document" type="file" accept=".pdf,.txt,.md,.csv" hidden />
            </footer>
        `;
    }

    renderActiveSourceIndicator() {
        const readySources = this.readyWorkspaceSourceCount();
        const attachedLabel = this.attachedFile ? `Attached: ${this.attachedFile.name}` : `${readySources} ready source${readySources === 1 ? '' : 's'} available`;
        return `
            <div class="chat-context-bar">
                <div class="chat-context-bar__left">
                    <span class="indicator-pulse"></span>
                    <span>${escapeHtml(attachedLabel)}</span>
                </div>
                <button type="button" id="chat-context-sources-btn" class="link-button">Manage sources</button>
            </div>
        `;
    }

    renderCitationDrawer() {
        if (!this.selectedCitation) return '';
        return `
            <aside class="evidence-drawer">
                <div class="evidence-drawer__header">
                    <div>
                        <div class="eyebrow">Evidence</div>
                        <h3>${escapeHtml(this.selectedCitation.id)}</h3>
                    </div>
                    <button type="button" class="icon-button icon-button--ghost" id="clear-citation-btn" aria-label="Close evidence">×</button>
                </div>
                <div class="evidence-drawer__source">${escapeHtml(this.selectedCitation.source || 'Clinical source')}</div>
                <p>${escapeHtml(this.selectedCitation.text || '')}</p>
            </aside>
        `;
    }

    render() {
        const sections = parseSoapSections(this.soapNote);
        this.innerHTML = `
            <section class="chat-view">
                ${this.renderDisclaimer()}
                ${this.renderToolbar()}
                
                <div class="workspace-chat-shell ${this.isSoapPaneOpen ? 'has-soap' : ''}">
                    <main class="workspace-chat-main">
                        <div class="chat-pane">
                            ${this.renderActiveSourceIndicator()}
                            ${this.renderCitationDrawer()}
                            <div class="chat-scroll" id="chat-scroll">
                                <div class="chat-column">
                                    ${this.messages.length ? this.messages.map((message, index) => this.renderMessage(message, index)).join('') : this.renderEmptyState()}
                                </div>
                            </div>
                            ${this.renderComposer()}
                        </div>
                    </main>
                            
                    <div class="soap-draft-pane glass-panel" style="display: ${this.isSoapPaneOpen ? 'flex' : 'none'};">
                        <div class="soap-pane-header flex-row">
                            <div>
                                <div class="eyebrow">Clinical Output</div>
                                <h3>SOAP Note Editor</h3>
                            </div>
                            <button type="button" class="button button--ghost" id="soap-pane-close">×</button>
                        </div>
                        <div class="soap-pane-body">
                            ${this.isSoapLoading ? `
                                <div class="empty-inline">Generating SOAP note from case conversation...</div>
                            ` : `
                                <div class="soap-sections-editor">
                                    ${['subjective', 'objective', 'assessment', 'plan'].map((sec) => `
                                        <section class="soap-editor-section">
                                            <div class="soap-editor-label">${sec.toUpperCase()}</div>
                                            <div class="soap-editor-content markdown-body" contenteditable="true" data-soap-sec="${sec}">
                                                ${renderMarkdown(sections[sec] || '*No context loaded.*')}
                                            </div>
                                        </section>
                                    `).join('')}
                                </div>
                            `}
                        </div>
                        <div class="soap-pane-footer flex-row">
                            <button type="button" class="button button--primary button--full" id="copy-soap-pane-btn" ${this.isSoapLoading ? 'disabled' : ''}>Copy Note</button>
                        </div>
                    </div>
                </div>
            </section>
        `;

        if (!this.querySelector('#chat-input')?.value) {
            this.querySelector('#chat-input')?.focus();
        }
        this.scrollToBottom();
    }

    setupEvents() {
        this._cleanup();
        const form = this.querySelector('#chat-form');
        const input = this.querySelector('#chat-input');
        const attachButton = this.querySelector('#attach-btn');
        const imageInput = this.querySelector('#upload-image');
        const documentInput = this.querySelector('#upload-document');

        // Typing updates height and draft
        this._bindListener(input, 'input', () => {
            if (!input) return;
            this.draftText = input.value;
            this.persistDraft();
            input.style.height = 'auto';
            input.style.height = `${Math.min(input.scrollHeight, 180)}px`;
        });

        this._bindListener(input, 'keydown', (event) => {
            if (event.key === 'Enter' && !event.shiftKey) {
                event.preventDefault();
                form?.dispatchEvent(new Event('submit', { cancelable: true }));
            }
        });

        this._bindListener(form, 'submit', async (event) => {
            event.preventDefault();
            await this.handleSubmit();
        });

        // Attach buttons
        this._bindListener(attachButton, 'click', (event) => {
            event.stopPropagation();
            this.isAttachmentMenuOpen = !this.isAttachmentMenuOpen;
            const menu = this.querySelector('#attach-menu');
            if (menu) menu.classList.toggle('is-open', this.isAttachmentMenuOpen);
        });

        this._bindListener(this.querySelector('#trigger-image-upload'), 'click', () => {
            this.isAttachmentMenuOpen = false;
            imageInput?.click();
        });

        this._bindListener(this.querySelector('#trigger-document-upload'), 'click', () => {
            this.isAttachmentMenuOpen = false;
            documentInput?.click();
        });

        this._bindListener(imageInput, 'change', async () => {
            const file = imageInput?.files?.[0];
            if (file) await this.handleUpload(file, 'image');
            if (imageInput) imageInput.value = '';
        });

        this._bindListener(documentInput, 'change', async () => {
            const file = documentInput?.files?.[0];
            if (file) await this.handleUpload(file, 'document');
            if (documentInput) documentInput.value = '';
        });

        // Record audio
        this._bindListener(this.querySelector('#record-audio-btn'), 'click', async () => {
            await this.toggleRecording();
        });

        // Active left panel checkers
        this.querySelectorAll('[data-select-doc]').forEach((box) => {
            box.addEventListener('change', () => {
                const docId = box.getAttribute('data-select-doc');
                const doc = this.workspaceContext.documents.find(d => String(d.id) === docId);
                if (box.checked) {
                    this.attachedFile = {
                        id: doc.id,
                        name: doc.filename,
                        type: 'document',
                        size: doc.file_size,
                        chunkCount: doc.chunk_count,
                        status: doc.status,
                        progress: 100,
                    };
                } else {
                    this.attachedFile = null;
                }
                this.persistAttachment();
                this.render();
                this.setupEvents();
            });
        });

        this.querySelectorAll('[data-select-img]').forEach((box) => {
            box.addEventListener('change', () => {
                const imgId = box.getAttribute('data-select-img');
                const img = this.workspaceContext.images.find(i => String(i.id) === imgId);
                if (box.checked) {
                    this.attachedFile = {
                        id: img.id,
                        name: img.original_filename || img.filename,
                        type: 'image',
                        previewUrl: img.thumbnail_url || img.image_url,
                        progress: 100,
                    };
                } else {
                    this.attachedFile = null;
                }
                this.persistAttachment();
                this.render();
                this.setupEvents();
            });
        });

        // Global session actions
        this._bindListener(this.querySelector('#workspace-new-session-btn'), 'click', () => {
            this.sessionId = '';
            this.messages = [];
            this.soapNote = '';
            this.isSoapPaneOpen = false;
            this.draftText = '';
            this.persistDraft();
            window.sessionStorage.removeItem('clinical_active_session_id');
            window.sessionStorage.removeItem(CHAT_SESSION_PAYLOAD_KEY);
            window.dispatchEvent(new CustomEvent('clinical:new-chat'));
            this.render();
            this.setupEvents();
        });

        this._bindListener(this.querySelector('#workspace-source-manage-btn'), 'click', () => navigate('/sources'));
        this._bindListener(this.querySelector('#chat-context-sources-btn'), 'click', () => navigate('/sources'));
        this._bindListener(this.querySelector('#workspace-empty-source-btn'), 'click', () => navigate('/sources'));

        this._bindListener(this.querySelector('#workspace-soap-toggle-btn'), 'click', async () => {
            await this.toggleSoapPane();
        });

        this._bindListener(this.querySelector('#soap-pane-close'), 'click', () => {
            this.isSoapPaneOpen = false;
            this.render();
            this.setupEvents();
        });

        // Copy SOAP Note
        const copySoapBtn = this.querySelector('#copy-soap-pane-btn');
        if (copySoapBtn) {
            this._bindListener(copySoapBtn, 'click', async () => {
                try {
                    await navigator.clipboard.writeText(this.soapNote);
                    showToast('SOAP note copied to clipboard.', 'success');
                } catch (_) {
                    showToast('Failed to copy note.', 'error');
                }
            });
        }

        // Attachment remover
        this.querySelectorAll('[data-remove-attachment]').forEach((btn) => {
            btn.addEventListener('click', () => {
                this.attachedFile = null;
                this.persistAttachment();
                this.render();
                this.setupEvents();
            });
        });

        // Click citation badges inside message bubble
        this.querySelectorAll('.citation-badge').forEach((badge) => {
            badge.addEventListener('click', (event) => {
                const citId = badge.getAttribute('data-citation');
                const match = citId.match(/(\d+)/);
                if (match) {
                    const idx = parseInt(match[1]) - 1;
                    // Find closest message container
                    const msgEl = badge.closest('[data-message-index]');
                    const msgIdx = parseInt(msgEl.getAttribute('data-message-index'));
                    const source = this.messages[msgIdx]?.sources?.[idx];
                    if (source) {
                        this.selectedCitation = {
                            id: citId,
                            source: source.document_name,
                            text: source.text,
                        };
                        this.render();
                        this.setupEvents();
                    }
                }
            });
        });

        // Citation clear button
        this.querySelector('#clear-citation-btn')?.addEventListener('click', () => {
            this.selectedCitation = null;
            this.render();
            this.setupEvents();
        });

        // Suggest chips at empty state
        this.querySelectorAll('[data-use-prompt]').forEach((btn) => {
            btn.addEventListener('click', () => {
                const prompt = btn.getAttribute('data-use-prompt') || '';
                this.draftText = this.attachedFile?.type === 'document' && /summarize.+case/i.test(prompt)
                    ? this.getDefaultAttachmentPrompt(this.attachedFile)
                    : prompt;
                this.persistDraft();
                this.render();
                this.setupEvents();
                const textarea = this.querySelector('#chat-input');
                if (textarea) {
                    textarea.focus();
                    textarea.selectionStart = textarea.value.length;
                    textarea.selectionEnd = textarea.value.length;
                }
            });
        });

        this.querySelectorAll('[data-attach-workspace-doc]').forEach((btn) => {
            btn.addEventListener('click', () => {
                const docId = btn.getAttribute('data-attach-workspace-doc');
                const doc = this.workspaceContext.documents.find(d => String(d.id) === docId);
                if (doc) {
                    this.attachedFile = {
                        id: doc.id,
                        name: doc.filename,
                        type: 'document',
                        size: doc.file_size,
                        chunkCount: doc.chunk_count,
                        status: doc.status,
                        progress: 100,
                    };
                    this.persistAttachment();
                    this.render();
                    this.setupEvents();
                    showToast(`Attached ${doc.filename}.`, 'success');
                }
            });
        });

        this.querySelectorAll('[data-attach-workspace-image]').forEach((btn) => {
            btn.addEventListener('click', () => {
                const imgId = btn.getAttribute('data-attach-workspace-image');
                const img = this.workspaceContext.images.find(i => String(i.id) === imgId);
                if (img) {
                    this.attachedFile = {
                        id: img.id,
                        name: img.original_filename || img.filename,
                        type: 'image',
                        previewUrl: img.thumbnail_url || img.image_url,
                        progress: 100,
                    };
                    this.persistAttachment();
                    this.render();
                    this.setupEvents();
                    showToast(`Attached image scan.`, 'success');
                }
            });
        });

        // Reasoning toggler
        this.querySelectorAll('[data-toggle-reasoning]').forEach((btn) => {
            btn.addEventListener('click', () => {
                const idx = parseInt(btn.getAttribute('data-toggle-reasoning'));
                if (this.expandedReasoningKeys.has(idx)) {
                    this.expandedReasoningKeys.delete(idx);
                } else {
                    this.expandedReasoningKeys.add(idx);
                }
                this.render();
                this.setupEvents();
            });
        });

        // Click menu outside listener
        this._bindListener(document, 'click', (event) => {
            const menu = this.querySelector('#attach-menu');
            if (menu && !menu.contains(event.target) && !this.querySelector('#attach-btn')?.contains(event.target)) {
                this.isAttachmentMenuOpen = false;
                menu.classList.remove('is-open');
            }
        });

        // Feedback
        this.querySelectorAll('[data-feedback]').forEach((btn) => {
            btn.addEventListener('click', async () => {
                const [indexStr, ratingStr] = btn.getAttribute('data-feedback').split(':');
                const index = parseInt(indexStr);
                const message = this.messages[index];
                if (!message?.id) return;
                const rating = ratingStr === 'up' ? 5 : 1;
                try {
                    await submitFeedback(message.id, rating);
                    this.feedbackSelections.set(message.id, rating);
                    showToast('Feedback submitted.', 'success');
                    this.render();
                    this.setupEvents();
                } catch (err) {
                    showToast('Unable to submit feedback.', 'error');
                }
            });
        });
    }

    async handleUpload(file, type) {
        this.isUploading = true;
        this.uploadingAttachment = { type, name: file.name };
        this.render();
        this.setupEvents();
        try {
            const res = await (type === 'image' ? uploadImage(file, () => {}) : uploadDocument(file, () => {}));
            this.attachedFile = {
                id: res.id,
                name: res.filename || file.name,
                type,
                size: file.size,
                status: res.status || 'ready',
                stage: res.stage || res.status || 'ready',
                chunkCount: res.chunk_count || 0,
                progress: res.processing_progress ?? (String(res.status || '').toLowerCase() === 'ready' ? 100 : 0),
            };
            if (type === 'document') {
                this.upsertWorkspaceDocument({
                    id: res.id,
                    filename: res.filename || file.name,
                    file_size: file.size,
                    status: res.status || 'queued',
                    stage: res.stage || res.status || 'uploaded',
                    chunk_count: res.chunk_count || 0,
                });
                if (String(res.status || '').toLowerCase() !== 'ready') {
                    this.scheduleAttachmentPoll(res.id);
                }
            } else {
                this.upsertWorkspaceImage({
                    id: res.id,
                    filename: res.filename || file.name,
                    original_filename: res.original_filename || res.filename || file.name,
                    status: res.status || 'ready',
                    analysis_status: res.analysis_status || res.status || 'ready',
                });
            }
            this.persistAttachment();
            showToast(`${file.name} successfully uploaded.`, 'success');
        } catch (err) {
            showToast(err.message || 'Upload failed.', 'error');
        } finally {
            this.isUploading = false;
            this.uploadingAttachment = null;
            this.render();
            this.setupEvents();
        }
    }
}

customElements.define('case-workspace', CaseWorkspace);
export default CaseWorkspace;
