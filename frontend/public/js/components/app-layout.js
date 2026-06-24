import {
    AuthService,
    deleteChatSession,
    getChatSession,
    listChatSessions,
    showToast,
} from '../api.js';
import { modal } from '../lib/modal.js';
import { registerGlobalShortcuts } from '../lib/shortcuts.js';
import { navigate } from '../router.js';

const ACTIVE_SESSION_KEY = 'clinical_active_session_id';
const SESSION_SEARCH_KEY = 'clinical_session_search';
const SESSION_TITLE_OVERRIDES_KEY = 'clinical_session_title_overrides';
const SESSION_PAYLOAD_KEY = 'clinical_loaded_session_payload';
const ONBOARDING_KEY = 'onboarded';
const ONBOARDING_ROOT_ID = 'global-onboarding-root';
	const ONBOARDING_STEPS = [
	    {
	        route: '/sources',
	        target: '#upload-zone',
	        title: 'Add source evidence to the case',
	        body: 'Upload clinical source material first so answers, drafts, and citations stay grounded.',
	        cta: 'Next',
	    },
	    {
	        route: '/workspace',
	        target: '#chat-input',
	        title: 'Ask and draft from the case',
	        body: 'Use the workspace to ask focused questions, verify evidence, and generate clinical outputs.',
	        cta: 'Next',
	    },
        {
	        route: null,
	        target: '[data-route-link][href="/graph"]',
	        title: 'Inspect graph context',
	        body: 'Open the graph workspace to inspect relationships between patients, conditions, drugs, labs, and source provenance.',
	        cta: 'Finish',
	    },
	];

function escapeHtml(value = '') {
    return String(value)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}

class AppLayout extends HTMLElement {
    constructor() {
        super();
        this.currentRoute = window.location.pathname;
        this.user = AuthService.getUser();
        this.sessions = [];
        this.loadingSessions = false;
        this.sessionSearchTerm = window.sessionStorage.getItem(SESSION_SEARCH_KEY) || '';
        this.activeSessionId = window.sessionStorage.getItem(ACTIVE_SESSION_KEY) || '';
        this.titleOverrides = this.loadTitleOverrides();
        this.editingSessionId = '';
        this.onboardingActive = false;
        this.onboardingStepIndex = -1;
        this.onboardingTarget = null;
        this.onboardingRect = null;
        this._bootstrapSequence = 0;
    }

    connectedCallback() {
        registerGlobalShortcuts({
            navigate,
            onNewChat: () => this.startNewChat(),
        });
        this.setRoute(window.location.pathname);
        this.attachGlobalListeners();
        this.bootstrap();
    }

    disconnectedCallback() {
        window.removeEventListener('clinical:auth-changed', this._authChangedHandler);
        window.removeEventListener('clinical:sessions-changed', this._sessionsChangedHandler);
        window.removeEventListener('clinical:new-chat', this._newChatHandler);
        window.removeEventListener('clinical:session-search-term', this._sessionSearchHandler);
        window.removeEventListener('clinical:route-rendered', this._routeRenderedHandler);
        window.removeEventListener('resize', this._resizeHandler);
        this.clearOnboardingHighlight();
        this.renderOnboardingOverlay();
    }

