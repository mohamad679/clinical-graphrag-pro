import { showToast, toast } from './lib/toast.js';

const AUTH_ACCESS_TOKEN_KEY = 'clinical_auth_access_token';
const AUTH_REFRESH_TOKEN_KEY = 'clinical_auth_refresh_token';
const AUTH_USER_KEY = 'clinical_auth_user';
const AUTH_SESSION_KEY = 'clinical_auth_session_id';
export const CHAT_ATTACHMENT_STORAGE_KEY = 'clinical_graphrag_pending_attachment';
export const CHAT_SESSION_PAYLOAD_KEY = 'clinical_loaded_session_payload';
export const CHAT_DRAFT_STORAGE_KEY = 'clinical_pending_draft';

const LOCAL_UI_USER = Object.freeze({
    id: 'local-ui',
    email: 'local-ui@clinical.local',
    name: 'Local UI Mode',
    role: 'admin',
    created_at: new Date(0).toISOString(),
    is_verified: true,
    must_change_password: false,
    session_id: 'local-ui',
});

const resolveApiBase = () => {
    if (typeof window === 'undefined') return '/api';
    const explicit = window.__CLINICAL_API_BASE__;
    if (typeof explicit === 'string' && explicit.trim()) {
        return explicit.replace(/\/+$/, '');
    }
    if (window.location.port === '3000') {
        return 'http://localhost:8000/api';
    }
    return `${window.location.origin}/api`;
};

export const API_BASE = resolveApiBase();

function apiAssetUrl(path = '') {
    if (!path || typeof path !== 'string') return path;
    if (path.startsWith('http://') || path.startsWith('https://') || path.startsWith('data:')) return path;
    if (!path.startsWith('/api/')) return path;
    return `${API_BASE}${path.slice('/api'.length)}`;
}

function normalizeImagePayload(image) {
    if (!image || typeof image !== 'object') return image;
    return {
        ...image,
        image_url: apiAssetUrl(image.image_url || ''),
        thumbnail_url: apiAssetUrl(image.thumbnail_url || ''),
    };
}

function normalizeImageListPayload(payload) {
    if (!payload || !Array.isArray(payload.images)) return payload;
    return {
        ...payload,
        images: payload.images.map(normalizeImagePayload),
    };
}

function buildQueryString(params = {}) {
    const searchParams = new URLSearchParams();
    Object.entries(params).forEach(([key, value]) => {
        if (value === undefined || value === null || value === '') return;
        searchParams.set(key, String(value));
    });
    const query = searchParams.toString();
    return query ? `?${query}` : '';
}

function stripHtml(raw = '') {
    return String(raw)
        .replace(/<style[\s\S]*?<\/style>/gi, ' ')
        .replace(/<script[\s\S]*?<\/script>/gi, ' ')
        .replace(/<[^>]+>/g, ' ')
        .replace(/\s+/g, ' ')
        .trim();
}

function createApiError(message, status = 0, body = null) {
    const error = new Error(message);
    error.status = status;
    error.body = body;
    return error;
}

async function parseErrorResponse(response, fallbackPrefix = 'Request failed') {
    const fallback = `${fallbackPrefix}: ${response.status} ${response.statusText}`.trim();

    try {
        const raw = await response.text();
        if (!raw) return fallback;

        try {
            const parsed = JSON.parse(raw);
            if (typeof parsed?.detail === 'string' && parsed.detail.trim()) return parsed.detail.trim();
            if (typeof parsed?.message === 'string' && parsed.message.trim()) return parsed.message.trim();
            if (typeof parsed?.error === 'string' && parsed.error.trim()) return parsed.error.trim();
            return fallback;
        } catch (_) {
            const flattened = stripHtml(raw);
            return flattened || fallback;
        }
    } catch (_) {
        return fallback;
    }
}

function defaultErrorMessageForStatus(status) {
    if (status === 403) return 'You do not have permission to perform that action.';
    if (status === 429) return 'Rate limit reached, please wait before trying again.';
    if (status >= 500) return 'The server hit an internal error. Please try again.';
    return 'Request failed.';
}

