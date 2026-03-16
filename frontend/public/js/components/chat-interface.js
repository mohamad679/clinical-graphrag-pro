import { streamChat, uploadImage, uploadDocument, uploadAudioForTranscription } from '../api.js';

// ── Inline markdown helpers (safe HTML escape + inline styles) ────────────────
const esc = (s) => s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
const inlineMd = (s) => esc(s)
    .replace(/\*\*\*(.+?)\*\*\*/g, '<strong><em>$1</em></strong>')
    .replace(/\*\*(.+?)\*\*/g, '<strong style="color:#ececec;font-weight:600;">$1</strong>')
    .replace(/\*(.+?)\*/g, '<em style="color:#d4d4d4;">$1</em>')
    .replace(/`([^`]+)`/g, '<code style="background:#1c1c1c;padding:2px 7px;border-radius:5px;font-size:12.5px;font-family:\'Fira Code\',monospace;color:#7dd3fc;">$1</code>')
    .replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2" target="_blank" rel="noreferrer" style="color:#60a5fa;text-decoration:underline;">$1</a>');

function renderMarkdown(text) {
    if (!text) return '';

    // Strip backend metadata artifacts that should not be shown to users
    text = text
        .replace(/\[Source:.*?\]/gs, '')
        .replace(/\[CONFIDENCE:\s*[\d.]+\]/gi, '')
        .trim();

    if (!text) return '';

    const lines = text.split('\n');
    let html = '';
    let inUl = false, inOl = false, inCode = false, codeBuf = '', codeLang = '';
    let tableLines = []; // Accumulate pipe-table rows

    const closeList = () => {
        if (inUl) { html += '</ul>'; inUl = false; }
        if (inOl) { html += '</ol>'; inOl = false; }
    };

    const flushTable = () => {
        if (tableLines.length === 0) return;
        // First row = header, second row = separator (---)
        const parseRow = (row) => row.replace(/^\||\|$/g, '').split('|').map(c => c.trim());
        const headerCells = parseRow(tableLines[0]);
        const dataRows = tableLines.slice(2); // skip separator row

        let tableHtml = `<div style="overflow-x:auto;margin:14px 0;border-radius:10px;border:1px solid rgba(255,255,255,0.08);">
            <table style="width:100%;border-collapse:collapse;font-size:13.5px;">
                <thead>
                    <tr style="background:#1e1e1e;">
                        ${headerCells.map(c => `<th style="padding:10px 14px;text-align:left;font-weight:600;color:#ececec;white-space:nowrap;border-bottom:1px solid rgba(255,255,255,0.1);">${inlineMd(c)}</th>`).join('')}
                    </tr>
                </thead>
                <tbody>
                    ${dataRows.map((row, ri) => {
            const cells = parseRow(row);
            const bg = ri % 2 === 0 ? 'transparent' : 'rgba(255,255,255,0.025)';
            return `<tr style="background:${bg};">
                            ${cells.map((c, ci) => `<td style="padding:9px 14px;color:${ci === 0 ? '#ececec' : '#a3a3a3'};border-bottom:1px solid rgba(255,255,255,0.05);line-height:1.5;">${inlineMd(c)}</td>`).join('')}
                        </tr>`;
        }).join('')}
                </tbody>
            </table>
        </div>`;
        html += tableHtml;
        tableLines = [];
    };

    const isTableRow = (l) => l.trim().startsWith('|') && l.trim().endsWith('|');
    const isSeparator = (l) => /^\|[\s\-:|]+\|/.test(l.trim());

    for (let i = 0; i < lines.length; i++) {
        const raw = lines[i];
        const line = raw;

        // Code fence
        if (line.startsWith('```')) {
            if (inCode) {
                flushTable();
                html += `<pre style="background:#161616;border:1px solid rgba(255,255,255,0.08);border-radius:12px;padding:16px;overflow-x:auto;margin:12px 0 4px;"><code style="font-family:'Fira Code','Courier New',monospace;font-size:13px;line-height:1.7;color:#e2e8f0;">${esc(codeBuf.trimEnd())}</code></pre>`;
                codeBuf = ''; codeLang = ''; inCode = false;
            } else {
                flushTable(); closeList();
                codeLang = line.slice(3).trim(); inCode = true;
            }
            continue;
        }
        if (inCode) { codeBuf += raw + '\n'; continue; }

        // Pipe tables — accumulate rows until non-table line
        if (isTableRow(line)) {
            closeList();
            tableLines.push(line);
            continue;
        } else if (tableLines.length > 0) {
            flushTable();
        }

        // Headings
        if (line.startsWith('#### ')) { closeList(); html += `<h4 style="font-size:13px;font-weight:700;color:#ececec;margin:14px 0 4px;letter-spacing:0.03em;text-transform:uppercase;opacity:0.65;">${inlineMd(line.slice(5))}</h4>`; continue; }
        if (line.startsWith('### ')) { closeList(); html += `<h3 style="font-size:15.5px;font-weight:700;color:#ececec;margin:18px 0 6px;">${inlineMd(line.slice(4))}</h3>`; continue; }
        if (line.startsWith('## ')) { closeList(); html += `<h2 style="font-size:17px;font-weight:700;color:#ececec;margin:20px 0 8px;padding-bottom:6px;border-bottom:1px solid rgba(255,255,255,0.08);">${inlineMd(line.slice(3))}</h2>`; continue; }
        if (line.startsWith('# ')) { closeList(); html += `<h1 style="font-size:20px;font-weight:700;color:#ececec;margin:20px 0 10px;padding-bottom:8px;border-bottom:1px solid rgba(255,255,255,0.12);">${inlineMd(line.slice(2))}</h1>`; continue; }

        // Horizontal rule
        if (/^[-*_]{3,}$/.test(line.trim())) { closeList(); html += '<hr style="border:none;border-top:1px solid rgba(255,255,255,0.08);margin:16px 0;">'; continue; }

        // Blockquote
        if (line.startsWith('> ')) { closeList(); html += `<blockquote style="border-left:3px solid rgba(96,165,250,0.5);margin:8px 0;padding:4px 14px;color:#a3a3a3;background:rgba(96,165,250,0.04);border-radius:0 6px 6px 0;">${inlineMd(line.slice(2))}</blockquote>`; continue; }

        // Unordered list
        if (/^[\*\-\+] /.test(line)) {
            if (inOl) { html += '</ol>'; inOl = false; }
            if (!inUl) { html += '<ul style="margin:8px 0;padding-left:0;list-style:none;display:flex;flex-direction:column;gap:5px;">'; inUl = true; }
            html += `<li style="display:flex;gap:8px;align-items:flex-start;color:#d4d4d4;line-height:1.65;"><span style="flex-shrink:0;margin-top:9px;width:4px;height:4px;border-radius:50%;background:#525252;display:inline-block;"></span><span>${inlineMd(line.replace(/^[\*\-\+] /, ''))}</span></li>`;
            continue;
        }

        // Ordered list
        if (/^\d+\. /.test(line)) {
            if (inUl) { html += '</ul>'; inUl = false; }
            if (!inOl) { html += '<ol style="margin:8px 0;padding-left:0;list-style:none;display:flex;flex-direction:column;gap:5px;">'; inOl = true; }
            html += `<li style="display:flex;gap:10px;align-items:flex-start;color:#d4d4d4;line-height:1.65;"><span style="flex-shrink:0;min-width:20px;color:#676767;font-size:13px;margin-top:1px;">${line.match(/^(\d+)\./)[1]}.</span><span>${inlineMd(line.replace(/^\d+\. /, ''))}</span></li>`;
            continue;
        }

        // Empty line
        if (line.trim() === '') { closeList(); flushTable(); html += '<div style="height:5px;"></div>'; continue; }

        // Normal paragraph
        closeList();
        html += `<p style="margin:0 0 2px;color:#d4d4d4;line-height:1.75;">${inlineMd(line)}</p>`;
    }

    flushTable();
    if (inCode) html += `<pre style="background:#161616;border-radius:12px;padding:16px;overflow-x:auto;"><code style="font-family:monospace;font-size:13px;color:#e2e8f0;">${esc(codeBuf.trimEnd())}</code></pre>`;
    if (inUl) html += '</ul>';
    if (inOl) html += '</ol>';
    return html;
}