    attachGlobalListeners() {
        if (!this._authChangedHandler) {
            this._authChangedHandler = async (event) => {
                this.user = AuthService.getUser();
                const authenticated = Boolean(event?.detail?.authenticated);

                if (!authenticated) {
                    if (this.isAuthRoute()) {
                        this.render();
                        this.setupEventListeners();
                    }
                    return;
                }

                if (this.isAuthRoute()) {
                    return;
                }

                this.render();
                this.setupEventListeners();
                await this.bootstrap();
            };
            window.addEventListener('clinical:auth-changed', this._authChangedHandler);
        }

        if (!this._sessionsChangedHandler) {
            this._sessionsChangedHandler = (event) => {
                const sessionId = event.detail?.sessionId;
                if (sessionId) {
                    this.activeSessionId = String(sessionId);
                    window.sessionStorage.setItem(ACTIVE_SESSION_KEY, this.activeSessionId);
                }
                this.loadSessions();
            };
            window.addEventListener('clinical:sessions-changed', this._sessionsChangedHandler);
        }

        if (!this._newChatHandler) {
            this._newChatHandler = () => {
                this.activeSessionId = '';
                this.editingSessionId = '';
                window.sessionStorage.removeItem(ACTIVE_SESSION_KEY);
                window.sessionStorage.removeItem(SESSION_PAYLOAD_KEY);
                this.renderSessionList();
            };
            window.addEventListener('clinical:new-chat', this._newChatHandler);
        }

        if (!this._sessionSearchHandler) {
            this._sessionSearchHandler = (event) => {
                this.sessionSearchTerm = event.detail?.term || '';
                window.sessionStorage.setItem(SESSION_SEARCH_KEY, this.sessionSearchTerm);
                this.renderSessionList();
                const input = this.querySelector('#session-search');
                if (input) input.value = this.sessionSearchTerm;
            };
            window.addEventListener('clinical:session-search-term', this._sessionSearchHandler);
        }

        if (!this._routeRenderedHandler) {
            this._routeRenderedHandler = () => this.scheduleOnboardingSync();
            window.addEventListener('clinical:route-rendered', this._routeRenderedHandler);
        }

        if (!this._resizeHandler) {
            this._resizeHandler = () => this.scheduleOnboardingSync();
            window.addEventListener('resize', this._resizeHandler);
        }
    }

	    async bootstrap() {
	        if (this.isAuthRoute()) return;
	        const bootstrapSequence = ++this._bootstrapSequence;
	        const routeAtStart = this.currentRoute;
	        this.user = await AuthService.ensureAuthenticated();
        if (!this.user) return;
        if (bootstrapSequence !== this._bootstrapSequence || routeAtStart !== this.currentRoute || this.isAuthRoute()) {
            return;
        }
	        const existingPageContent = this.querySelector('#page-content');
	        const existingRouteContent = existingPageContent?.innerHTML || '';
	        this.render();
	        if (existingRouteContent.trim()) {
	            const freshPageContent = this.querySelector('#page-content');
	            if (freshPageContent && !freshPageContent.innerHTML.trim()) {
	                freshPageContent.innerHTML = existingRouteContent;
	            }
	        }
	        if (bootstrapSequence !== this._bootstrapSequence || routeAtStart !== this.currentRoute || this.isAuthRoute()) {
	            return;
	        }
        this.setupEventListeners();
        await this.loadSessions();
        if (bootstrapSequence !== this._bootstrapSequence || routeAtStart !== this.currentRoute || this.isAuthRoute()) {
            return;
        }
        this.ensureCurrentRouteRendered();
        this.maybeStartOnboarding();
    }

    isAuthRoute() {
        return false;
    }

    isAdmin() {
        return this.user?.role === 'admin';
    }

    canAccessImages() {
        return ['admin', 'physician'].includes(this.user?.role);
    }

    startNewChat() {
        this.activeSessionId = '';
        this.editingSessionId = '';
        window.sessionStorage.removeItem(ACTIVE_SESSION_KEY);
        window.sessionStorage.removeItem(SESSION_PAYLOAD_KEY);
        window.dispatchEvent(new CustomEvent('clinical:new-chat'));
        navigate('/workspace');
    }

    setRoute(path) {
        this._bootstrapSequence += 1;
        this.currentRoute = path;
        if (this.isAuthRoute()) {
            this.finishOnboarding({ persist: false });
        }
        this.render();
        this.setupEventListeners();
    }

    updateActiveRoute(path) {
        this.currentRoute = path;
        const links = this.querySelectorAll('[data-route-link]');
        links.forEach((link) => {
            const active = link.getAttribute('href') === path;
            link.classList.toggle('is-active', active);
        });
        this.renderSessionList();
    }

    ensureCurrentRouteRendered() {
        const pageContent = this.querySelector('#page-content');
        if (!pageContent || pageContent.children.length > 0 || pageContent.textContent.trim()) return;
        queueMicrotask(() => {
            const target = `${window.location.pathname}${window.location.search}`;
            navigate(target, { replace: true });
        });
    }

    loadTitleOverrides() {
        try {
            return JSON.parse(window.sessionStorage.getItem(SESSION_TITLE_OVERRIDES_KEY) || '{}');
        } catch (_) {
            return {};
        }
    }

