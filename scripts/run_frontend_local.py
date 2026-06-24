#!/usr/bin/env python3
"""
Serve the static frontend locally and proxy backend requests to a remote URL.

Typical use:
    python3 scripts/run_frontend_local.py --backend https://mohi679-clinical-graphrag-backend.hf.space

The browser only talks to localhost, so this avoids CORS issues while letting
the backend stay on Hugging Face.
"""

from __future__ import annotations

import argparse
import errno
import http.client
import mimetypes
import posixpath
import ssl
import sys
import urllib.parse
from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
STATIC_ROOT = (REPO_ROOT / "frontend" / "public").resolve()
PROXY_PATH_PREFIXES = ("/api/",)
PROXY_EXACT_PATHS = {"/api", "/docs", "/redoc", "/openapi.json"}
HOP_BY_HOP_HEADERS = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailers",
    "transfer-encoding",
    "upgrade",
}


@dataclass(frozen=True)
class BackendTarget:
    base_url: str
    scheme: str
    netloc: str
    base_path: str
    verify_ssl: bool


def normalize_backend_url(raw_url: str) -> str:
    url = raw_url.strip().rstrip("/")
    parsed = urllib.parse.urlsplit(url)

    if parsed.scheme not in {"http", "https"}:
        raise ValueError("backend URL must start with http:// or https://")

    if parsed.netloc == "huggingface.co":
        parts = [part for part in parsed.path.split("/") if part]
        if len(parts) >= 3 and parts[0] == "spaces":
            username, space_name = parts[1], parts[2]
            return f"https://{username}-{space_name}.hf.space"

    return url


def parse_backend_target(raw_url: str, *, verify_ssl: bool) -> BackendTarget:
    base_url = normalize_backend_url(raw_url)
    parsed = urllib.parse.urlsplit(base_url)

    if not parsed.netloc:
        raise ValueError("backend URL is missing a host")

    base_path = parsed.path.rstrip("/")
    return BackendTarget(
        base_url=base_url,
        scheme=parsed.scheme,
        netloc=parsed.netloc,
        base_path=base_path,
        verify_ssl=verify_ssl,
    )


def build_target_path(base_path: str, request_path: str, query: str) -> str:
    path = request_path if request_path.startswith("/") else f"/{request_path}"
    merged = f"{base_path}{path}" if base_path else path
    if not merged:
        merged = "/"
    if query:
        return f"{merged}?{query}"
    return merged


def is_proxy_path(path: str) -> bool:
    return path in PROXY_EXACT_PATHS or any(path.startswith(prefix) for prefix in PROXY_PATH_PREFIXES)