// ─────────────────────────────────────────────────────────────────────────────

class ChatInterface extends HTMLElement {
    constructor() {
        super();
        this.messages = [];
        this.isGenerating = false;
        this.attachedFile = null;
        this.isUploading = false;
        this.isMenuOpen = false;
        this.isRecording = false;
        this.mediaRecorder = null;
        this.audioChunks = [];
        this.sessionId = null;
        this.reasoningSteps = []; // Tracks thinking steps from backend
        this._toastTimer = null;
    }

    connectedCallback() {
        this.render();
        this.setupEvents();
        this.bindAttachmentEvents();
    }

    render() {
        this.innerHTML = `
            <div style="display:flex;flex-direction:column;height:100%;width:100%;position:relative;background:#212121;">

                <!-- Chat Log -->
                <div id="chat-messages" style="flex:1;overflow-y:auto;padding:24px 0 180px;display:flex;flex-direction:column;scroll-behavior:smooth;">
                    <div style="width:100%;max-width:720px;margin:0 auto;padding:0 24px;">
                        ${this.messages.length === 0 ? this.renderEmptyState() : this.messages.map((m, i) => this.renderMessage(m, i)).join('')}
                    </div>
                </div>

                <!-- Input Area -->
                <div style="position:absolute;bottom:0;width:100%;padding:0 16px 20px;background:linear-gradient(to top, #212121 80%, transparent);">
                    <div style="max-width:720px;margin:0 auto;">

                        <!-- Attached File Preview -->
                        ${this.attachedFile ? `
                            <div style="display:inline-flex;align-items:center;gap:8px;padding:6px 12px;margin-bottom:8px;background:#2f2f2f;border-radius:10px;border:1px solid rgba(255,255,255,0.08);">
                                <i data-lucide="${this.attachedFile.type === 'image' ? 'image' : 'file-text'}" style="width:14px;height:14px;color:#a3a3a3;flex-shrink:0;"></i>
                                <span style="font-size:13px;color:#d4d4d4;max-width:220px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${this.attachedFile.name}</span>
                                <button id="remove-file-btn" style="background:none;border:none;cursor:pointer;padding:2px;color:#676767;display:flex;line-height:1;" title="Remove">
                                    <i data-lucide="x" style="width:13px;height:13px;"></i>
                                </button>
                            </div>
                        ` : ''}

                        <!-- Recording Indicator -->
                        ${this.isRecording ? `
                            <div style="display:flex;align-items:center;gap:8px;margin-bottom:8px;">
                                <div style="width:7px;height:7px;border-radius:50%;background:#ef4444;animation:pulse 1s infinite;"></div>
                                <span style="font-size:13px;color:#ef4444;font-weight:500;">Recording…</span>
                            </div>
                        ` : ''}

                        <!-- Input Pill -->
                        <form id="chat-form" style="display:flex;align-items:flex-end;gap:8px;background:#2f2f2f;border-radius:16px;padding:10px 12px;border:1px solid rgba(255,255,255,0.06);transition:border-color 0.2s;"
                            onfocusin="this.style.borderColor='rgba(255,255,255,0.14)'"
                            onfocusout="this.style.borderColor='rgba(255,255,255,0.06)'">

                            <!-- + Button -->
                            <div style="position:relative;flex-shrink:0;">
                                <button type="button" id="attach-btn" ${this.isGenerating || this.isUploading ? 'disabled' : ''}
                                    style="width:34px;height:34px;border-radius:50%;background:#383838;border:none;cursor:pointer;display:flex;align-items:center;justify-content:center;color:#a3a3a3;transition:background 0.15s;flex-shrink:0;"
                                    onmouseover="if(!this.disabled) this.style.background='#424242'" onmouseout="this.style.background='#383838'">
                                    ${this.isUploading
                ? '<i data-lucide="loader-2" style="width:16px;height:16px;animation:spin 1s linear infinite;"></i>'
                : '<i data-lucide="plus" style="width:18px;height:18px;"></i>'}
                                </button>

                                <!-- Dropdown -->
                                <div id="attach-menu" style="position:absolute;bottom:calc(100% + 10px);left:0;width:180px;background:#2a2a2a;border:1px solid rgba(255,255,255,0.1);border-radius:14px;box-shadow:0 10px 40px rgba(0,0,0,0.5);padding:6px;transform:scale(0.94) translateY(4px);opacity:0;pointer-events:none;transition:all 0.15s cubic-bezier(0.2,0,0,1);transform-origin:bottom left;z-index:50;">
                                    <button type="button" id="trigger-image-upload"
                                        style="display:flex;align-items:center;gap:10px;padding:10px 12px;font-size:13.5px;color:#d4d4d4;cursor:pointer;background:none;border:none;width:100%;text-align:left;border-radius:9px;font-family:inherit;"
                                        onmouseover="this.style.background='#383838'" onmouseout="this.style.background='none'">
                                        <i data-lucide="image" style="width:16px;height:16px;flex-shrink:0;color:#7dd3fc;"></i>
                                        Add photos
                                    </button>
                                    <button type="button" id="trigger-doc-upload"
                                        style="display:flex;align-items:center;gap:10px;padding:10px 12px;font-size:13.5px;color:#d4d4d4;cursor:pointer;background:none;border:none;width:100%;text-align:left;border-radius:9px;font-family:inherit;"
                                        onmouseover="this.style.background='#383838'" onmouseout="this.style.background='none'">
                                        <i data-lucide="paperclip" style="width:16px;height:16px;flex-shrink:0;color:#fb923c;"></i>
                                        Add files
                                    </button>

                                </div>
                            </div>

                            <!-- Textarea -->
                            <textarea id="chat-input" rows="1"
                                placeholder="Message ClinicalAI…"
                                ${this.isGenerating || this.isRecording ? 'disabled' : ''}
                                style="flex:1;background:transparent;border:none;outline:none;color:#ececec;font-size:15.5px;font-family:inherit;resize:none;padding:6px 0;line-height:1.5;max-height:180px;overflow-y:auto;min-height:36px;"></textarea>

                            <!-- Right Controls -->
                            <div style="display:flex;align-items:center;gap:6px;flex-shrink:0;">
                                <button type="button" id="record-audio-btn" ${this.isGenerating || this.isUploading ? 'disabled' : ''}
                                    style="width:34px;height:34px;border-radius:50%;background:${this.isRecording ? 'rgba(239,68,68,0.15)' : '#383838'};border:none;cursor:pointer;display:flex;align-items:center;justify-content:center;color:${this.isRecording ? '#ef4444' : '#a3a3a3'};transition:background 0.15s;"
                                    onmouseover="if(!this.disabled) this.style.background='#424242'" onmouseout="this.style.background='${this.isRecording ? 'rgba(239,68,68,0.15)' : '#383838'}'">
                                    ${this.isRecording
                ? '<i data-lucide="square" style="width:12px;height:12px;fill:currentColor;"></i>'
                : '<i data-lucide="mic" style="width:15px;height:15px;"></i>'}
                                </button>

                                <button type="submit" id="send-btn" ${this.isGenerating || this.isUploading ? 'disabled' : ''}
                                    style="width:34px;height:34px;border-radius:50%;background:${this.isGenerating || this.isUploading ? '#383838' : '#ffffff'};border:none;cursor:pointer;display:flex;align-items:center;justify-content:center;color:${this.isGenerating || this.isUploading ? '#676767' : '#000'};transition:all 0.2s;opacity:${this.isGenerating || this.isUploading ? 0.45 : 1};"
                                    onmouseover="if(!this.disabled) this.style.background='#e5e5e5'" onmouseout="this.style.background='${this.isGenerating || this.isUploading ? '#383838' : '#ffffff'}'">
                                    <i data-lucide="arrow-up" style="width:16px;height:16px;"></i>
                                </button>
                            </div>
                        </form>

                        <p style="text-align:center;margin-top:8px;font-size:11.5px;color:#525252;">ClinicalAI can make mistakes. Consider verifying important information.</p>
                    </div>
                </div>
            </div>

            <!-- ⚠️ File inputs outside form — prevents form submission on select -->
            <input type="file" id="upload-image" style="display:none;position:absolute;" accept="image/png,image/jpeg,image/gif,image/webp" />
            <input type="file" id="upload-doc" style="display:none;position:absolute;" accept=".pdf,.txt,.csv,.docx" />

            <!-- Toast -->
            <div id="upload-toast" style="position:absolute;bottom:120px;left:50%;transform:translateX(-50%);background:#ef4444;color:#fff;font-size:13px;font-weight:500;padding:10px 20px;border-radius:12px;opacity:0;pointer-events:none;transition:opacity 0.25s;white-space:nowrap;z-index:200;box-shadow:0 4px 20px rgba(0,0,0,0.4);"></div>

            <style>
                @keyframes spin { to { transform: rotate(360deg); } }
                @keyframes pulse { 0%,100%{opacity:1} 50%{opacity:0.4} }
                @keyframes typing-bounce { 0%,60%,100%{transform:translateY(0)} 30%{transform:translateY(-5px)} }
                @keyframes fadeIn { from{opacity:0;transform:translateY(6px)} to{opacity:1;transform:translateY(0)} }
                @keyframes reasonPulse { 0%,100%{opacity:0.6} 50%{opacity:1} }
                #chat-messages { scrollbar-width: thin; scrollbar-color: #383838 transparent; }
                #chat-input::placeholder { color: #525252; }
                .ai-message { animation: fadeIn 0.25s ease; }
                .reason-step { animation: fadeIn 0.2s ease; }
            </style>
        `;

        if (window.lucide) window.lucide.createIcons();
        this.scrollToBottom();
    }

