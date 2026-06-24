# API Reference

> Base URL (direct backend): `http://localhost:8000/api`
> Base URL (via reverse proxy): `http://localhost/api`
> Interactive docs: `http://localhost/docs`

---

## Authentication

### POST `/auth/login`
Authenticate and receive a JWT token.

**Request:**
```json
{
  "email": "your-admin@example.com",
  "password": "your-admin-password"
}
```

**Response:**
```json
{
  "token": "eyJhbGciOi...",
  "user": {
    "id": "bootstrap-admin-001",
    "email": "your-admin@example.com",
    "name": "Administrator",
    "role": "admin"
  }
}
```

### GET `/auth/me`
Get current user info. Returns `{"authenticated": false}` if no token.

**Headers:** `Authorization: Bearer <token>`

---

## Chat

### POST `/chat/sync`
Synchronous RAG chat. Retrieves context, generates answer, returns sources.

**Request:**
```json
{
  "message": "What are the treatment options for type 2 diabetes?",
  "session_id": "optional-session-id"
}
```

**Response:**
```json
{
  "answer": "Treatment options for type 2 diabetes include...",
  "sources": [
    {"document_name": "guidelines.pdf", "chunk_id": "chunk-123", "relevance_score": 0.92}
  ],
  "session_id": "abc-123",
  "trace": {
    "trace_level": "public",
    "heuristic_evidence_support_score": 0.76,
    "score_semantics": "heuristic evidence-support score, not calibrated clinical confidence",
    "retrieved_chunk_count": 5,
    "citation_count": 2,
    "latency_ms": 123
  },
  "heuristic_evidence_support_score": 0.76,
  "confidence_score": 0.76,
  "confidence_score_deprecated": true,
  "clinician_review_required": true
}
```

Normal sync and SSE responses return public trace metadata only. They do not return raw prompts, full retrieved chunk text, `final_context`, or raw tool output. Admin-only `debug_redacted` trace access is available only in non-production debug mode.

`heuristic_evidence_support_score` is a retrieval/grounding support indicator, not calibrated clinical confidence. The legacy `confidence_score` field is retained temporarily for compatibility and mirrors the heuristic value. All demo chat outputs require clinician review.

### POST `/chat`
Streaming chat via Server-Sent Events (SSE).

### POST `/auth/ws-ticket`
Issue a short-lived, single-use WebSocket ticket. Requires `Authorization: Bearer <access_token>`.

**Request:**
```json
{
  "session_id": "optional-chat-session-id"
}
```

**Response:**
```json
{
  "ticket": "one-time-random-ticket",
  "token_type": "websocket_ticket",
  "expires_in": 45,
  "expires_at": "2026-06-06T12:00:45+00:00"
}
```

Use the ticket with `GET /chat/ws/{session_id}?ticket=<ticket>`. Long-lived JWT access tokens are not accepted in WebSocket query strings.

### GET `/chat/sessions`
List all chat sessions.

### GET `/chat/sessions/{session_id}`
Get messages for a specific session.

---

## Documents

### POST `/documents/upload`
Upload a clinical document (`.pdf`, `.txt`, `.md`, `.csv`).

**Form Data:** `file` — multipart file upload

**Response:**
```json
{
  "id": "doc-uuid",
  "filename": "guidelines.pdf",
  "status": "ready",
  "chunk_count": 42,
  "message": "Document processed successfully"
}
```

### GET `/documents`
List all indexed documents with metadata.

### DELETE `/documents/{document_id}`
Remove a document and invalidate retrieval entries (vector and BM25 tombstones).

---

## Knowledge Graph

### GET `/graph/stats`
Vector store and knowledge graph statistics.

### GET `/graph/search?q=diabetes`
Semantic search over indexed chunks.

---

## Medical Images

### POST `/images/upload`
Upload a medical image.

**Form Data:** `file` — image upload

### POST `/images/{image_id}/analyze`
Run analysis on an uploaded image.

### GET `/images`
List uploaded images.

### GET `/images/{image_id}`
Get analysis results for a specific image.

---

## Agentic Workflows

### GET `/agents/tools`
List available tools (medical calculator, drug lookup, search, etc.).

### POST `/agents/run`
Run an agentic workflow with tool usage (SSE stream).

**Request:**
```json
{
  "query": "Calculate BMI for a 70kg patient who is 1.75m tall"
}
```

### GET `/agents/workflows`
List completed workflow executions.

---

## Evaluation

### POST `/eval/run`
Evaluate a RAG response across 4 metrics.

**Request:**
```json
{
  "query": "What is hypertension?",
  "answer": "Hypertension is high blood pressure.",
  "contexts": ["Hypertension, or high blood pressure, is a chronic condition."]
}
```

**Response:**
```json
{
  "scores": {
    "faithfulness": 0.95,
    "relevance": 0.88,
    "citation_accuracy": 0.80,
    "context_precision": 0.75
  },
  "overall_score": 0.845
}
```

### GET `/eval/history`
Get past evaluation results.

---

## Fine-Tuning

### Datasets

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/fine-tune/datasets` | List datasets |
| `POST` | `/fine-tune/datasets` | Create dataset |
| `GET` | `/fine-tune/datasets/{id}` | Get dataset |
| `DELETE` | `/fine-tune/datasets/{id}` | Delete dataset |
| `POST` | `/fine-tune/datasets/{id}/generate` | Auto-generate from docs |
| `GET` | `/fine-tune/datasets/{id}/export` | Export as JSONL |

### Training Jobs

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/fine-tune/jobs` | List jobs |
| `POST` | `/fine-tune/jobs` | Create + start job |
| `GET` | `/fine-tune/jobs/{id}` | Get job status |
| `POST` | `/fine-tune/jobs/{id}/cancel` | Cancel job |

### Model Registry

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/fine-tune/models` | List models |
| `POST` | `/fine-tune/models/{id}/deploy` | Deploy adapter |
| `POST` | `/fine-tune/models/{id}/undeploy` | Undeploy adapter |

---

## Admin

### POST `/auth/bootstrap`
One-time first-admin bootstrap. Works only when the deployment has zero users, then returns a logged-in admin token bundle.

### GET `/admin/health`
Detailed system health with uptime, service status, vector store stats.

### GET `/admin/metrics`
Request metrics plus dashboard rollups for chat latency, retrieval latency, LLM/document failure rate, image analysis success rate, and worker queue depth.

### GET `/admin/sessions`
List active user sessions.

### GET `/admin/config`
Non-sensitive configuration display.

All `/admin/*` endpoints require admin JWT.

---

## Error Responses

All errors follow this format:
```json
{
  "detail": "Error message describing what went wrong"
}
```

| Status | Meaning |
|--------|---------|
| `400` | Bad request (invalid input) |
| `401` | Unauthorized (invalid/missing token) |
| `404` | Resource not found |
| `422` | Validation error |
| `429` | Rate limit exceeded |
| `500` | Internal server error |

---

## Rate Limiting

Requests are rate-limited to **60 per minute per IP** by default.

When exceeded, the response includes:
```
HTTP/1.1 429 Too Many Requests
Retry-After: 12
```
