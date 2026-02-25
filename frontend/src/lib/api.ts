/**
 * API client for the Clinical GraphRAG Pro backend.
 * Provides typed methods for all API endpoints + SSE streaming support.
 */

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8000/api";

// ── Types ───────────────────────────────────────────────

export interface ChatMessage {
    id: string;
    role: "user" | "assistant" | "system" | "tool";
    content: string;
    sources?: SourceReference[] | null;
    reasoning_steps?: ReasoningStep[] | null;
    created_at: string;
}

export interface SourceReference {
    document_id: string;
    document_name: string;
    chunk_index: number;
    text: string;
    relevance_score: number;
}

export interface ReasoningStep {
    step: number;
    title: string;
    description: string;
    status: "pending" | "running" | "done";
}

export interface ChatSession {
    id: string;
    title: string;
    created_at: string;
    updated_at: string;
    message_count: number;
}

export interface DocumentInfo {
    id: string;
    filename: string;
    file_size: number;
    chunk_count: number;
    status: string;
    uploaded_at: string;
    processed_at: string | null;
    error_message: string | null;
}

export interface StreamEvent {
    type: "reasoning" | "source" | "token" | "done" | "error";
    content?: string;
    step?: number;
    title?: string;
    description?: string;
    status?: string;
    sources?: SourceReference[];
    session_id?: string;
}

export interface HealthStatus {
    status: string;
    app: string;
    version: string;
    dependencies: {
        database: { status: string };
        redis: { status: string };
    };
}

// ── Image / Vision Types ────────────────────────────────

export interface ImageAnnotation {
    id: string;
    image_id: string;
    annotation_type: "bbox" | "polygon" | "point" | "freeform" | "text";
    label: string;
    description?: string;
    color: string;
    confidence?: number;
    geometry: Record<string, unknown>;
    source: "ai" | "user";
    created_at: string;
}

export interface Finding {
    description: string;
    location: string;
    severity: "normal" | "mild" | "moderate" | "severe";
    confidence: number;
    bbox?: { x: number; y: number; width: number; height: number };
}

export interface ImageAnalysisResult {
    summary: string;
    modality_detected: string;
    body_part_detected: string;
    findings: Finding[];
    recommendations: string[];
    differential_diagnosis: { condition: string; probability: number }[];
    model_used: string;
    error?: string;
}

export interface MedicalImageInfo {
    id: string;
    filename: string;
    original_filename: string;
    file_size: number;
    width?: number;
    height?: number;
    mime_type: string;
    modality?: string;
    body_part?: string;
    analysis_status: "pending" | "analyzing" | "completed" | "failed";
    analysis_result?: ImageAnalysisResult;
    annotations: ImageAnnotation[];
    uploaded_at: string;
    analyzed_at?: string;
    image_url: string;
    thumbnail_url?: string;
}

// ── Fetch helper ────────────────────────────────────────

async function apiFetch<T>(
    path: string,
    options?: RequestInit
): Promise<T> {
    const res = await fetch(`${API_BASE}${path}`, {
        headers: { "Content-Type": "application/json", ...options?.headers },
        ...options,
    });
    if (!res.ok) {
        const error = await res.json().catch(() => ({ detail: res.statusText }));
        throw new Error(error.detail || `API error: ${res.status}`);
    }
    return res.json();
}

// ── Health ──────────────────────────────────────────────

export async function getHealth(): Promise<HealthStatus> {
    return apiFetch("/health");
}

// ── Chat ────────────────────────────────────────────────