async function handleErrorResponse(response, options = {}) {
    const fallback = options.fallbackMessage || defaultErrorMessageForStatus(response.status);
    const message = await parseErrorResponse(response, fallback);

    if (response.status === 401) {
        AuthService.clearSession({ silent: true });
        if (!options.silent) showToast('This API endpoint still requires backend authentication.', 'warning');
    } else if (!options.silent) {
        const tone = response.status === 403 ? 'warning' : response.status >= 500 ? 'error' : 'info';
        showToast(message, tone);
    }

    throw createApiError(message, response.status);
}

async function parseJsonSafe(response) {
    const raw = await response.text();
    if (!raw) return null;
    return JSON.parse(raw);
}

function withAuthHeader(headers = {}, auth = true) {
    const finalHeaders = { ...headers };
    if (auth) {
        const token = AuthService.getToken();
        if (token) {
            finalHeaders.Authorization = `Bearer ${token}`;
        }
    }
    return finalHeaders;
}

export async function apiFetch(endpoint, options = {}) {
    const {
        method = 'GET',
        body,
        headers = {},
        auth = true,
        contentType = 'application/json',
        responseType = 'json',
        silent = false,
        skipRedirect = false,
        fallbackMessage,
        retryOnAuth = true,
    } = options;

    const url = endpoint.startsWith('http') ? endpoint : `${API_BASE}${endpoint}`;
    const buildHeaders = () => {
        const requestHeaders = withAuthHeader(headers, auth);
        if (contentType && !(body instanceof FormData)) {
            requestHeaders['Content-Type'] = contentType;
        }
        return requestHeaders;
    };

    let response = await fetch(url, {
        method,
        headers: buildHeaders(),
        body,
    });

    if (response.status === 401 && auth && retryOnAuth) {
        const refreshed = await AuthService.refresh({ silent: true }).catch(() => null);
        if (refreshed) {
            response = await fetch(url, {
                method,
                headers: buildHeaders(),
                body,
            });
        }
    }

    if (!response.ok) {
        return handleErrorResponse(response, { silent, skipRedirect, fallbackMessage });
    }

    if (responseType === 'text') return response.text();
    if (responseType === 'raw') return response;
    if (response.status === 204) return null;
    return parseJsonSafe(response);
}

class AuthServiceClass {
    constructor() {
        this._refreshPromise = null;
    }

    _storage() {
        if (typeof window === 'undefined') {
            return {
                getItem: () => null,
                setItem: () => {},
                removeItem: () => {},
            };
        }
        return window.localStorage;
    }

    getToken() {
        return this._storage().getItem(AUTH_ACCESS_TOKEN_KEY) || '';
    }

    getRefreshToken() {
        return this._storage().getItem(AUTH_REFRESH_TOKEN_KEY) || '';
    }

    getSessionId() {
        return this._storage().getItem(AUTH_SESSION_KEY) || '';
    }

    getUser() {
        const raw = this._storage().getItem(AUTH_USER_KEY);
        if (!raw) return { ...LOCAL_UI_USER };
        try {
            return JSON.parse(raw) || { ...LOCAL_UI_USER };
        } catch (_) {
            return { ...LOCAL_UI_USER };
        }
    }

    setSession(payload) {
        const storage = this._storage();
        const user = payload.user || null;
        storage.setItem(AUTH_ACCESS_TOKEN_KEY, payload.access_token);
        storage.setItem(AUTH_REFRESH_TOKEN_KEY, payload.refresh_token);
        storage.setItem(AUTH_USER_KEY, JSON.stringify(user));
        storage.setItem(AUTH_SESSION_KEY, payload.session_id || user?.session_id || '');
        window.dispatchEvent(new CustomEvent('clinical:auth-changed', { detail: { authenticated: true, user } }));
    }

    clearSession({ silent = false } = {}) {
        const storage = this._storage();
        storage.removeItem(AUTH_ACCESS_TOKEN_KEY);
        storage.removeItem(AUTH_REFRESH_TOKEN_KEY);
        storage.removeItem(AUTH_USER_KEY);
        storage.removeItem(AUTH_SESSION_KEY);
        window.dispatchEvent(new CustomEvent('clinical:auth-changed', { detail: { authenticated: false } }));
        if (!silent) {
            showToast('Signed out.', 'info', 2500);
        }
    }