    renderEmptyState() {
        const chips = [
            ['What is the first-line treatment', 'for COPD exacerbation?'],
            ['Summarize clinical guidelines', 'for hypertensive emergencies'],
            ['Cross-reference symptoms', 'with possible differential diagnoses'],
            ['Analyze patient data', 'and generate a clinical summary'],
        ];
        return `
            <div style="display:flex;flex-direction:column;align-items:center;margin-top:14vh;text-align:center;padding-bottom:24px;">
                <h2 style="font-size:27px;font-weight:600;color:#ececec;margin:0 0 28px 0;">What can I help with?</h2>
                <div style="display:grid;grid-template-columns:1fr 1fr;gap:10px;width:100%;max-width:600px;text-align:left;">
                    ${chips.map(([title, sub]) => `
                        <button class="suggestion-chip" style="display:flex;flex-direction:column;gap:3px;padding:13px 15px;background:#2a2a2a;border:1px solid rgba(255,255,255,0.06);border-radius:14px;cursor:pointer;text-align:left;width:100%;font-family:inherit;color:#ececec;transition:background 0.15s;"
                            onmouseover="this.style.background='#333333'" onmouseout="this.style.background='#2a2a2a'">
                            <span style="font-size:13.5px;font-weight:500;color:#d4d4d4;line-height:1.4;">${title}</span>
                            <span style="font-size:12.5px;color:#676767;line-height:1.4;">${sub}</span>
                        </button>
                    `).join('')}
                </div>
            </div>
        `;
    }