    persistTitleOverrides() {
        window.sessionStorage.setItem(SESSION_TITLE_OVERRIDES_KEY, JSON.stringify(this.titleOverrides));
    }

    getSessionTitle(session) {
        const override = this.titleOverrides?.[session.id];
        if (typeof override === 'string' && override.trim()) return override.trim();
        return session.title || 'Untitled session';
    }

    async loadSessions() {
        if (this.isAuthRoute() || (!AuthService.getToken() && !AuthService.getRefreshToken())) return;
        this.loadingSessions = true;
        this.renderSessionList();
        try {
            this.sessions = await listChatSessions();
        } catch (_) {
            this.sessions = [];
        } finally {
            this.loadingSessions = false;
            this.renderSessionList();
        }
    }

    getFilteredSessions() {
        const query = this.sessionSearchTerm.trim().toLowerCase();
        if (!query) return this.sessions;
        return this.sessions.filter((session) => this.getSessionTitle(session).toLowerCase().includes(query));
    }

    groupSessions(sessions) {
        const today = new Date();
        const yesterday = new Date(today);
        yesterday.setDate(today.getDate() - 1);
        const lastWeek = new Date(today);
        lastWeek.setDate(today.getDate() - 7);

        const groups = { Today: [], Yesterday: [], 'Previous 7 Days': [], Older: [] };
        sessions.forEach((session) => {
            const updatedAt = new Date(session.updated_at);
            if (updatedAt.toDateString() === today.toDateString()) groups.Today.push(session);
            else if (updatedAt.toDateString() === yesterday.toDateString()) groups.Yesterday.push(session);
            else if (updatedAt >= lastWeek) groups['Previous 7 Days'].push(session);
            else groups.Older.push(session);
        });
        return groups;
    }

    renderSessionList() {
        const container = this.querySelector('#session-list');
        if (!container) return;

        if (this.loadingSessions) {
            container.innerHTML = `
                <div class="session-group">
                    ${Array.from({ length: 3 }).map(() => `
                        <div class="session-item">
                            <div class="session-item__open">
                                <div class="skeleton" style="width:24px;height:24px;border-radius:8px;"></div>
                                <div class="skeleton" style="width:100%;height:16px;"></div>
                            </div>
                            <div class="skeleton" style="width:34px;height:34px;border-radius:12px;"></div>
                        </div>
                    `).join('')}
                </div>
            `;
            return;
        }

        const filtered = this.getFilteredSessions();
        if (filtered.length === 0) {
            container.innerHTML = `<div class="empty-inline">${this.sessionSearchTerm ? 'No sessions match this search.' : 'No previous conversations yet.'}</div>`;
            return;
        }

        const groups = this.groupSessions(filtered);
        container.innerHTML = Object.entries(groups)
            .filter(([, items]) => items.length > 0)
            .map(([label, items]) => `
                <section class="session-group">
                    <h3 class="session-group__title">${escapeHtml(label)}</h3>
                    ${items.map((session) => {
                        const isEditing = this.editingSessionId === session.id;
                        const title = this.getSessionTitle(session);
                        return `
                            <div class="session-item ${this.activeSessionId === session.id ? 'is-active' : ''}" data-session-row="${escapeHtml(session.id)}">
                                <button type="button" class="session-item__open" data-open-session="${escapeHtml(session.id)}">
                                    <span class="session-item__icon" aria-hidden="true">#</span>
                                    ${
                                        isEditing
                                            ? `<input id="rename-session-input" class="session-item__rename" data-rename-session="${escapeHtml(session.id)}" value="${escapeHtml(title)}" maxlength="80" />`
                                            : `<span class="session-item__title" data-session-title="${escapeHtml(session.id)}">${escapeHtml(title)}</span>`
                                    }
                                </button>
                                <button type="button" class="session-item__delete" data-delete-session="${escapeHtml(session.id)}" aria-label="Delete session">×</button>
                            </div>
                        `;
                    }).join('')}
                </section>
            `).join('');

        this.bindSessionControls();
    }