    async login(email, password) {
        const result = await apiFetch('/auth/login', {
            method: 'POST',
            auth: false,
            body: JSON.stringify({ email, password }),
            fallbackMessage: 'Unable to sign in',
            silent: true,
            skipRedirect: true,
            retryOnAuth: false,
        });
        this.setSession(result);
        return result.user;
    }

    async getBootstrapStatus() {
        return apiFetch('/auth/bootstrap/status', {
            auth: false,
            silent: true,
            skipRedirect: true,
            retryOnAuth: false,
            fallbackMessage: 'Unable to load setup status',
        });
    }

    async bootstrapAdmin({ email, password, name = '' }) {
        const result = await apiFetch('/auth/bootstrap', {
            method: 'POST',
            auth: false,
            body: JSON.stringify({ email, password, name }),
            fallbackMessage: 'Unable to create the first admin account',
            silent: true,
            skipRedirect: true,
            retryOnAuth: false,
        });
        this.setSession(result);
        return result.user;
    }

    async refresh({ silent = true } = {}) {
        if (this._refreshPromise) {
            return this._refreshPromise;
        }

        const refreshToken = this.getRefreshToken();
        if (!refreshToken) return null;

        this._refreshPromise = (async () => {
            try {
                const result = await apiFetch('/auth/refresh', {
                    method: 'POST',
                    auth: false,
                    body: JSON.stringify({ refresh_token: refreshToken }),
                    fallbackMessage: 'Unable to refresh session',
                    silent,
                    skipRedirect: true,
                    retryOnAuth: false,
                });
                this.setSession(result);
                return result.user;
            } catch (error) {
                this.clearSession({ silent: true });
                return null;
            }
        })();

        try {
            return await this._refreshPromise;
        } finally {
            this._refreshPromise = null;
        }
    }

    async logout() {
        try {
            await apiFetch('/auth/logout', {
                method: 'POST',
                auth: true,
                silent: true,
                skipRedirect: true,
                retryOnAuth: false,
            });
        } finally {
            this.clearSession({ silent: true });
        }
    }

    async logoutAll() {
        try {
            await apiFetch('/auth/logout-all', {
                method: 'POST',
                auth: true,
                silent: true,
                skipRedirect: true,
                retryOnAuth: false,
            });
        } finally {
            this.clearSession({ silent: true });
        }
    }

    async changePassword(currentPassword, newPassword) {
        return apiFetch('/auth/change-password', {
            method: 'POST',
            auth: true,
            body: JSON.stringify({
                current_password: currentPassword,
                new_password: newPassword,
            }),
            fallbackMessage: 'Unable to change password',
        });
    }

    async listSessions({ includeRevoked = false } = {}) {
        const suffix = includeRevoked ? '?include_revoked=true' : '';
        return apiFetch(`/auth/sessions${suffix}`, {
            auth: true,
            fallbackMessage: 'Unable to load sessions',
        });
    }

    async revokeSession(sessionId) {
        return apiFetch(`/auth/sessions/${encodeURIComponent(sessionId)}/revoke`, {
            method: 'POST',
            auth: true,
            fallbackMessage: 'Unable to revoke session',
        });
    }

    async fetchCurrentUser({ silent = true } = {}) {
        if (!this.getToken() && this.getRefreshToken()) {
            const refreshed = await this.refresh({ silent: true });
            if (!refreshed) return { ...LOCAL_UI_USER };
        }

        const token = this.getToken();
        if (!token) return { ...LOCAL_UI_USER };

        const payload = await apiFetch('/auth/me', {
            auth: true,
            silent,
            skipRedirect: true,
            fallbackMessage: 'Unable to validate session',
        }).catch(() => null);

        if (!payload?.authenticated) {
            this.clearSession({ silent: true });
            return { ...LOCAL_UI_USER };
        }

        const user = {
            id: payload.id,
            email: payload.email,
            name: payload.name,
            role: payload.role,
            created_at: payload.created_at,
            is_verified: payload.is_verified,
            must_change_password: payload.must_change_password,
            session_id: payload.session_id,
        };
        const storage = this._storage();
        storage.setItem(AUTH_USER_KEY, JSON.stringify(user));
        storage.setItem(AUTH_SESSION_KEY, payload.session_id || '');
        return user;
    }