    renderMessage(msg, idx) {
        const isUser = msg.role === 'user';
        const content = msg.content || '';

        if (isUser) {
            // User bubble — attachment chip + message stacked
            return `
                <div style="display:flex;flex-direction:column;align-items:flex-end;margin-bottom:20px;">
                    ${msg.attachment ? `
                        <div style="display:flex;align-items:center;gap:7px;padding:6px 12px;margin-bottom:6px;background:#1e1e1e;border:1px solid rgba(255,255,255,0.08);border-radius:10px;">
                            <i data-lucide="${msg.attachment.type === 'image' ? 'image' : 'file-text'}" style="width:13px;height:13px;color:#7dd3fc;flex-shrink:0;"></i>
                            <span style="font-size:12.5px;color:#a3a3a3;max-width:200px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${msg.attachment.name}</span>
                        </div>
                    ` : ''}
                    ${content ? `
                        <div style="max-width:80%;padding:11px 16px;background:#2f2f2f;border-radius:18px 18px 4px 18px;color:#ececec;font-size:15px;line-height:1.65;word-break:break-word;">
                            ${esc(content)}
                        </div>
                    ` : ''}
                </div>
            `;
        } else {
            // AI bubble
            const isStreaming = this.isGenerating && idx === this.messages.length - 1;
            return `
                <div class="ai-message" style="display:flex;gap:12px;margin-bottom:24px;">
                    <div style="width:26px;height:26px;border-radius:50%;background:#1a1a1a;border:1px solid rgba(255,255,255,0.1);display:flex;align-items:center;justify-content:center;flex-shrink:0;margin-top:2px;">
                        <i data-lucide="bot" style="width:13px;height:13px;color:#ececec;"></i>
                    </div>
                    <div style="flex:1;min-width:0;">

                        ${isStreaming && this.reasoningSteps.length > 0 ? this.renderReasoningPanel() : ''}

                        <div class="markdown-body" style="color:#d4d4d4;font-size:15px;line-height:1.75;word-break:break-word;">
                            ${content === '' && isStreaming
                    ? `<div style="display:flex;gap:5px;padding:10px 0;">
                                    <div style="width:6px;height:6px;border-radius:50%;background:#525252;animation:typing-bounce 1.2s infinite 0s;"></div>
                                    <div style="width:6px;height:6px;border-radius:50%;background:#525252;animation:typing-bounce 1.2s infinite 0.2s;"></div>
                                    <div style="width:6px;height:6px;border-radius:50%;background:#525252;animation:typing-bounce 1.2s infinite 0.4s;"></div>
                                  </div>`
                    : renderMarkdown(content)}
                        </div>

                        ${!isStreaming && content ? `
                            <div style="display:flex;gap:2px;margin-top:10px;opacity:0;transition:opacity 0.15s;" onmouseenter="this.style.opacity='1'" onmouseleave="this.style.opacity='0'">
                                <button onclick="navigator.clipboard.writeText(${JSON.stringify(content).replace(/'/g, "\\'")})" title="Copy"
                                    style="padding:5px 8px;border-radius:7px;background:none;border:none;cursor:pointer;color:#525252;display:flex;align-items:center;gap:5px;font-size:12px;font-family:inherit;"
                                    onmouseover="this.style.color='#a3a3a3';this.style.background='#2a2a2a'" onmouseout="this.style.color='#525252';this.style.background='none'">
                                    <i data-lucide="copy" style="width:13px;height:13px;"></i> Copy
                                </button>
                                <button title="Good response"
                                    style="padding:5px 7px;border-radius:7px;background:none;border:none;cursor:pointer;color:#525252;display:flex;"
                                    onmouseover="this.style.color='#a3a3a3';this.style.background='#2a2a2a'" onmouseout="this.style.color='#525252';this.style.background='none'">
                                    <i data-lucide="thumbs-up" style="width:13px;height:13px;"></i>
                                </button>
                                <button title="Bad response"
                                    style="padding:5px 7px;border-radius:7px;background:none;border:none;cursor:pointer;color:#525252;display:flex;"
                                    onmouseover="this.style.color='#a3a3a3';this.style.background='#2a2a2a'" onmouseout="this.style.color='#525252';this.style.background='none'">
                                    <i data-lucide="thumbs-down" style="width:13px;height:13px;"></i>
                                </button>
                            </div>
                        ` : ''}
                    </div>
                </div>
            `;
        }
    }

