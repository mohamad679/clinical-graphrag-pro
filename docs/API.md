# API Reference

> Base URL: `http://localhost:8000/api`
> Interactive docs: `http://localhost:8000/docs`

---

## Authentication

### POST `/auth/login`
Authenticate and receive a JWT token.

**Request:**
```json
{
  "email": "admin@clinicalgraph.ai",
  "password": "admin123"
}
```

**Response:**
```json
{
  "token": "eyJhbGciOi...",
  "user": {
    "id": "demo-admin-001",
    "email": "admin@clinicalgraph.ai",
    "name": "Dr. Admin",
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
    {"document_name": "guidelines.pdf", "chunk_text": "...", "score": 0.92}
  ],
  "session_id": "abc-123"
}
```

### POST `/chat/stream`
Streaming chat via Server-Sent Events (SSE).

### GET `/chat/sessions`
List all chat sessions.

### GET `/chat/sessions/{session_id}`
Get messages for a specific session.

---

## Documents

### POST `/documents/upload`
Upload a clinical document (PDF, TXT, MD).

**Form Data:** `file` — multipart file upload

**Response:**
```json
{
  "document_id": "doc-uuid",
  "filename": "guidelines.pdf",
  "chunks_created": 42,
  "message": "Document processed successfully"
}
```

### GET `/documents`
List all indexed documents with metadata.

### DELETE `/documents/{document_id}`
Remove a document and its chunks from the index.

---

## Knowledge Graph

### GET `/graph/stats`
Vector store and knowledge graph statistics.

### GET `/graph/search?query=diabetes`
Search the knowledge graph for entities and relationships.

---

## Medical Images

### POST `/images/analyze`
Analyze a medical image using vision AI.

**Form Data:** `file` — image file, `analysis_type` — "general" | "xray" | "pathology" | "dermatology"

### GET `/images`
List analyzed images.

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

### GET `/admin/health`
Detailed system health with uptime, service status, vector store stats.

### GET `/admin/metrics`
Request metrics: total requests, error rate, P95 latency, top endpoints.

### GET `/admin/sessions`
List active user sessions.

### GET `/admin/config`
Non-sensitive configuration display.

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