    bindSessionControls() {
        this.querySelectorAll('[data-open-session]').forEach((button) => {
            button.addEventListener('click', async () => {
                await this.openSession(button.getAttribute('data-open-session'));
            });
        });

        this.querySelectorAll('[data-delete-session]').forEach((button) => {
            button.addEventListener('click', async (event) => {
                event.stopPropagation();
                await this.handleDeleteSession(button.getAttribute('data-delete-session'));
            });
        });

        this.querySelectorAll('[data-session-title]').forEach((titleNode) => {
            titleNode.addEventListener('dblclick', (event) => {
                event.stopPropagation();
                this.editingSessionId = titleNode.getAttribute('data-session-title') || '';
                this.renderSessionList();
                const input = this.querySelector('#rename-session-input');
                if (input) {
                    input.focus();
                    input.select();
                }
            });
        });

        const renameInput = this.querySelector('#rename-session-input');
        if (renameInput) {
            const commit = () => {
                const sessionId = renameInput.getAttribute('data-rename-session') || '';
                const value = renameInput.value.trim();
                if (sessionId && value) {
                    this.titleOverrides[sessionId] = value;
                    this.persistTitleOverrides();
                }
                this.editingSessionId = '';
                this.renderSessionList();
            };
            renameInput.addEventListener('keydown', (event) => {
                if (event.key === 'Enter') commit();
                if (event.key === 'Escape') {
                    this.editingSessionId = '';
                    this.renderSessionList();
                }
            });
            renameInput.addEventListener('blur', commit);
        }
    }

    async openSession(sessionId) {
        if (!sessionId) return;
        try {
            const payload = await getChatSession(sessionId);
            this.activeSessionId = String(sessionId);
            window.sessionStorage.setItem(ACTIVE_SESSION_KEY, this.activeSessionId);
            window.sessionStorage.setItem(SESSION_PAYLOAD_KEY, JSON.stringify(payload));
            await navigate('/workspace');
            requestAnimationFrame(() => {
                window.dispatchEvent(new CustomEvent('clinical:session-loaded', { detail: payload }));
            });
        } catch (error) {
            showToast(error.message || 'Unable to open chat session.', 'error');
        }
    }

    async handleDeleteSession(sessionId) {
        if (!sessionId) return;
        const confirmed = await modal.confirm('Delete this chat session? This cannot be undone.', {
            title: 'Delete Chat Session',
            confirmLabel: 'Delete session',
            destructive: true,
        });
        if (!confirmed) return;

        try {
            await deleteChatSession(sessionId);
            this.sessions = this.sessions.filter((session) => session.id !== sessionId);
            delete this.titleOverrides[sessionId];
            this.persistTitleOverrides();
            if (this.activeSessionId === sessionId) {
                this.activeSessionId = '';
                window.sessionStorage.removeItem(ACTIVE_SESSION_KEY);
                window.sessionStorage.removeItem(SESSION_PAYLOAD_KEY);
                window.dispatchEvent(new CustomEvent('clinical:new-chat'));
            }
            this.renderSessionList();
            showToast('Chat session deleted.', 'success', 2500);
        } catch (error) {
            showToast(error.message || 'Unable to delete session.', 'error');
        }
    }