    renderReasoningPanel() {
        const steps = this.reasoningSteps;
        if (steps.length === 0) return '';
        const activeStep = steps[steps.length - 1];
        return `
            <div id="reasoning-panel" style="margin-bottom:10px;padding:10px 14px;background:#1a1a1a;border:1px solid rgba(255,255,255,0.07);border-radius:12px;overflow:hidden;">
                <div style="display:flex;align-items:center;gap:8px;margin-bottom:${steps.length > 1 ? '8px' : '0'};">
                    <div style="width:8px;height:8px;border-radius:50%;background:#3b82f6;animation:reasonPulse 1.2s ease infinite;flex-shrink:0;"></div>
                    <span style="font-size:12.5px;font-weight:500;color:#7dd3fc;">${activeStep.title}</span>
                    <span style="font-size:11.5px;color:#525252;flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${activeStep.description || ''}</span>
                </div>
                ${steps.length > 1 ? steps.slice(0, -1).map(s => `
                    <div class="reason-step" style="display:flex;align-items:center;gap:8px;margin-top:4px;">
                        <i data-lucide="check" style="width:12px;height:12px;color:#22c55e;flex-shrink:0;"></i>
                        <span style="font-size:12px;color:#525252;">${s.title}</span>
                    </div>
                `).join('') : ''}
            </div>
        `;
    }