    async ensureAuthenticated() {
        const user = await this.fetchCurrentUser({ silent: true });
        return user || { ...LOCAL_UI_USER };
    }
}

export const AuthService = new AuthServiceClass();
export { showToast, toast };

export function primeChatContext({ attachment = null, draft = '', resetSession = true } = {}) {
    if (typeof window === 'undefined') return;

    if (attachment) {
        window.sessionStorage.setItem(CHAT_ATTACHMENT_STORAGE_KEY, JSON.stringify(attachment));
    } else {
        window.sessionStorage.removeItem(CHAT_ATTACHMENT_STORAGE_KEY);
    }

    if (draft && String(draft).trim()) {
        window.sessionStorage.setItem(CHAT_DRAFT_STORAGE_KEY, String(draft));
    } else {
        window.sessionStorage.removeItem(CHAT_DRAFT_STORAGE_KEY);
    }

    if (resetSession) {
        window.sessionStorage.removeItem(CHAT_SESSION_PAYLOAD_KEY);
        window.dispatchEvent(new CustomEvent('clinical:new-chat'));
    }
}

function uploadFileWithProgress(endpoint, file, onProgress, fallbackMessage) {
    return new Promise((resolve, reject) => {
        const xhr = new XMLHttpRequest();
        const formData = new FormData();
        formData.append('file', file);
        xhr.open('POST', `${API_BASE}${endpoint}`, true);

        const token = AuthService.getToken();
        if (token) xhr.setRequestHeader('Authorization', `Bearer ${token}`);

        xhr.upload.addEventListener('progress', (event) => {
            if (!event.lengthComputable || typeof onProgress !== 'function') return;
            const progress = Math.round((event.loaded / event.total) * 100);
            onProgress(progress);
        });

        xhr.onload = async () => {
            const pseudoResponse = new Response(xhr.responseText, {
                status: xhr.status,
                statusText: xhr.statusText,
                headers: { 'Content-Type': xhr.getResponseHeader('Content-Type') || 'application/json' },
            });

            if (xhr.status < 200 || xhr.status >= 300) {
                try {
                    await handleErrorResponse(pseudoResponse, { fallbackMessage });
                } catch (error) {
                    reject(error);
                }
                return;
            }

            try {
                resolve(xhr.responseText ? JSON.parse(xhr.responseText) : null);
            } catch (_) {
                resolve(null);
            }
        };

        xhr.onerror = () => {
            const error = createApiError('Network error while uploading file.');
            showToast(error.message, 'error');
            reject(error);
        };

        xhr.send(formData);
    });
}

export async function streamChat({
    message,
    sessionId = null,
    attachedDocumentId = null,
    attachedImageId = null,
    onToken,
    onReasoning,
    onSources,
    onDone,
    onError,
}) {
    const body = { message };
    if (sessionId) body.session_id = sessionId;
    if (attachedDocumentId) body.attached_document_id = attachedDocumentId;
    if (attachedImageId) body.attached_image_id = attachedImageId;

    try {
        const response = await fetch(`${API_BASE}/chat`, {
            method: 'POST',
            headers: withAuthHeader({ 'Content-Type': 'application/json' }, true),
            body: JSON.stringify(body),
        });

        if (!response.ok) {
            await handleErrorResponse(response, { fallbackMessage: 'Failed to send message' });
            return;
        }

        const reader = response.body.getReader();
        const decoder = new TextDecoder('utf-8');
        let buffer = '';
        let complete = false;
        let finalSessionId = sessionId;

        while (!complete) {
            const { value, done } = await reader.read();
            complete = done;
            if (!value) continue;

            buffer += decoder.decode(value, { stream: true });
            let boundary = buffer.indexOf('\n\n');

            while (boundary !== -1) {
                const chunk = buffer.slice(0, boundary).trim();
                buffer = buffer.slice(boundary + 2);
                boundary = buffer.indexOf('\n\n');
                if (!chunk) continue;

                for (const line of chunk.split('\n')) {
                    if (!line.startsWith('data: ')) continue;
                    const dataStr = line.slice(6).trim();
                    if (dataStr === '[DONE]') {
                        complete = true;
                        break;
                    }

                    let payload = null;
                    try {
                        payload = JSON.parse(dataStr);
                    } catch (_) {
                        continue;
                    }

                    if (payload.type === 'token' && payload.content) {
                        onToken?.(payload.content);
                    } else if (payload.type === 'reasoning') {
                        onReasoning?.(payload);
                    } else if (payload.type === 'source') {
                        onSources?.(payload.sources || []);
                    } else if (payload.type === 'done') {
                        finalSessionId = payload.session_id || finalSessionId;
                        onDone?.({ session_id: finalSessionId, message_id: payload.message_id || null });
                    } else if (payload.type === 'error') {
                        throw createApiError(payload.content || payload.message || 'Streaming error');
                    }
                }
            }
        }
    } catch (error) {
        onError?.(error);
    }
}