class LocalFrontendHandler(BaseHTTPRequestHandler):
    server_version = "ClinicalGraphRAGLocal/1.0"
    protocol_version = "HTTP/1.0"

    def do_GET(self) -> None:
        self.handle_request()

    def do_HEAD(self) -> None:
        self.handle_request()

    def do_POST(self) -> None:
        self.handle_request()

    def do_PUT(self) -> None:
        self.handle_request()

    def do_PATCH(self) -> None:
        self.handle_request()

    def do_DELETE(self) -> None:
        self.handle_request()

    def do_OPTIONS(self) -> None:
        self.handle_request()

    def handle_request(self) -> None:
        parsed = urllib.parse.urlsplit(self.path)
        if is_proxy_path(parsed.path):
            self.proxy_request(parsed)
            return
        self.serve_static(parsed.path)

    def proxy_request(self, parsed: urllib.parse.SplitResult) -> None:
        backend: BackendTarget = self.server.backend  # type: ignore[attr-defined]
        target_path = build_target_path(backend.base_path, parsed.path, parsed.query)
        connection_cls = http.client.HTTPSConnection if backend.scheme == "https" else http.client.HTTPConnection
        if backend.scheme == "https":
            context = ssl.create_default_context() if backend.verify_ssl else ssl._create_unverified_context()
        else:
            context = None
        connection = connection_cls(backend.netloc, timeout=300, context=context) if context else connection_cls(backend.netloc, timeout=300)

        try:
            content_length = int(self.headers.get("Content-Length", "0") or "0")
            body = self.rfile.read(content_length) if content_length > 0 else None

            headers = {}
            for key, value in self.headers.items():
                if key.lower() in HOP_BY_HOP_HEADERS or key.lower() == "host":
                    continue
                headers[key] = value

            headers["Host"] = backend.netloc
            headers["X-Forwarded-Host"] = self.headers.get("Host", "")
            headers["X-Forwarded-Proto"] = "http"

            connection.request(self.command, target_path, body=body, headers=headers)
            response = connection.getresponse()

            self.send_response(response.status, response.reason)
            for key, value in response.getheaders():
                lower_key = key.lower()
                if lower_key in HOP_BY_HOP_HEADERS:
                    continue
                self.send_header(key, value)
            self.send_header("Connection", "close")
            self.end_headers()

            if self.command != "HEAD":
                while True:
                    chunk = response.read(64 * 1024)
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    self.wfile.flush()
        except ssl.SSLCertVerificationError as exc:  # pragma: no cover - exercised manually
            message = (
                f"Proxy SSL error: {exc}. "
                "Retry the local proxy with --insecure, or fix your Python certificates on macOS."
            )
            self.send_error(HTTPStatus.BAD_GATEWAY, message)
        except Exception as exc:  # pragma: no cover - exercised manually
            self.send_error(HTTPStatus.BAD_GATEWAY, f"Proxy error: {exc}")
        finally:
            connection.close()

    def serve_static(self, request_path: str) -> None:
        if request_path == "/":
            return self.send_file(STATIC_ROOT / "index.html", no_cache=True)

        relative_path = posixpath.normpath(urllib.parse.unquote(request_path)).lstrip("/")
        candidate = (STATIC_ROOT / relative_path).resolve()

        if STATIC_ROOT not in candidate.parents and candidate != STATIC_ROOT:
            self.send_error(HTTPStatus.FORBIDDEN, "Invalid path")
            return

        if candidate.is_file():
            return self.send_file(candidate, no_cache=candidate.name == "index.html")

        if "." not in Path(relative_path).name:
            return self.send_file(STATIC_ROOT / "index.html", no_cache=True)

        self.send_error(HTTPStatus.NOT_FOUND, "File not found")

    def send_file(self, file_path: Path, *, no_cache: bool) -> None:
        try:
            data = file_path.read_bytes()
        except FileNotFoundError:
            self.send_error(HTTPStatus.NOT_FOUND, "File not found")
            return

        content_type, _ = mimetypes.guess_type(str(file_path))
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type or "application/octet-stream")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()

        if self.command != "HEAD":
            self.wfile.write(data)

    def log_message(self, format: str, *args) -> None:
        sys.stdout.write(
            f"{self.address_string()} - [{self.log_date_time_string()}] {format % args}\n"
        )


class LocalFrontendServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, server_address: tuple[str, int], handler_class: type[BaseHTTPRequestHandler], backend: BackendTarget):
        super().__init__(server_address, handler_class)
        self.backend = backend


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the frontend locally and proxy /api to a remote backend.")
    parser.add_argument(
        "--backend",
        required=True,
        help="Remote backend base URL, for example https://mohi679-clinical-graphrag-backend.hf.space",
    )
    parser.add_argument("--host", default="127.0.0.1", help="Local host to bind. Default: 127.0.0.1")
    parser.add_argument("--port", type=int, default=3000, help="Local port to bind. Default: 3000")
    parser.add_argument(
        "--insecure",
        action="store_true",
        help="Disable HTTPS certificate verification for the remote backend. Use only for local troubleshooting.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    backend = parse_backend_target(args.backend, verify_ssl=not args.insecure)

    selected_port = args.port
    server = None
    for candidate_port in range(args.port, args.port + 20):
        try:
            server = LocalFrontendServer((args.host, candidate_port), LocalFrontendHandler, backend)
            selected_port = candidate_port
            break
        except OSError as exc:
            if exc.errno != errno.EADDRINUSE:
                raise

    if server is None:
        raise SystemExit(f"Could not bind a local frontend port in the range {args.port}-{args.port + 19}.")

    print(f"Frontend static root: {STATIC_ROOT}")
    print(f"Proxy backend:       {backend.base_url}")
    print(f"Verify SSL:          {'yes' if backend.verify_ssl else 'no'}")
    if selected_port != args.port:
        print(f"Requested port:      {args.port} (already in use)")
    print(f"Open in browser:     http://{args.host}:{selected_port}")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping local frontend server...")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
