# Examples

## Prerequisites

- Docker is running and the application stack is up.
- Demo data has been seeded and valid user credentials are available.
- The reverse-proxy API base is reachable at `http://localhost/api`, or `BASE_URL` has been overridden.

## Quick Setup

Source the setup script to log in and export a reusable JWT:

```bash
source examples/00_setup.sh
```

Defaults:

- `BASE_URL=http://localhost/api`
- `EMAIL=physician@clinicalgraph.ai`
- `PASSWORD=<your-demo-account-password>`

For the knowledge-graph admin example, set `ADMIN_EMAIL` and `ADMIN_PASSWORD` if your admin account differs from the demo defaults.

## Scripts

| Script | Description |
|--------|-------------|
| `examples/00_setup.sh` | Logs in through `POST /api/auth/login`, exports `TOKEN`, and verifies connectivity with `GET /api/health`. |
| `examples/01_upload_and_chat.sh` | Uploads `discharge_summary.txt`, polls document processing status, then calls `POST /api/chat/sync` and prints the grounded answer plus sources. |
| `examples/02_agent_drug_interaction.sh` | Runs `POST /api/agents/run` for a drug-interaction workflow and parses the SSE stream into readable reasoning, tool, verification, and completion output. |
| `examples/03_knowledge_graph.sh` | Logs in as an admin, seeds the graph, then pretty-prints `/graph/stats`, `/graph/temporal`, and `/graph/patients/Patient_A/lab-trends`. |
| `examples/04_medical_image.sh` | Downloads a public chest X-ray, uploads it, requests AI analysis, polls image status, and prints the findings summary. |
| `examples/05_evaluation.sh` | Loads one sample from `backend/data/golden_evaluation_dataset.jsonl`, calls `POST /api/eval/run`, and scores four core metrics with emoji indicators. |
| `examples/lab_trends.sh` | Fetches `/api/graph/patients/{patient_id}/lab-trends` for all labs and for a specific `lab=` filter using a pre-exported JWT. |

## Troubleshooting

- `curl: (7) Failed to connect`: start the stack with Docker Compose and confirm the API is available at `BASE_URL`.
- `401 Unauthorized` or `Invalid credentials`: set `EMAIL` and `PASSWORD` before sourcing `examples/00_setup.sh`, or set `ADMIN_EMAIL` and `ADMIN_PASSWORD` for the graph example.
- `403 Forbidden`: document, image, graph, chat, and evaluation routes require an authenticated user with sufficient role; use a physician or admin account where appropriate.
- `404 Graph seed endpoint is disabled`: the seed route is intentionally unavailable in production-like deployments; use a development or seeded demo environment for `examples/03_knowledge_graph.sh`.
- Document or image polling times out: background workers may be unavailable, or external AI providers may not be configured.
- Image analysis returns `503`: a vision provider is not configured, so `/api/images/{id}/analyze` cannot run yet.

Scripts require bash, curl, and python3 (stdlib only).