export async function streamAgentWorkflow({
    query,
    workflowType = 'general',
    imageId = null,
    sessionId = null,
    onEvent,
    onError,
}) {
    const body = {
        query,
        workflow_type: workflowType,
    };
    if (imageId) body.image_id = imageId;
    if (sessionId) body.session_id = sessionId;

    try {
        const response = await fetch(`${API_BASE}/agents/run`, {
            method: 'POST',
            headers: withAuthHeader({ 'Content-Type': 'application/json' }, true),
            body: JSON.stringify(body),
        });

        if (!response.ok) {
            await handleErrorResponse(response, { fallbackMessage: 'Failed to run workflow' });
            return;
        }

        const reader = response.body.getReader();
        const decoder = new TextDecoder('utf-8');
        let buffer = '';
        let complete = false;

        while (!complete) {
            const { value, done } = await reader.read();
            complete = done;
            if (!value) continue;

            buffer += decoder.decode(value, { stream: true });
            let boundary = buffer.indexOf('\n\n');

            while (boundary !== -1) {
                const chunk = buffer.slice(0, boundary).trim();
                buffer = buffer.slice(boundary + 2);
                boundary = buffer.indexOf('\n\n');
                if (!chunk) continue;

                for (const line of chunk.split('\n')) {
                    if (!line.startsWith('data:')) continue;
                    const dataStr = line.slice(5).trim();
                    if (!dataStr) continue;

                    let payload = null;
                    try {
                        payload = JSON.parse(dataStr);
                    } catch (_) {
                        continue;
                    }

                    onEvent?.(payload);
                    if (payload.type === 'workflow_done' || payload.type === 'error') {
                        complete = true;
                    }
                }
            }
        }
    } catch (error) {
        onError?.(error);
    }
}

export function listChatSessions() {
    return apiFetch('/chat/sessions');
}

export function listAgentWorkflows({ skip = 0, limit = 20, sessionId = '' } = {}) {
    return apiFetch(`/agents/workflows${buildQueryString({ skip, limit, session_id: sessionId })}`);
}

export function getAgentWorkflow(workflowId) {
    return apiFetch(`/agents/workflows/${workflowId}`);
}

export function listAgentTools() {
    return apiFetch('/agents/tools');
}

export function getChatSession(sessionId) {
    return apiFetch(`/chat/sessions/${sessionId}`);
}

export function deleteChatSession(sessionId) {
    return apiFetch(`/chat/sessions/${sessionId}`, {
        method: 'DELETE',
        fallbackMessage: 'Failed to delete chat session',
    });
}

export function submitFeedback(messageId, rating, comment = '') {
    return apiFetch(`/chat/messages/${messageId}/feedback`, {
        method: 'POST',
        body: JSON.stringify({ rating, comment }),
        fallbackMessage: 'Unable to submit feedback',
    });
}

export function generateSoapNote(sessionId) {
    return apiFetch(`/chat/sessions/${sessionId}/generate-note`, {
        method: 'POST',
        fallbackMessage: 'Unable to generate SOAP note',
    });
}

