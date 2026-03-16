class AppLayout extends HTMLElement {
    constructor() {
        super();
        this.isAdminMode = false;
        this.sessions = []; // Chat sessions from backend
    }

    connectedCallback() {
        if (!this.initialContent) {
            this.initialContent = this.innerHTML;
        }
        this.render();
        this.setupEventListeners();
        this.loadSessions(); // Load sessions from backend
    }

    async loadSessions() {
        try {
            const res = await fetch('/api/chat/sessions');
            if (res.ok) {
                this.sessions = await res.json();
                this.renderSessionList();
            }
        } catch (e) {
            // Sessions are optional — if API fails, just show empty history
        }
    }

    renderSessionList() {
        const container = this.querySelector('#session-list');
        if (!container) return;

        if (this.sessions.length === 0) {
            container.innerHTML = `<p style="font-size:12px;color:#525252;padding:4px 8px;font-style:italic;">No previous conversations</p>`;
            return;
        }

        const today = new Date();
        const yesterday = new Date(today); yesterday.setDate(today.getDate() - 1);
        const lastWeek = new Date(today); lastWeek.setDate(today.getDate() - 7);

        const groups = { Today: [], Yesterday: [], 'Previous 7 days': [], Older: [] };
        this.sessions.forEach(s => {
            const d = new Date(s.updated_at);
            if (d.toDateString() === today.toDateString()) groups.Today.push(s);
            else if (d.toDateString() === yesterday.toDateString()) groups.Yesterday.push(s);
            else if (d >= lastWeek) groups['Previous 7 days'].push(s);
            else groups.Older.push(s);
        });

        let html = '';
        for (const [label, items] of Object.entries(groups)) {
            if (items.length === 0) continue;
            html += `<p style="font-size:11.5px;font-weight:600;color:#525252;padding:10px 8px 3px;margin:0;letter-spacing:0.05em;text-transform:uppercase;">${label}</p>`;
            for (const s of items) {
                const title = s.title || 'Untitled chat';
                const truncated = title.length > 26 ? title.slice(0, 26) + '…' : title;
                html += `
                    <div class="session-row" data-id="${s.id}"
                        style="display:flex;align-items:center;border-radius:8px;padding:1px 2px;transition:background 0.1s;position:relative;"
                        onmouseenter="this.style.background='#2a2a2a';this.querySelector('.del-btn').style.opacity='1';"
                        onmouseleave="this.style.background='transparent';this.querySelector('.del-btn').style.opacity='0';">
                        <button class="session-link" data-id="${s.id}"
                            style="display:flex;align-items:center;gap:9px;padding:7px 8px;border-radius:7px;flex:1;background:none;border:none;cursor:pointer;font-family:inherit;color:#a3a3a3;font-size:13.5px;text-align:left;min-width:0;">
                            <i data-lucide="message-square" style="width:14px;height:14px;flex-shrink:0;opacity:0.45;"></i>
                            <span style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${truncated}</span>
                        </button>
                        <button class="del-btn" data-id="${s.id}" title="Delete"
                            style="flex-shrink:0;width:28px;height:28px;border-radius:7px;background:none;border:none;cursor:pointer;display:flex;align-items:center;justify-content:center;color:#676767;opacity:0;transition:opacity 0.15s,color 0.1s,background 0.1s;margin-right:3px;"
                            onmouseover="this.style.color='#ef4444';this.style.background='rgba(239,68,68,0.08)';"
                            onmouseout="this.style.color='#676767';this.style.background='none';">
                            <i data-lucide="trash-2" style="width:13px;height:13px;pointer-events:none;"></i>
                        </button>
                    </div>
                `;
            }
        }

        // Clear all history button
        if (this.sessions.length > 0) {
            html += `
                <div style="margin-top:8px;padding-top:8px;border-top:1px solid rgba(255,255,255,0.05);">
                    <button id="clear-all-btn"
                        style="display:flex;align-items:center;gap:8px;padding:7px 8px;border-radius:8px;background:none;border:none;cursor:pointer;font-family:inherit;color:#525252;font-size:12.5px;width:100%;text-align:left;transition:color 0.1s,background 0.1s;"
                        onmouseover="this.style.color='#ef4444';this.style.background='rgba(239,68,68,0.06)';"
                        onmouseout="this.style.color='#525252';this.style.background='none';">
                        <i data-lucide="trash" style="width:13px;height:13px;"></i>
                        Clear all history
                    </button>
                </div>
            `;
        }

        container.innerHTML = html;
        if (window.lucide) window.lucide.createIcons();
        this.bindSessionLinks();
    }

    bindSessionLinks() {
        this.querySelectorAll('.session-link').forEach(btn => {
            btn.addEventListener('click', () => this.loadSession(btn.dataset.id));
        });
        this.querySelectorAll('.del-btn').forEach(btn => {
            btn.addEventListener('click', (e) => {
                e.stopPropagation();
                this.deleteSession(btn.dataset.id);
            });
        });
        const clearAll = this.querySelector('#clear-all-btn');
        if (clearAll) {
            clearAll.addEventListener('click', () => {
                if (confirm('Delete all chat history? This cannot be undone.')) {
                    Promise.all(this.sessions.map(s => fetch(`/api/chat/sessions/${s.id}`, { method: 'DELETE' })))
                        .then(() => { this.sessions = []; this.renderSessionList(); })
                        .catch(() => { });
                }
            });
        }
    }

    async deleteSession(sessionId) {
        // Optimistic removal
        this.sessions = this.sessions.filter(s => s.id !== sessionId);
        this.renderSessionList();
        try {
            await fetch(`/api/chat/sessions/${sessionId}`, { method: 'DELETE' });
        } catch (e) {
            // If server delete fails, reload from server
            this.loadSessions();
        }
    }


    async loadSession(sessionId) {
        try {
            const res = await fetch(`/api/chat/sessions/${sessionId}`);
            if (!res.ok) return;
            const data = await res.json();
            const chatEl = document.querySelector('chat-interface');
            if (chatEl) {
                chatEl.sessionId = sessionId;
                chatEl.messages = data.messages.map(m => ({
                    role: m.role,
                    content: m.content
                }));
                chatEl.render();
                chatEl.setupEvents();
                chatEl.bindAttachmentEvents();
            }
            if (window.history) window.history.pushState({}, '', '/');
            this.updateActiveRoute('/');
        } catch (e) {
            console.error('Failed to load session:', e);
        }
    }

    render() {
        this.innerHTML = `
            <div style="display:flex; height:100vh; width:100%; background:#212121; color:#ececec; font-family:'Inter',system-ui,sans-serif; overflow:hidden;">

                <!-- Sidebar -->
                <aside style="width:260px; min-width:260px; background:#171717; display:flex; flex-direction:column; height:100%; padding:8px 0; position:relative; z-index:20;">

                    <!-- Top: Logo + New Chat -->
                    <div style="display:flex; align-items:center; justify-content:space-between; padding:8px 12px 4px; margin-bottom:4px;">
                        <div style="display:flex; align-items:center; gap:10px; padding:6px 8px; border-radius:10px; cursor:pointer; transition:background 0.15s; flex:1;"
                            onmouseover="this.style.background='#2f2f2f'" onmouseout="this.style.background='transparent'">
                            <div style="width:32px; height:32px; border-radius:50%; background:#ffffff; display:flex; align-items:center; justify-content:center; flex-shrink:0;">
                                <i data-lucide="activity" style="width:18px; height:18px; color:#000;"></i>
                            </div>
                            <span style="font-size:15px; font-weight:600; color:#ececec;">ClinicalAI Pro</span>
                        </div>
                        <button id="new-chat-btn" title="New chat"
                            style="width:36px; height:36px; border-radius:8px; background:none; border:none; cursor:pointer; display:flex; align-items:center; justify-content:center; color:#b4b4b4; flex-shrink:0; transition:background 0.15s, color 0.15s;"
                            onmouseover="this.style.background='#2f2f2f'; this.style.color='#ececec';" onmouseout="this.style.background='none'; this.style.color='#b4b4b4';">
                            <i data-lucide="square-pen" style="width:18px; height:18px;"></i>
                        </button>
                    </div>

                    <!-- Clinical Chat link (always visible) -->
                    <div style="padding:0 8px; margin-bottom:4px;">
                        <a href="/" class="nav-link" style="display:flex; align-items:center; gap:12px; padding:8px 10px; border-radius:8px; text-decoration:none; color:#ececec; font-size:14px; transition:background 0.15s; background:#2f2f2f;"
                            onmouseover="this.style.background='#2f2f2f'" onmouseout="">
                            <i data-lucide="message-square" style="width:16px; height:16px; flex-shrink:0;"></i>
                            <span style="overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">New Clinical Chat</span>
                        </a>
                    </div>

                    <!-- Session History -->
                    <nav style="flex:1; overflow-y:auto; padding:4px 8px; display:flex; flex-direction:column; gap:1px;">
                        <div id="session-list" style="display:flex; flex-direction:column;">
                            <p style="font-size:12px; color:#525252; padding:4px 8px; font-style:italic;">Loading history...</p>
                        </div>

                        <!-- Admin Section -->
                        <div id="admin-nav" style="overflow:hidden; transition:max-height 0.3s ease, opacity 0.3s ease; max-height:${this.isAdminMode ? '300px' : '0'}; opacity:${this.isAdminMode ? '1' : '0'};">
                            <div style="height:1px; background:rgba(255,255,255,0.07); margin:4px 0 8px;"></div>
                            <p style="font-size:12px; font-weight:500; color:#676767; padding:0 8px 4px; margin:0;">System Admin</p>
                            <a href="/evaluations" class="nav-link" style="display:flex; align-items:center; gap:12px; padding:8px 10px; border-radius:8px; text-decoration:none; color:#b4b4b4; font-size:14px; transition:background 0.15s;"
                                onmouseover="this.style.background='#2f2f2f'; this.style.color='#ececec'" onmouseout="this.style.background='transparent'; this.style.color='#b4b4b4'">
                                <i data-lucide="bar-chart-2" style="width:16px; height:16px; flex-shrink:0;"></i>
                                <span>Health Analytics</span>
                            </a>
                            <a href="/graph" class="nav-link" style="display:flex; align-items:center; gap:12px; padding:8px 10px; border-radius:8px; text-decoration:none; color:#b4b4b4; font-size:14px; transition:background 0.15s;"
                                onmouseover="this.style.background='#2f2f2f'; this.style.color='#ececec'" onmouseout="this.style.background='transparent'; this.style.color='#b4b4b4'">
                                <i data-lucide="git-branch" style="width:16px; height:16px; flex-shrink:0;"></i>
                                <span>Knowledge Graph</span>
                            </a>
                        </div>
                    </nav>

                    <!-- Bottom: Admin Mode Toggle -->
                    <div style="padding:8px; border-top:1px solid rgba(255,255,255,0.06); margin-top:4px;">
                        <button id="mode-toggle"
                            style="width:100%; display:flex; align-items:center; gap:12px; padding:10px; border-radius:8px; background:none; border:none; cursor:pointer; color:#b4b4b4; font-size:14px; font-family:inherit; text-align:left; transition:background 0.15s, color 0.15s;"
                            onmouseover="this.style.background='#2f2f2f'; this.style.color='#ececec'" onmouseout="this.style.background='none'; this.style.color='#b4b4b4'">
                            <i data-lucide="${this.isAdminMode ? 'shield' : 'shield-off'}" style="width:16px; height:16px; flex-shrink:0; ${this.isAdminMode ? 'color:#f59e0b;' : ''}"></i>
                            <span>${this.isAdminMode ? 'Exit Admin Mode' : 'Admin Mode'}</span>
                        </button>
                    </div>
                </aside>

                <!-- Main Content -->
                <main style="flex:1; overflow:hidden; position:relative; background:#212121;">
                    ${this.initialContent}
                </main>
            </div>
        `;

        if (window.lucide) window.lucide.createIcons();
        this.updateActiveRoute(window.location.pathname);
    }

    setupEventListeners() {
        const toggleBtn = this.querySelector('#mode-toggle');
        if (toggleBtn) {
            toggleBtn.addEventListener('click', () => {
                this.isAdminMode = !this.isAdminMode;
                const pageContent = document.getElementById('page-content');
                if (pageContent) this.initialContent = pageContent.outerHTML;
                this.render();
                this.setupEventListeners();
                this.renderSessionList();
            });
        }

        const newChatBtn = this.querySelector('#new-chat-btn');
        if (newChatBtn) {
            newChatBtn.addEventListener('click', () => {
                const chatEl = document.querySelector('chat-interface');
                if (chatEl) {
                    chatEl.messages = [];
                    chatEl.attachedFile = null;
                    chatEl.isGenerating = false;
                    chatEl.sessionId = null;
                    chatEl.render();
                    chatEl.setupEvents();
                    chatEl.bindAttachmentEvents();
                }
                if (window.history) window.history.pushState({}, '', '/');
                this.updateActiveRoute('/');
            });
        }
    }

    updateActiveRoute(path) {
        this.querySelectorAll('a.nav-link').forEach(link => {
            const href = link.getAttribute('href');
            const isActive = href === path;
            link.style.background = isActive ? '#2f2f2f' : 'transparent';
            link.style.color = isActive ? '#ececec' : '#b4b4b4';
            link.style.fontWeight = isActive ? '500' : 'normal';
        });

        if (!this.isAdminMode && (path === '/evaluations' || path === '/graph')) {
            this.isAdminMode = true;
            const pageContent = document.getElementById('page-content');
            if (pageContent) this.initialContent = pageContent.outerHTML;
            this.render();
            this.setupEventListeners();
            this.renderSessionList();
        }
    }

    // Called by chat-interface after a message is sent to refresh the history
    refreshSessions() {
        this.loadSessions();
    }
}

customElements.define('app-layout', AppLayout);
