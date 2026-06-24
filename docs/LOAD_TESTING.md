# API Load Testing

Clinical GraphRAG Pro includes an asynchronous performance benchmarking script to measure request throughput, latencies, and error rates.

---

## Running the Load Tester

The load testing utility runs in Python without heavy external dependencies. It uses `httpx` to fire concurrent requests to target endpoints.

### Usage

1. Open a terminal and navigate to the backend workspace.
2. Run the load test script:
   ```bash
   python3 backend/scripts/load_test.py --host http://localhost:8000 --requests 50 --concurrency 5
   ```

### Tested Endpoints
- **Health Check (`/api/health`)**: Basic server liveness check.
- **Detailed Health Check (`/api/health/detailed`)**: Evaluates backing DB, Redis, Neo4j, and queue statuses.
- **Clinical Disclaimer (`/api/health/disclaimer`)**: Returns disclaimer info.
- **Agent Workflow Runs (`/api/agents/run`)** (Optional): Tested only if a valid `--token` is provided.

### Report Output
For each endpoint tested, the tool outputs:
- **Requests Per Second (RPS)**
- **p50, p95, p99 Latency Profiles** (in milliseconds)
- **Success and Error Rates**