    setupEvents() {
        const form = this.querySelector('#chat-form');
        const input = this.querySelector('#chat-input');
        if (!form || !input) return;

        input.addEventListener('input', () => {
            input.style.height = 'auto';
            input.style.height = Math.min(input.scrollHeight, 180) + 'px';
        });
        input.addEventListener('keydown', (e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                form.dispatchEvent(new Event('submit'));
            }
        });

        form.addEventListener('submit', async (e) => {
            e.preventDefault();
            const message = input.value.trim();
            if ((!message && !this.attachedFile) || this.isGenerating) return;

            input.value = '';
            input.style.height = 'auto';

            this.messages.push({ role: 'user', content: message, attachment: this.attachedFile });
            const currentAttachment = this.attachedFile;
            this.attachedFile = null;
            this.reasoningSteps = [];

            const aiMsgIndex = this.messages.length;
            this.messages.push({ role: 'system', content: '' });

            this.isGenerating = true;
            this.render();

            // Live-update targets
            const getAiBody = () => this.querySelector('.markdown-body:last-of-type') ||
                this.querySelectorAll('.markdown-body')[this.querySelectorAll('.markdown-body').length - 1];
            const getReasonPanel = () => this.querySelector('#reasoning-panel');

            try {
                await streamChat(
                    message, false,
                    (chunk) => {
                        this.messages[aiMsgIndex].content += chunk;
                        const body = getAiBody();
                        if (body) body.innerHTML = renderMarkdown(this.messages[aiMsgIndex].content);
                        this.scrollToBottom();
                    },
                    () => { },
                    ({ session_id }) => {
                        if (session_id) this.sessionId = session_id;
                        this.reasoningSteps = [];
                        this.isGenerating = false;
                        this.render();
                        this.setupEvents();
                        this.bindAttachmentEvents();
                        const layout = document.querySelector('app-layout');
                        if (layout?.refreshSessions) layout.refreshSessions();
                    },
                    (err) => {
                        this.messages[aiMsgIndex].content += `\n\n**Error:** ${err.message}`;
                        this.reasoningSteps = [];
                        this.isGenerating = false;
                        this.render();
                        this.setupEvents();
                        this.bindAttachmentEvents();
                    },
                    (step) => {
                        // Reasoning step from backend — update thinking panel live
                        const existing = this.reasoningSteps.findIndex(s => s.step === step.step);
                        if (existing >= 0) this.reasoningSteps[existing] = step;
                        else this.reasoningSteps.push(step);

                        // Update panel in-place without full re-render
                        const panel = getReasonPanel();
                        if (panel) {
                            panel.outerHTML = this.renderReasoningPanel();
                            if (window.lucide) window.lucide.createIcons();
                        } else {
                            const body = getAiBody();
                            if (body) {
                                const newPanel = document.createElement('div');
                                newPanel.innerHTML = this.renderReasoningPanel();
                                body.parentElement.insertBefore(newPanel.firstElementChild, body);
                                if (window.lucide) window.lucide.createIcons();
                            }
                        }
                    },
                    this.sessionId,
                    currentAttachment?.type === 'document' ? currentAttachment.id : null,
                    currentAttachment?.type === 'image' ? currentAttachment.id : null
                );
            } catch (err) {
                this.reasoningSteps = [];
                this.isGenerating = false;
                this.render();
                this.setupEvents();
                this.bindAttachmentEvents();
            }
        });
    }

    bindAttachmentEvents() {
        // Suggestion chips
        this.querySelectorAll('.suggestion-chip').forEach(chip => {
            chip.addEventListener('click', () => {
                const spans = chip.querySelectorAll('span');
                const input = this.querySelector('#chat-input');
                if (input && spans.length >= 2) {
                    input.value = `${spans[0].textContent} ${spans[1].textContent}`;
                    input.dispatchEvent(new Event('input'));
                    input.focus();
                }
            });
        });

        const attachBtn = this.querySelector('#attach-btn');
        const attachMenu = this.querySelector('#attach-menu');
        const imgInput = this.querySelector('#upload-image');
        const docInput = this.querySelector('#upload-doc');
        const triggerImg = this.querySelector('#trigger-image-upload');
        const triggerDoc = this.querySelector('#trigger-doc-upload');
        const recBtn = this.querySelector('#record-audio-btn');
        const removeFileBtn = this.querySelector('#remove-file-btn');

        const closeMenu = () => {
            this.isMenuOpen = false;
            if (attachMenu) {
                attachMenu.style.transform = 'scale(0.94) translateY(4px)';
                attachMenu.style.opacity = '0';
                attachMenu.style.pointerEvents = 'none';
            }
        };

        if (attachBtn && attachMenu) {
            attachBtn.addEventListener('click', (e) => {
                e.stopPropagation();
                this.isMenuOpen = !this.isMenuOpen;
                if (this.isMenuOpen) {
                    attachMenu.style.transform = 'scale(1) translateY(0)';
                    attachMenu.style.opacity = '1';
                    attachMenu.style.pointerEvents = 'auto';
                } else { closeMenu(); }
            });
            document.addEventListener('click', (e) => {
                if (this.isMenuOpen && !attachBtn.contains(e.target) && !attachMenu.contains(e.target)) closeMenu();
            });
        }

        if (triggerImg && imgInput) triggerImg.addEventListener('click', (e) => { e.stopPropagation(); closeMenu(); imgInput.click(); });
        if (triggerDoc && docInput) triggerDoc.addEventListener('click', (e) => { e.stopPropagation(); closeMenu(); docInput.click(); });

        if (imgInput) imgInput.addEventListener('change', (e) => { e.stopPropagation(); this.handleUpload(e, 'image'); });
        if (docInput) docInput.addEventListener('change', (e) => { e.stopPropagation(); this.handleUpload(e, 'document'); });

        // Drag-and-drop
        const chatArea = this.querySelector('#chat-messages');
        if (chatArea) {
            chatArea.addEventListener('dragover', (e) => { e.preventDefault(); chatArea.style.outline = '2px dashed rgba(96,165,250,0.3)'; chatArea.style.borderRadius = '16px'; });
            chatArea.addEventListener('dragleave', () => { chatArea.style.outline = 'none'; });
            chatArea.addEventListener('drop', (e) => {
                e.preventDefault(); chatArea.style.outline = 'none';
                const file = e.dataTransfer.files[0];
                if (!file) return;
                const fakeEv = { target: { files: [file], value: '' }, stopPropagation: () => { } };
                this.handleUpload(fakeEv, file.type.startsWith('image/') ? 'image' : 'document');
            });
        }

        if (recBtn) recBtn.addEventListener('click', () => this.toggleRecording());
        if (removeFileBtn) removeFileBtn.addEventListener('click', () => {
            this.attachedFile = null;
            this.render(); this.setupEvents(); this.bindAttachmentEvents();
        });
    }

    showToast(msg, color = '#ef4444') {
        const toast = this.querySelector('#upload-toast');
        if (!toast) return;
        toast.textContent = msg;
        toast.style.background = color;
        toast.style.opacity = '1';
        clearTimeout(this._toastTimer);
        this._toastTimer = setTimeout(() => { toast.style.opacity = '0'; }, 3500);
    }

    async handleUpload(e, type) {
        e.stopPropagation?.();
        const file = e.target?.files?.[0];
        if (!file) return;

        this.isMenuOpen = false;
        this.isUploading = true;
        this.render(); this.setupEvents(); this.bindAttachmentEvents();

        try {
            const res = type === 'image' ? await uploadImage(file) : await uploadDocument(file);
            this.attachedFile = { id: res.id, name: res.filename || file.name, type };
            this.showToast(`✓ ${file.name} attached`, '#22c55e');
        } catch (err) {
            console.error(err);
            this.showToast(`Upload failed: ${err.message || 'Unknown error'}`);
        } finally {
            this.isUploading = false;
            if (e.target) e.target.value = '';
            this.render(); this.setupEvents(); this.bindAttachmentEvents();
        }
    }

    async toggleRecording() {
        if (this.isRecording) {
            if (this.mediaRecorder?.state !== 'inactive') this.mediaRecorder.stop();
            this.isRecording = false;
            this.render(); this.setupEvents(); this.bindAttachmentEvents();
            return;
        }
        try {
            const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
            this.mediaRecorder = new MediaRecorder(stream);
            this.audioChunks = [];
            this.mediaRecorder.ondataavailable = (e) => { if (e.data.size > 0) this.audioChunks.push(e.data); };
            this.mediaRecorder.onstop = async () => {
                const blob = new Blob(this.audioChunks, { type: 'audio/webm' });
                stream.getTracks().forEach(t => t.stop());
                this.isUploading = true;
                this.render(); this.setupEvents(); this.bindAttachmentEvents();
                try {
                    const res = await uploadAudioForTranscription(blob);
                    const input = this.querySelector('#chat-input');
                    if (input) {
                        input.value = input.value ? input.value + ' ' + res.text : res.text;
                        input.dispatchEvent(new Event('input'));
                        input.focus();
                    }
                } catch (err) {
                    this.showToast('Transcription failed');
                } finally {
                    this.isUploading = false;
                    this.render(); this.setupEvents(); this.bindAttachmentEvents();
                }
            };
            this.mediaRecorder.start();
            this.isRecording = true;
            this.render(); this.setupEvents(); this.bindAttachmentEvents();
        } catch (err) {
            this.showToast('Could not access microphone.');
        }
    }

    scrollToBottom() {
        const c = this.querySelector('#chat-messages');
        if (c) c.scrollTop = c.scrollHeight;
    }
}

customElements.define('chat-interface', ChatInterface);