export function uploadDocument(file, onProgress) {
    return uploadFileWithProgress('/documents/upload', file, onProgress, 'Failed to upload document');
}

export function listDocuments() {
    return apiFetch('/documents');
}

export function getDocument(documentId) {
    return apiFetch(`/documents/${documentId}`);
}

export function getDocumentStatus(documentId) {
    return apiFetch(`/documents/${documentId}/status`, {
        fallbackMessage: 'Unable to get document status',
    });
}

export function deleteDocument(documentId) {
    return apiFetch(`/documents/${documentId}`, {
        method: 'DELETE',
        fallbackMessage: 'Unable to delete document',
    });
}

export function retryDocumentProcessing(documentId) {
    return apiFetch(`/documents/${documentId}/retry`, {
        method: 'POST',
        fallbackMessage: 'Unable to retry document processing',
    });
}

export function uploadImage(file, onProgress) {
    return uploadFileWithProgress('/images/upload', file, onProgress, 'Failed to upload image')
        .then(normalizeImagePayload);
}

export function listImages() {
    return apiFetch('/images').then(normalizeImageListPayload);
}

export function getImage(imageId) {
    return apiFetch(`/images/${imageId}`).then(normalizeImagePayload);
}

export function analyzeImage(imageId, additionalContext = '') {
    return apiFetch(`/images/${imageId}/analyze`, {
        method: 'POST',
        body: JSON.stringify({ additional_context: additionalContext }),
        fallbackMessage: 'Unable to analyze image',
    });
}

export function deleteImage(imageId) {
    return apiFetch(`/images/${imageId}`, {
        method: 'DELETE',
        fallbackMessage: 'Unable to delete image',
    });
}

export function listImageAnnotations(imageId) {
    return apiFetch(`/images/${imageId}/annotations`, {
        fallbackMessage: 'Unable to load image annotations',
    });
}

export function createImageAnnotation(imageId, annotation) {
    return apiFetch(`/images/${imageId}/annotations`, {
        method: 'POST',
        body: JSON.stringify(annotation),
        fallbackMessage: 'Unable to create image annotation',
    });
}

export function updateImageAnnotation(imageId, annotationId, annotation) {
    return apiFetch(`/images/${imageId}/annotations/${annotationId}`, {
        method: 'PUT',
        body: JSON.stringify(annotation),
        fallbackMessage: 'Unable to update image annotation',
    });
}

export function deleteImageAnnotation(imageId, annotationId) {
    return apiFetch(`/images/${imageId}/annotations/${annotationId}`, {
        method: 'DELETE',
        fallbackMessage: 'Unable to delete image annotation',
    });
}

export function getGraphVisualization(limit = 500, patientId = null) {
    return apiFetch(`/graph/visualize${buildQueryString({ limit, patient_id: patientId })}`);
}

export function getGraphStats() {
    return apiFetch('/graph/stats');
}

export function getTemporalGraphState(entity, date) {
    return apiFetch(`/graph/temporal${buildQueryString({ entity, date })}`, {
        fallbackMessage: 'Unable to query temporal graph state',
    });
}

export function getPatientLabTrends(patientId, { lab = '', limit = 50 } = {}) {
    return apiFetch(`/graph/patients/${encodeURIComponent(patientId)}/lab-trends${buildQueryString({ lab, limit })}`, {
        fallbackMessage: 'Unable to load lab trends',
    });
}

export function searchGraphDocuments(query, { topK = 5 } = {}) {
    return apiFetch(`/graph/search${buildQueryString({ q: query, top_k: topK })}`, {
        fallbackMessage: 'Unable to search graph evidence',
    });
}

export function ingestFhirBundle(bundle) {
    return apiFetch('/graph/fhir/ingest', {
        method: 'POST',
        body: JSON.stringify(bundle),
        fallbackMessage: 'Unable to ingest FHIR bundle',
    });
}

export function normalizeEntities(entities) {
    return apiFetch('/entity-normalization/normalize', {
        method: 'POST',
        body: JSON.stringify({ entities }),
        fallbackMessage: 'Unable to normalize clinical entities',
    });
}