    renderSidebar() {
        return `
            <aside class="shell-sidebar">
                <div class="sidebar-brand">
                    <div class="brand-mark" aria-hidden="true">∿</div>
                    <div class="brand-copy">
                        <div class="brand-name">ClinicalAI Pro</div>
                        <div class="brand-meta">${escapeHtml(this.user?.email || 'Local workspace')}</div>
                    </div>
                    <button type="button" class="icon-button icon-button--ghost" id="new-chat-btn" aria-label="New chat">+</button>
                </div>

                <div class="sidebar-search">
                    <input id="session-search" class="field-input" type="search" placeholder="Search sessions" value="${escapeHtml(this.sessionSearchTerm)}" />
                </div>

                <nav class="sidebar-nav">
                    <a href="/" data-route-link class="nav-link ${this.currentRoute === '/' ? 'is-active' : ''}">Home Dashboard</a>
                    <a href="/workspace" data-route-link class="nav-link ${this.currentRoute === '/workspace' ? 'is-active' : ''}">Ask & Draft</a>
                    <a href="/sources" data-route-link class="nav-link ${this.currentRoute === '/sources' ? 'is-active' : ''}">Source Library</a>
                    ${this.canAccessImages() ? `<a href="/images" data-route-link class="nav-link ${this.currentRoute === '/images' ? 'is-active' : ''}">Imaging Review</a>` : ''}
                    <a href="/reports" data-route-link class="nav-link ${this.currentRoute === '/reports' ? 'is-active' : ''}">Reports</a>
                    <a href="/workflows" data-route-link class="nav-link ${this.currentRoute === '/workflows' ? 'is-active' : ''}">AI Workflows</a>
                    <a href="/graph" data-route-link class="nav-link ${this.currentRoute === '/graph' ? 'is-active' : ''}">Knowledge Graph</a>
                    ${this.isAdmin() ? `
                        <div class="nav-divider"></div>
                        <div class="nav-section-label">Quality & Ops</div>
                        <a href="/admin" data-route-link class="nav-link ${this.currentRoute === '/admin' ? 'is-active' : ''}">Quality & Evals</a>
                    ` : ''}
                </nav>

                <section class="sidebar-history">
                    <div class="sidebar-history__header">
                        <span>Recent Sessions</span>
                    </div>
                    <div id="session-list" class="session-list"></div>
                </section>

                <footer class="sidebar-footer">
                    <div class="user-card">
                        <div class="user-card__name">${escapeHtml(this.user?.name || 'Local UI Mode')}</div>
                        <div class="user-card__email">${escapeHtml(this.user?.email || 'No browser login required')}</div>
                        <div class="role-badge">${escapeHtml(this.user?.role || 'viewer')}</div>
                    </div>
                    <div style="display:flex;gap:8px;">
                        <button type="button" id="theme-toggle-btn" class="button button--secondary" style="flex:1;min-height:38px;padding:0 8px;font-size:0.85rem;" aria-label="Toggle light/dark mode">🌓 Theme</button>
                    </div>
                </footer>
            </aside>
        `;
    }

    renderAuthShell() {
        this.innerHTML = `
            <div class="auth-shell">
                <main class="auth-shell__content">
                    <div id="page-content" class="page-content"></div>
                </main>
            </div>
        `;
    }

    renderAppShell() {
        this.innerHTML = `
            <div class="app-shell">
                ${this.renderSidebar()}
                <main class="shell-main">
                    <div id="page-content" class="page-content"></div>
                </main>
            </div>
        `;
        this.renderSessionList();
    }

    render() {
        if (this.isAuthRoute()) {
            this.renderAuthShell();
        } else {
            this.renderAppShell();
        }
    }

    setupEventListeners() {
        if (this.isAuthRoute()) return;

        const searchInput = this.querySelector('#session-search');
        if (searchInput) {
            searchInput.addEventListener('input', () => {
                this.sessionSearchTerm = searchInput.value;
                window.sessionStorage.setItem(SESSION_SEARCH_KEY, this.sessionSearchTerm);
                this.renderSessionList();
            });
        }

        const newChatButton = this.querySelector('#new-chat-btn');
        if (newChatButton) {
            newChatButton.addEventListener('click', () => this.startNewChat());
        }

        const themeToggleBtn = this.querySelector('#theme-toggle-btn');
        if (themeToggleBtn) {
            themeToggleBtn.addEventListener('click', () => {
                const isLight = document.documentElement.classList.toggle('light-theme');
                window.localStorage.setItem('clinical_theme', isLight ? 'light' : 'dark');
                window.dispatchEvent(new CustomEvent('clinical:theme-changed', { detail: { theme: isLight ? 'light' : 'dark' } }));
            });
        }
    }

    refreshSessions() {
        this.loadSessions();
    }

    maybeStartOnboarding() {
        if (this.isAuthRoute()) return;
        if (window.localStorage.getItem(ONBOARDING_KEY) === 'true') {
            this.finishOnboarding({ persist: false });
            return;
        }
        if (this.onboardingActive) {
            this.scheduleOnboardingSync();
            return;
        }
        this.onboardingActive = true;
        this.onboardingStepIndex = 0;
        this.goToOnboardingStep();
    }

    goToOnboardingStep() {
        const step = ONBOARDING_STEPS[this.onboardingStepIndex];
        if (!step) {
            this.finishOnboarding();
            return;
        }

        if (step.route && window.location.pathname !== step.route) {
            navigate(step.route);
            return;
        }

        this.scheduleOnboardingSync();
    }