export async function sendMessageStream(
    message: string,
    sessionId?: string,
    onEvent?: (event: StreamEvent) => void,
    attachedImageId?: string,
    attachedDocumentId?: string
) {
    const payload: Record<string, string> = {
        message,
    };
    if (sessionId) payload.session_id = sessionId;
    if (attachedImageId) payload.attached_image_id = attachedImageId;
    if (attachedDocumentId) payload.attached_document_id = attachedDocumentId;

    const res = await fetch(`${API_BASE}/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
    });

    if (!res.ok) {
        const error = await res.json().catch(() => ({ detail: res.statusText }));
        throw new Error(error.detail || `API error: ${res.status}`);
    }

    const reader = res.body?.getReader();
    if (!reader) throw new Error("No response body");

    const decoder = new TextDecoder();
    let buffer = "";

    while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });

        const lines = buffer.split("\n");
        buffer = lines.pop() || "";

        for (const line of lines) {
            if (line.startsWith("data: ")) {
                const data = line.slice(6);
                if (data === "[DONE]") continue;
                try {
                    const event: StreamEvent = JSON.parse(data);
                    if (onEvent) onEvent(event);
                } catch (e) {
                    console.error("Failed to parse SSE event:", data, e);
                }
            }
        }
    }
}

export async function sendMessageSync(
    message: string,
    sessionId?: string
): Promise<{ answer: string; sources: SourceReference[]; error: boolean }> {
    return apiFetch("/chat/sync", {
        method: "POST",
        body: JSON.stringify({ message, session_id: sessionId }),
    });
}

export async function getSessions(): Promise<ChatSession[]> {
    return apiFetch("/chat/sessions");
}

export async function getSession(
    sessionId: string
): Promise<{ session: ChatSession; messages: ChatMessage[] }> {
    return apiFetch(`/chat/sessions/${sessionId}`);
}

export async function deleteSession(sessionId: string): Promise<void> {
    await apiFetch(`/chat/sessions/${sessionId}`, { method: "DELETE" });
}

export async function submitFeedback(messageId: string, rating: number, comment?: string): Promise<{ success: boolean; message: string }> {
    return apiFetch(`/chat/messages/${messageId}/feedback`, {
        method: "POST",
        body: JSON.stringify({ message_id: messageId, rating, comment }),
    });
}

export async function generateClinicalNote(sessionId: string): Promise<{ note: string }> {
    return apiFetch(`/chat/sessions/${sessionId}/generate-note`, {
        method: "POST"
    });
}

// ── Documents ───────────────────────────────────────────

export async function uploadDocument(file: File): Promise<{
    id: string;
    filename: string;
    status: string;
    chunk_count: number;
    message: string;
}> {
    const formData = new FormData();
    formData.append("file", file);

    const res = await fetch(`${API_BASE}/documents/upload`, {
        method: "POST",
        body: formData,
    });

    if (!res.ok) {
        const error = await res.json().catch(() => ({ detail: res.statusText }));
        throw new Error(error.detail || `Upload failed: ${res.status}`);
    }

    return res.json();
}

export async function getDocuments(): Promise<{
    documents: DocumentInfo[];
    total: number;
}> {
    return apiFetch("/documents");
}

export async function deleteDocument(documentId: string): Promise<void> {
    await apiFetch(`/documents/${documentId}`, { method: "DELETE" });
}

// ── Graph ───────────────────────────────────────────────

export async function getGraphStats(): Promise<{
    vector_store: { total_vectors: number; total_chunks: number; total_documents: number };
    knowledge_graph: { nodes: number; edges: number; status: string };
}> {
    return apiFetch("/graph/stats");
}

export async function searchGraph(
    query: string,
    topK = 5
): Promise<{
    query: string;
    total: number;
    results: { document_id: string; document_name: string; chunk_index: number; text: string; score: number }[];
}> {
    return apiFetch(`/graph/search?q=${encodeURIComponent(query)}&top_k=${topK}`);
}

export async function getGraphVisualization(): Promise<{
    nodes: any[];
    links: any[];
}> {
    return apiFetch("/graph/visualize");
}

// ── Images / Vision ─────────────────────────────────────

export async function uploadImage(file: File): Promise<{
    id: string;
    filename: string;
    file_size: number;
    analysis_status: string;
    thumbnail_url?: string;
    message: string;
}> {
    const formData = new FormData();
    formData.append("file", file);

    const res = await fetch(`${API_BASE}/images/upload`, {
        method: "POST",
        body: formData,
    });

    if (!res.ok) {
        const error = await res.json().catch(() => ({ detail: res.statusText }));
        throw new Error(error.detail || `Upload failed: ${res.status}`);
    }

    return res.json();
}

export async function getImages(): Promise<{ images: MedicalImageInfo[]; total: number }> {
    return apiFetch("/images");
}

export async function getImage(imageId: string): Promise<MedicalImageInfo> {
    return apiFetch(`/images/${imageId}`);
}

export async function deleteImage(imageId: string): Promise<void> {
    await apiFetch(`/images/${imageId}`, { method: "DELETE" });
}

export async function analyzeImage(
    imageId: string,
    additionalContext = ""
): Promise<ImageAnalysisResult> {
    return apiFetch(`/images/${imageId}/analyze`, {
        method: "POST",
        body: JSON.stringify({ additional_context: additionalContext }),
    });
}

export async function createAnnotation(
    imageId: string,
    annotation: Omit<ImageAnnotation, "id" | "image_id" | "created_at">
): Promise<ImageAnnotation> {
    return apiFetch(`/images/${imageId}/annotations`, {
        method: "POST",
        body: JSON.stringify(annotation),
    });
}

export async function deleteAnnotation(
    imageId: string,
    annotationId: string
): Promise<void> {
    await apiFetch(`/images/${imageId}/annotations/${annotationId}`, { method: "DELETE" });
}

export function getImageFileUrl(filename: string): string {
    return `${API_BASE}/images/files/${filename}`;
}

export function getThumbnailUrl(filename: string): string {
    return `${API_BASE}/images/thumbnails/thumb_${filename.split(".")[0]}.webp`;
}

// ── Agent / Workflow Types ──────────────────────────────

export interface AgentStreamEvent {
    type: "workflow_start" | "reasoning" | "tool_call" | "token" | "workflow_done" | "error" | "verification";
    workflow_id?: string;
    step?: number;
    title?: string;
    description?: string;
    status?: string;
    tool?: string;
    input?: Record<string, unknown>;
    output?: Record<string, unknown>;
    duration?: number;
    content?: string;
    flags?: string[];
    confidence_score?: number;
}

export interface WorkflowInfo {
    id: string;
    session_id?: string;
    workflow_type: string;
    status: string;
    input_data?: Record<string, unknown>;
    output_data?: Record<string, unknown>;
    error_message?: string;
    started_at?: string;
    completed_at?: string;
    created_at: string;
    steps?: WorkflowStepInfo[];
}

export interface WorkflowStepInfo {
    id: string;
    step_number: number;
    title: string;
    description?: string;
    status: string;
    result?: Record<string, unknown>;
    started_at?: string;
    completed_at?: string;
}

export interface ToolDefinition {
    name: string;
    description: string;
    parameters: Record<string, unknown>;
}

// ── Agent / Workflow API ────────────────────────────────

export async function runAgentWorkflow(
    query: string,
    workflowType = "general",
    onEvent: (event: AgentStreamEvent) => void = () => { },
): Promise<void> {
    const res = await fetch(`${API_BASE}/agents/run`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ query, workflow_type: workflowType }),
    });

    if (!res.ok) {
        const error = await res.json().catch(() => ({ detail: res.statusText }));
        throw new Error(error.detail || `API error: ${res.status}`);
    }

    const reader = res.body?.getReader();
    if (!reader) throw new Error("No response body");

    const decoder = new TextDecoder();
    let buffer = "";

    while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop() || "";

        for (const line of lines) {
            if (line.startsWith("data: ")) {
                try {
                    const event: AgentStreamEvent = JSON.parse(line.slice(6));
                    onEvent(event);
                } catch {
                    // skip
                }
            }
        }
    }
}

export async function getWorkflows(): Promise<{ workflows: WorkflowInfo[]; total: number }> {
    return apiFetch("/agents/workflows");
}

export async function getWorkflow(workflowId: string): Promise<WorkflowInfo> {
    return apiFetch(`/agents/workflows/${workflowId}`);
}

export async function getTools(): Promise<ToolDefinition[]> {
    return apiFetch("/agents/tools");
}

// ── Evaluation Types ────────────────────────────────────

export interface MetricScore {
    score: number;
    explanation: string;
}

export interface EvalRunResponse {
    id: string;
    query: string;
    answer: string;
    faithfulness: MetricScore;
    relevance: MetricScore;
    citation_accuracy: MetricScore;
    context_precision: MetricScore;
    overall_score: number;
    created_at: string;
}

export interface EvalHistoryResponse {
    evaluations: EvalRunResponse[];
    total: number;
}

// ── Evaluation API ──────────────────────────────────────

export async function runEvaluation(query: string, topK = 5): Promise<EvalRunResponse> {
    return apiFetch("/eval/run", {
        method: "POST",
        body: JSON.stringify({ query, top_k: topK }),
    });
}

export async function getEvalHistory(limit = 20, offset = 0): Promise<EvalHistoryResponse> {
    return apiFetch(`/eval/history?limit=${limit}&offset=${offset}`);
}

// ── New Analytics Dashboard API ─────────────────────────

export interface EvaluationMetricRun {
    id: string;
    timestamp: string;
    evaluation_type: "ragas" | "adjudicator";
    dataset_size: number;
    metrics: Record<string, number>;
    metadata: Record<string, any>;
}

export interface LatestEvaluations {
    ragas: { timestamp: string; metrics: Record<string, number> } | null;
    adjudicator: { timestamp: string; metrics: Record<string, number> } | null;
    csat?: { score: number | null; total_ratings: number } | null;
}

export async function getEvaluationMetrics(limit = 50): Promise<{ source: string; data: EvaluationMetricRun[] }> {
    return apiFetch(`/evaluations/metrics?limit=${limit}`);
}

export async function getLatestEvaluations(): Promise<LatestEvaluations> {
    return apiFetch(`/evaluations/latest`);
}

// ── Fine-Tuning Types ───────────────────────────────────

export interface FineTuneDataset {
    id: string;
    name: string;
    description: string;
    template: string;
    sample_count: number;
    created_at: string;
}

export interface FineTuneJob {
    id: string;
    adapter_name: string;
    status: string;
    base_model: string;
    lora_rank: number;
    num_epochs: number;
    final_loss: number | null;
    started_at: string | null;
    completed_at: string | null;
    created_at: string;
    duration: number | null;
}

export interface FineTuneModel {
    id: string;
    name: string;
    base_model: string;
    dataset_name: string;
    lora_rank: number;
    training_loss: number | null;
    eval_scores: Record<string, number>;
    is_active: boolean;
    version: number;
    created_at: string;
    notes: string;
}

export interface JobDetail {
    id: string;
    adapter_name: string;
    status: string;
    config: {
        base_model: string;
        lora_rank: number;
        lora_alpha: number;
        learning_rate: number;
        num_epochs: number;
        batch_size: number;
    };
    final_loss: number | null;
    started_at: string | null;
    completed_at: string | null;
    duration: number | null;
    error_message: string | null;
    metrics: { step: number; loss: number; eval_loss?: number | null; epoch: number; learning_rate: number }[];
}

// ── Fine-Tuning API ─────────────────────────────────────

export async function getFineTuneDatasets(): Promise<{ datasets: FineTuneDataset[] }> {
    return apiFetch("/fine-tune/datasets");
}

export async function createFineTuneDataset(name: string, description = "", template = "alpaca"): Promise<{ id: string }> {
    return apiFetch("/fine-tune/datasets", {
        method: "POST",
        body: JSON.stringify({ name, description, template }),
    });
}

export async function generateSamples(datasetId: string, numPairs = 20): Promise<{ generated: number }> {
    return apiFetch(`/fine-tune/datasets/${datasetId}/generate`, {
        method: "POST",
        body: JSON.stringify({ num_pairs: numPairs }),
    });
}

export async function getFineTuneJobs(): Promise<{ jobs: FineTuneJob[] }> {
    return apiFetch("/fine-tune/jobs");
}

export async function startTraining(config: {
    dataset_id: string;
    adapter_name?: string;
    lora_rank?: number;
    num_epochs?: number;
    learning_rate?: number;
}): Promise<{ job_id: string }> {
    return apiFetch("/fine-tune/train", {
        method: "POST",
        body: JSON.stringify(config),
    });
}

export async function getJobDetail(jobId: string): Promise<JobDetail> {
    return apiFetch(`/fine-tune/jobs/${jobId}`);
}

export async function getFineTuneModels(): Promise<{ models: FineTuneModel[] }> {
    return apiFetch("/fine-tune/models");
}

export async function deployModel(modelId: string): Promise<void> {
    await apiFetch(`/fine-tune/models/${modelId}/deploy`, { method: "POST" });
}

export async function undeployModel(modelId: string): Promise<void> {
    await apiFetch(`/fine-tune/models/${modelId}/undeploy`, { method: "POST" });
}

// ── Audio ───────────────────────────────────────────────

export async function uploadAudioForTranscription(file: File | Blob): Promise<{ text: string }> {
    const formData = new FormData();
    const filename = file instanceof File ? file.name : "recording.webm";
    formData.append("file", file, filename);

    const res = await fetch(`${API_BASE}/audio/transcribe`, {
        method: "POST",
        body: formData,
    });

    if (!res.ok) {
        const error = await res.json().catch(() => ({ detail: res.statusText }));
        throw new Error(error.detail || `Transcription failed: ${res.status}`);
    }

    return res.json();
}

// ── Admin Types ─────────────────────────────────────────

export interface AdminHealth {
    status: string;
    uptime_seconds: number;
    uptime_human: string;
    python_version: string;
    platform: string;
    timestamp: string;
    services: {
        vector_store: { status: string; total_chunks: number; total_documents: number };
        llm: { status: string };
        rate_limiter: { enabled: boolean; max_requests_per_minute: number; active_buckets: number };
    };
}

export interface AdminMetrics {
    total_requests: number;
    total_errors: number;
    error_rate_pct: number;
    avg_latency_ms: number;
    p95_latency_ms: number;
    status_counts: Record<string, number>;
    top_endpoints: Record<string, number>;
}

export interface AdminConfig {
    llm: Record<string, string>;
    embedding: Record<string, string | number>;
    rag: Record<string, string | number | boolean>;
    fine_tune: Record<string, string | number>;
    rate_limit: Record<string, string | number | boolean>;
}

export interface AdminSession {
    user_id: string;
    email: string;
    name: string;
    role: string;
    started_at: string;
}

// ── Admin API ───────────────────────────────────────────

export async function getAdminHealth(): Promise<AdminHealth> {
    return apiFetch("/admin/health");
}

export async function getAdminMetrics(): Promise<AdminMetrics> {
    return apiFetch("/admin/metrics");
}

export async function getAdminConfig(): Promise<AdminConfig> {
    return apiFetch("/admin/config");
}

export async function getAdminSessions(): Promise<{ sessions: AdminSession[] }> {
    return apiFetch("/admin/sessions");
}

export async function loginUser(email: string, password: string): Promise<{ token: string; user: { id: string; email: string; name: string; role: string } }> {
    return apiFetch("/auth/login", {
        method: "POST",
        body: JSON.stringify({ email, password }),
    });
}

export async function getAuthMe(): Promise<{ authenticated: boolean; email?: string; name?: string; role?: string }> {
    return apiFetch("/auth/me");
}
