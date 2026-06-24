from __future__ import annotations

import argparse
import base64
import sys
import time
from typing import Any

import httpx

TINY_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO3Zx4cAAAAASUVORK5CYII="
)


def _api_base(base_url: str) -> str:
    normalized = base_url.rstrip("/")
    return normalized if normalized.endswith("/api") else f"{normalized}/api"


def _raise_for_status(response: httpx.Response, action: str) -> dict[str, Any]:
    try:
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        raise RuntimeError(f"{action} failed: {exc.response.status_code} {exc.response.text}") from exc
    if not response.content:
        return {}
    return response.json()


def _poll(
    client: httpx.Client,
    path: str,
    *,
    timeout_seconds: int,
    interval_seconds: float,
    action: str,
    predicate,
) -> dict[str, Any]:
    deadline = time.time() + timeout_seconds
    last_payload: dict[str, Any] | None = None
    while time.time() < deadline:
        payload = _raise_for_status(client.get(path), action)
        last_payload = payload
        if predicate(payload):
            return payload
        time.sleep(interval_seconds)
    raise RuntimeError(f"{action} timed out after {timeout_seconds}s. Last payload: {last_payload}")


def run(base_url: str, email: str, password: str, *, timeout_seconds: int, insecure: bool) -> None:
    client = httpx.Client(
        base_url=_api_base(base_url),
        timeout=30.0,
        follow_redirects=True,
        verify=not insecure,
    )
    document_id: str | None = None
    image_id: str | None = None

    try:
        _raise_for_status(client.get("/health/detailed"), "health check")

        login_payload = _raise_for_status(
            client.post("/auth/login", json={"email": email, "password": password}),
            "login",
        )
        access_token = login_payload["access_token"]
        client.headers["Authorization"] = f"Bearer {access_token}"

        document_payload = _raise_for_status(
            client.post(
                "/documents/upload",
                files={
                    "file": (
                        "staging-smoke.txt",
                        b"Staging smoke test document. The patient reports chest pain and requires follow up.",
                        "text/plain",
                    )
                },
            ),
            "document upload",
        )
        document_id = str(document_payload["id"])

        document_status = _poll(
            client,
            f"/documents/{document_id}/status",
            timeout_seconds=timeout_seconds,
            interval_seconds=5.0,
            action="document processing",
            predicate=lambda payload: payload.get("status") in {"ready", "error", "failed"},
        )
        if document_status.get("status") != "ready":
            raise RuntimeError(f"Document processing failed: {document_status}")

        chat_payload = _raise_for_status(
            client.post(
                "/chat/sync",
                json={
                    "message": "What does the uploaded staging smoke document say?",
                    "attached_document_id": document_id,
                },
            ),
            "chat sync",
        )
        if not str(chat_payload.get("answer", "")).strip():
            raise RuntimeError(f"Chat response was empty: {chat_payload}")

        image_payload = _raise_for_status(
            client.post(
                "/images/upload",
                files={"file": ("staging-smoke.png", TINY_PNG, "image/png")},
            ),
            "image upload",
        )
        image_id = str(image_payload["id"])

        _raise_for_status(
            client.post(
                f"/images/{image_id}/analyze",
                json={"additional_context": "Staging smoke test request"},
            ),
            "image analysis dispatch",
        )

        image_status = _poll(
            client,
            f"/images/{image_id}",
            timeout_seconds=timeout_seconds,
            interval_seconds=5.0,
            action="image analysis",
            predicate=lambda payload: payload.get("analysis_status")
            in {"ai_generated", "clinician_reviewed", "corrected", "failed"},
        )
        if image_status.get("analysis_status") == "failed":
            raise RuntimeError(f"Image analysis failed: {image_status}")

        graph_payload = _raise_for_status(
            client.get(
                "/graph/search",
                params={"q": "chest pain follow up", "top_k": 3},
            ),
            "graph search",
        )
        if graph_payload.get("total", 0) < 1:
            raise RuntimeError(f"Graph search returned no results: {graph_payload}")

        print(
            "[PASS] Staging smoke completed:",
            {
                "document_id": document_id,
                "image_id": image_id,
                "chat_session_id": chat_payload.get("session_id"),
                "graph_results": graph_payload.get("total", 0),
            },
        )
    finally:
        if image_id:
            try:
                client.delete(f"/images/{image_id}")
            except Exception:
                pass
        if document_id:
            try:
                client.delete(f"/documents/{document_id}")
            except Exception:
                pass
        client.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a staging smoke flow against the API.")
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--email", required=True)
    parser.add_argument("--password", required=True)
    parser.add_argument("--timeout-seconds", type=int, default=300)
    parser.add_argument("--insecure", action="store_true")
    args = parser.parse_args()

    try:
        run(
            args.base_url,
            args.email,
            args.password,
            timeout_seconds=args.timeout_seconds,
            insecure=args.insecure,
        )
    except Exception as exc:
        print(f"[FAIL] {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