    scheduleOnboardingSync() {
        if (!this.onboardingActive) return;
        window.cancelAnimationFrame(this._onboardingFrame);
        this._onboardingFrame = window.requestAnimationFrame(() => this.syncOnboardingTarget());
    }

    clearOnboardingHighlight() {
        if (this.onboardingTarget) {
            this.onboardingTarget.classList.remove('onboarding-highlight');
            this.onboardingTarget.removeAttribute('data-onboarding-active');
        }
        this.onboardingTarget = null;
        this.onboardingRect = null;
    }

    syncOnboardingTarget() {
        if (!this.onboardingActive) {
            this.renderOnboardingOverlay();
            return;
        }

        const step = ONBOARDING_STEPS[this.onboardingStepIndex];
        if (!step) {
            this.finishOnboarding();
            return;
        }

        const target = document.querySelector(step.target);
        if (!target) {
            window.setTimeout(() => this.scheduleOnboardingSync(), 140);
            return;
        }

        this.clearOnboardingHighlight();
        this.onboardingTarget = target;
        target.classList.add('onboarding-highlight');
        target.setAttribute('data-onboarding-active', 'true');
        target.scrollIntoView({ block: 'nearest', behavior: 'smooth' });

        const rect = target.getBoundingClientRect();
        this.onboardingRect = {
            top: Math.max(12, rect.top - 10),
            left: Math.max(12, rect.left - 10),
            width: Math.max(80, rect.width + 20),
            height: Math.max(48, rect.height + 20),
            cardTop: Math.min(window.innerHeight - 200, Math.max(24, rect.bottom + 18)),
            cardLeft: Math.min(window.innerWidth - 380, Math.max(24, rect.left)),
        };
        this.renderOnboardingOverlay();
    }

    renderOnboardingOverlay() {
        let root = document.getElementById(ONBOARDING_ROOT_ID);
        if (!root) {
            root = document.createElement('div');
            root.id = ONBOARDING_ROOT_ID;
            document.body.appendChild(root);
        }

        if (!this.onboardingActive || this.onboardingStepIndex < 0 || !this.onboardingRect) {
            root.innerHTML = '';
            return;
        }

        const step = ONBOARDING_STEPS[this.onboardingStepIndex];
        const progress = `${this.onboardingStepIndex + 1}/${ONBOARDING_STEPS.length}`;
        root.innerHTML = `
            <div class="onboarding-shell" aria-hidden="true">
                <div class="onboarding-backdrop"></div>
                <div class="onboarding-spotlight" style="top:${this.onboardingRect.top}px; left:${this.onboardingRect.left}px; width:${this.onboardingRect.width}px; height:${this.onboardingRect.height}px;"></div>
                <section class="onboarding-card" style="top:${this.onboardingRect.cardTop}px; left:${this.onboardingRect.cardLeft}px;" aria-hidden="false">
                    <div class="onboarding-card__eyebrow">Guided Setup</div>
                    <div class="onboarding-card__title">${escapeHtml(step.title)}</div>
                    <div class="onboarding-card__copy">${escapeHtml(step.body)}</div>
                    <div class="onboarding-card__footer">
                        <div class="onboarding-card__progress">${escapeHtml(progress)}</div>
                        <div class="onboarding-card__actions">
                            <button type="button" class="button button--ghost" data-onboarding-skip>Skip</button>
                            <button type="button" class="button button--primary" data-onboarding-next>${escapeHtml(step.cta)}</button>
                        </div>
                    </div>
                </section>
            </div>
        `;

        root.querySelector('[data-onboarding-skip]')?.addEventListener('click', () => this.finishOnboarding());
        root.querySelector('[data-onboarding-next]')?.addEventListener('click', () => {
            if (this.onboardingStepIndex >= ONBOARDING_STEPS.length - 1) {
                this.finishOnboarding();
                return;
            }
            this.onboardingStepIndex += 1;
            this.goToOnboardingStep();
        });
    }

    finishOnboarding({ persist = true } = {}) {
        if (persist) window.localStorage.setItem(ONBOARDING_KEY, 'true');
        this.onboardingActive = false;
        this.onboardingStepIndex = -1;
        this.clearOnboardingHighlight();
        this.renderOnboardingOverlay();
    }
}

customElements.define('app-layout', AppLayout);
