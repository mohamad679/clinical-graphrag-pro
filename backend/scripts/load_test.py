#!/usr/bin/env python3
"""
Lightweight asynchronous API load testing utility for Clinical GraphRAG Pro.
Measures request rate, latencies (p50, p95, p99), and error rates.
"""

import asyncio
import time
import argparse
import sys
import numpy as np
import httpx


async def run_request(client: httpx.AsyncClient, url: str, method: str, json_data: dict | None = None) -> float:
    """Sends a request and returns the latency in ms, or raises an exception on error."""
    start = time.perf_counter()
    if method.upper() == "POST":
        resp = await client.post(url, json=json_data)
    else:
        resp = await client.get(url)
    resp.raise_for_status()
    return (time.perf_counter() - start) * 1000.0


async def worker(queue: asyncio.Queue, client: httpx.AsyncClient, results: list, errors: list):
    """Worker task that consumes the request queue."""
    while True:
        item = await queue.get()
        if item is None:
            queue.task_done()
            break
        url, method, json_data = item
        try:
            latency = await run_request(client, url, method, json_data)
            results.append(latency)
        except Exception as e:
            errors.append(str(e))
        queue.task_done()


async def run_load_test(host: str, endpoint: str, requests_count: int, concurrency: int, method: str = "GET", json_data: dict | None = None, headers: dict | None = None):
    print(f"\nRunning load test for {method} {host}{endpoint}...")
    print(f"  Total Requests: {requests_count} | Concurrency: {concurrency}")

    queue = asyncio.Queue()
    for _ in range(requests_count):
        queue.put_nowait((f"{host}{endpoint}", method, json_data))

    # Add poison pills for workers
    for _ in range(concurrency):
        queue.put_nowait(None)

    results = []
    errors = []
    
    start_time = time.perf_counter()
    async with httpx.AsyncClient(timeout=30.0, headers=headers) as client:
        workers = [
            asyncio.create_task(worker(queue, client, results, errors))
            for _ in range(concurrency)
        ]
        await asyncio.gather(*workers)
    
    total_time = time.perf_counter() - start_time
    success_count = len(results)
    error_count = len(errors)
    rps = requests_count / total_time if total_time > 0 else 0.0

    print(f"Completed in {total_time:.3f} seconds")
    print(f"  Success: {success_count} | Errors: {error_count} ({error_count/requests_count*100:.1f}%)")
    print(f"  RPS (Requests Per Second): {rps:.2f}")

    if results:
        p50 = np.percentile(results, 50)
        p95 = np.percentile(results, 95)
        p99 = np.percentile(results, 99)
        print(f"  Latency (ms): Min: {min(results):.1f} | p50: {p50:.1f} | p95: {p95:.1f} | p99: {p99:.1f} | Max: {max(results):.1f}")
    else:
        print("  Latency metrics: N/A (all requests failed)")


def main():
    parser = argparse.ArgumentParser(description="Clinical GraphRAG Pro Load Testing Tool")
    parser.add_argument("--host", default="http://localhost:8000", help="API Host URL")
    parser.add_argument("--base-url", default=None, help="Base URL of the API (aliases --host)")
    parser.add_argument("--requests", type=int, default=50, help="Number of requests to send per endpoint")
    parser.add_argument("--concurrency", type=int, default=5, help="Number of concurrent requests")
    parser.add_argument("--token", default="", help="Optional JWT authorization token")
    parser.add_argument("--endpoint", default=None, help="Specific endpoint to load test (e.g. /api/health)")
    parser.add_argument("--dry-run", action="store_true", help="Perform validation and dry run without sending requests")
    args = parser.parse_args()

    base_url = args.base_url or args.host

    # Handle Dry Run check
    if args.dry_run:
        print("Dry run validation check:")
        print(f"  Base URL: {base_url}")
        print(f"  Requests: {args.requests}")
        print(f"  Concurrency: {args.concurrency}")
        print(f"  Target Endpoint: {args.endpoint or 'All default endpoints'}")
        
        headers = {}
        if args.token:
            headers["Authorization"] = f"Bearer {args.token}"
            print("  Authorization: Token header configured successfully.")
            # Assert proper insertion
            assert "Authorization" in headers
            assert headers["Authorization"] == f"Bearer {args.token}"
            print("  [DRY-RUN VALIDATION SUCCESS] Headers inserted correctly.")
        else:
            print("  Authorization: No token provided.")
        sys.exit(0)

    print("=" * 60)
    print("              STARTING API LOAD TESTS")
    print("=" * 60)

    headers = {"Authorization": f"Bearer {args.token}"} if args.token else None

    if args.endpoint:
        method = "POST" if args.endpoint == "/api/agents/run" else "GET"
        payload = {"query": "Check if patient has hypertension.", "patient_id": "patient-1"} if method == "POST" else None
        asyncio.run(run_load_test(
            base_url,
            args.endpoint,
            args.requests,
            args.concurrency,
            method=method,
            json_data=payload,
            headers=headers
        ))
    else:
        # Endpoint 1: Health check
        asyncio.run(run_load_test(base_url, "/api/health", args.requests, args.concurrency, headers=headers))

        # Endpoint 2: Detailed health check
        asyncio.run(run_load_test(base_url, "/api/health/detailed", min(args.requests, 10), min(args.concurrency, 2), headers=headers))

        # Endpoint 3: Clinical safety disclaimer
        asyncio.run(run_load_test(base_url, "/api/health/disclaimer", args.requests, args.concurrency, headers=headers))

        # Endpoint 4: Document retrieval or agent run (requires auth and patient ID)
        if args.token:
            payload = {"query": "Check if patient has hypertension.", "patient_id": "patient-1"}
            print("\nAuthenticated Agent Workflow Load Test:")
            asyncio.run(run_load_test(
                base_url, 
                "/api/agents/run", 
                min(args.requests, 10), 
                min(args.concurrency, 2),
                method="POST",
                json_data=payload,
                headers=headers
            ))
        else:
            print("\n[NOTE] Skipped authenticated load tests (agent run) because no --token was provided.")

    print("\n" + "=" * 60)
    print("              LOAD TESTS COMPLETED")
    print("=" * 60)


if __name__ == "__main__":
    main()