export function listOntologies() {
    return apiFetch('/entity-normalization/ontologies', {
        fallbackMessage: 'Unable to load supported ontologies',
    });
}

export function getDetailedHealth() {
    return apiFetch('/health/detailed', {
        silent: true,
        skipRedirect: true,
        fallbackMessage: 'Unable to load system capability status',
    });
}

export function getAdminHealth() {
    return apiFetch('/admin/health', {
        fallbackMessage: 'Unable to load admin health',
    });
}

export function getAdminMetrics() {
    return apiFetch('/admin/metrics', {
        fallbackMessage: 'Unable to load admin metrics',
    });
}

export function getAdminConfig() {
    return apiFetch('/admin/config', {
        fallbackMessage: 'Unable to load admin config',
    });
}

export function listAdminUsers() {
    return apiFetch('/admin/users', {
        fallbackMessage: 'Unable to load users',
    });
}

export function createAdminUser(user) {
    return apiFetch('/admin/users', {
        method: 'POST',
        body: JSON.stringify(user),
        fallbackMessage: 'Unable to create user',
    });
}

export function updateAdminUser(userId, patch) {
    return apiFetch(`/admin/users/${encodeURIComponent(userId)}`, {
        method: 'PATCH',
        body: JSON.stringify(patch),
        fallbackMessage: 'Unable to update user',
    });
}

export function listAdminSessions({ includeRevoked = true } = {}) {
    return apiFetch(`/admin/sessions${buildQueryString({ include_revoked: includeRevoked })}`, {
        fallbackMessage: 'Unable to load active sessions',
    });
}

export function revokeAdminSession(sessionId) {
    return apiFetch(`/admin/sessions/${encodeURIComponent(sessionId)}/revoke`, {
        method: 'POST',
        fallbackMessage: 'Unable to revoke session',
    });
}

export function listAuditLog({ page = 1, pageSize = 25 } = {}) {
    return apiFetch(`/admin/audit-log${buildQueryString({ page, page_size: pageSize })}`, {
        fallbackMessage: 'Unable to load audit log',
    });
}

export function exportUserData(userId) {
    return apiFetch(`/admin/gdpr/export/${encodeURIComponent(userId)}`, {
        method: 'POST',
        fallbackMessage: 'Unable to export user data',
    });
}

export function purgeUserData(userId) {
    return apiFetch(`/admin/gdpr/purge/${encodeURIComponent(userId)}`, {
        method: 'DELETE',
        fallbackMessage: 'Unable to purge user data',
    });
}

export function getEvaluationBaseline() {
    return apiFetch('/evaluations/baseline', {
        silent: true,
        skipRedirect: true,
        fallbackMessage: 'Unable to load evaluation baseline',
    });
}

export function blessEvaluationBaseline(runId, note = '') {
    return apiFetch(`/evaluations/${encodeURIComponent(runId)}/baseline`, {
        method: 'POST',
        body: JSON.stringify({ note }),
        fallbackMessage: 'Unable to bless evaluation baseline',
    });
}

export function reviewEvaluationCase(runId, review) {
    return apiFetch(`/evaluations/${encodeURIComponent(runId)}/review`, {
        method: 'POST',
        body: JSON.stringify(review),
        fallbackMessage: 'Unable to record evaluation review',
    });
}

export function listFineTuneDatasets() {
    return apiFetch('/fine-tune/datasets', {
        silent: true,
        skipRedirect: true,
        fallbackMessage: 'Unable to load training datasets',
    });
}

export function createFineTuneDataset(dataset) {
    return apiFetch('/fine-tune/datasets', {
        method: 'POST',
        body: JSON.stringify(dataset),
        fallbackMessage: 'Unable to create training dataset',
    });
}

export function getFineTuneDataset(datasetId) {
    return apiFetch(`/fine-tune/datasets/${encodeURIComponent(datasetId)}`, {
        fallbackMessage: 'Unable to load training dataset',
    });
}

