// api.js
export const API_BASE = 'https://mohi679-clinical-graphrag-backend.hf.space/api';

/**
 * Standard JSON fetch utility
 */
export async function apiFetch(endpoint, options = {}) {
    const url = endpoint.startsWith('http') ? endpoint : `${API_BASE}${endpoint}`;
    try {
        const response = await fetch(url, {
            ...options,
            headers: {
                'Content-Type': 'application/json',
                ...options.headers
            }
        });

        if (!response.ok) {
            let errorText = await response.text();
            try {
                const errObj = JSON.parse(errorText);
                errorText = errObj.detail || errorText;
            } catch (e) { }
            throw new Error(errorText || `API Error: ${response.status}`);
        }

        return await response.json();
    } catch (error) {
        console.error(`[API] Error fetching ${endpoint}:`, error);
        throw error;
    }
}

/**
 * Streaming fetch utility for Server-Sent Events (Chat)
 * @param {string} message - The user message
 * @param {boolean} isReview - Review mode flag
 * @param {Function} onChunk - Called with each text token/chunk
 * @param {Function} onMetadata - Called with metadata events
 * @param {Function} onDone - Called when stream completes, receives { session_id }
 * @param {Function} onError - Called on error
 * @param {string|null} sessionId - Existing session ID for history continuity
 * @param {string|null} attachedDocumentId - Document ID for document chat
 * @param {string|null} attachedImageId - Image ID for vision chat
 */
export async function streamChat(message, isReview, onChunk, onMetadata, onDone, onError, onReasoning = null, sessionId = null, attachedDocumentId = null, attachedImageId = null) {
    try {
        const body = { message, review_mode: isReview };
        if (sessionId) body.session_id = sessionId;
        if (attachedDocumentId) body.attached_document_id = attachedDocumentId;
        if (attachedImageId) body.attached_image_id = attachedImageId;

        const response = await fetch(`${API_BASE}/chat`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body)
        });

        if (!response.ok) {
            const errBody = await response.text();
            throw new Error(`Failed to send message: ${response.status} ${errBody}`);
        }

        const reader = response.body.getReader();
        const decoder = new TextDecoder('utf-8');
        let done = false;
        let buffer = '';
        let receivedSessionId = sessionId;

        while (!done) {
            const { value, done: readerDone } = await reader.read();
            done = readerDone;

            if (value) {
                buffer += decoder.decode(value, { stream: true });
                let boundary = buffer.indexOf('\n\n');
                while (boundary !== -1) {
                    const chunk = buffer.substring(0, boundary).trim();
                    buffer = buffer.substring(boundary + 2);
                    boundary = buffer.indexOf('\n\n');
                    if (!chunk) continue;

                    for (const line of chunk.split('\n')) {
                        if (!line.startsWith('data: ')) continue;
                        const dataStr = line.substring(6).trim();
                        if (dataStr === '[DONE]') { done = true; break; }
                        try {
                            const data = JSON.parse(dataStr);
                            if (data.type === 'token' || data.type === 'content') {
                                if (data.content) onChunk(data.content);
                            } else if (data.type === 'reasoning') {
                                if (onReasoning) onReasoning(data);
                            } else if (data.type === 'metadata') {
                                if (onMetadata) onMetadata(data);
                            } else if (data.type === 'done') {
                                if (data.session_id) receivedSessionId = data.session_id;
                                done = true;
                            } else if (data.type === 'error') {
                                throw new Error(data.content || data.message || 'Stream error');
                            }
                        } catch (e) {
                            if (e.message && !e.message.includes('JSON')) throw e;
                        }
                    }
                }
            }
        }

        if (onDone) onDone({ session_id: receivedSessionId });
    } catch (error) {
        console.error('[API] Stream error:', error);
        if (onError) onError(error);
    }
}


// ── Documents ───────────────────────────────────────────


export async function uploadDocument(file) {
    const formData = new FormData();
    formData.append("file", file);

    const res = await fetch(`${API_BASE}/documents/upload`, {
        method: "POST",
        body: formData,
    });

    if (!res.ok) {
        throw new Error(`Failed to upload document: ${res.status}`);
    }

    return await res.json();
}

// ── Images / Vision ─────────────────────────────────────

export async function uploadImage(file) {
    const formData = new FormData();
    formData.append("file", file);

    const res = await fetch(`${API_BASE}/images/upload`, {
        method: "POST",
        body: formData,
    });

    if (!res.ok) {
        throw new Error(`Failed to upload image: ${res.status}`);
    }

    return await res.json();
}

// ── Audio ───────────────────────────────────────────────

export async function uploadAudioForTranscription(file) {
    const formData = new FormData();
    const filename = file instanceof File ? file.name : "recording.webm";
    formData.append("file", file, filename);

    const res = await fetch(`${API_BASE}/audio/transcribe`, {
        method: "POST",
        body: formData,
    });

    if (!res.ok) {
        throw new Error(`Failed to transcribe audio: ${res.status}`);
    }

    return await res.json();
}