export function addFineTuneSample(datasetId, sample) {
    return apiFetch(`/fine-tune/datasets/${encodeURIComponent(datasetId)}/samples`, {
        method: 'POST',
        body: JSON.stringify(sample),
        fallbackMessage: 'Unable to add training sample',
    });
}

export function generateFineTuneSamples(datasetId, numPairs = 20) {
    return apiFetch(`/fine-tune/datasets/${encodeURIComponent(datasetId)}/generate`, {
        method: 'POST',
        body: JSON.stringify({ num_pairs: Number(numPairs) || 20 }),
        fallbackMessage: 'Unable to generate training samples',
    });
}

export function validateFineTuneDataset(datasetId) {
    return apiFetch(`/fine-tune/datasets/${encodeURIComponent(datasetId)}/validate`, {
        fallbackMessage: 'Unable to validate training dataset',
    });
}

export function deleteFineTuneDataset(datasetId) {
    return apiFetch(`/fine-tune/datasets/${encodeURIComponent(datasetId)}`, {
        method: 'DELETE',
        fallbackMessage: 'Unable to delete training dataset',
    });
}

export function startFineTuneTraining(config) {
    return apiFetch('/fine-tune/start', {
        method: 'POST',
        body: JSON.stringify(config),
        fallbackMessage: 'Unable to start fine-tuning job',
    });
}

export function listFineTuneJobs() {
    return apiFetch('/fine-tune/jobs', {
        silent: true,
        skipRedirect: true,
        fallbackMessage: 'Unable to load fine-tuning jobs',
    });
}

export function getFineTuneJob(jobId) {
    return apiFetch(`/fine-tune/jobs/${encodeURIComponent(jobId)}`, {
        fallbackMessage: 'Unable to load fine-tuning job',
    });
}

export function cancelFineTuneJob(jobId) {
    return apiFetch(`/fine-tune/jobs/${encodeURIComponent(jobId)}/cancel`, {
        method: 'POST',
        fallbackMessage: 'Unable to cancel fine-tuning job',
    });
}

export function listFineTuneModels() {
    return apiFetch('/fine-tune/models', {
        silent: true,
        skipRedirect: true,
        fallbackMessage: 'Unable to load model registry',
    });
}

export function registerFineTuneModel(model) {
    return apiFetch('/fine-tune/models', {
        method: 'POST',
        body: JSON.stringify(model),
        fallbackMessage: 'Unable to register model',
    });
}

export function deployFineTuneModel(modelId) {
    return apiFetch(`/fine-tune/models/${encodeURIComponent(modelId)}/deploy`, {
        method: 'POST',
        fallbackMessage: 'Unable to deploy model',
    });
}

export function undeployFineTuneModel(modelId) {
    return apiFetch(`/fine-tune/models/${encodeURIComponent(modelId)}/undeploy`, {
        method: 'POST',
        fallbackMessage: 'Unable to undeploy model',
    });
}

export function deleteFineTuneModel(modelId) {
    return apiFetch(`/fine-tune/models/${encodeURIComponent(modelId)}`, {
        method: 'DELETE',
        fallbackMessage: 'Unable to delete model',
    });
}

export function uploadAudioForTranscription(file) {
    const formData = new FormData();
    const filename = file instanceof File ? file.name : 'recording.webm';
    formData.append('file', file, filename);
    return apiFetch('/audio/transcribe', {
        method: 'POST',
        body: formData,
        contentType: null,
        fallbackMessage: 'Failed to transcribe audio',
    }).then(async (response) => {
        if (response?.status === 'completed' || !response?.id) {
            return response;
        }

        const startedAt = Date.now();
        while (Date.now() - startedAt < 60000) {
            await new Promise((resolve) => setTimeout(resolve, 1000));
            const status = await apiFetch(`/audio/transcripts/${response.id}`, {
                fallbackMessage: 'Failed to fetch transcription status',
                notifyOnError: false,
            });
            if (status?.status === 'completed') return status;
            if (status?.status === 'failed') {
                throw createApiError(status.error_message || 'Audio transcription failed.');
            }
        }

        throw createApiError('Audio transcription timed out while waiting for the queued job.');
    });
}

export const transcribeAudio = uploadAudioForTranscription;
