from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any


MAX_REQUEST_BYTES = 16 * 1024 * 1024
TOKEN_LIMIT_FIELDS = {
    "max_tokens",
    "max_completion_tokens",
    "max_output_tokens",
    "maxTokens",
}


def transform_request(payload: dict[str, Any]) -> dict[str, Any]:
    """Keep high/medium reasoning and leave output length server-controlled."""
    transformed = dict(payload)
    for field in TOKEN_LIMIT_FIELDS:
        transformed.pop(field, None)
    if transformed.get("reasoning_effort") not in {"high", "medium"}:
        transformed["reasoning_effort"] = "high"
    messages = transformed.get("messages")
    if isinstance(messages, list):
        normalized_messages: list[Any] = []
        for message in messages:
            if isinstance(message, dict) and message.get("role") == "assistant":
                normalized = dict(message)
                normalized.pop("reasoning_content", None)
                normalized.pop("reasoning", None)
                normalized_messages.append(normalized)
            else:
                normalized_messages.append(message)
        transformed["messages"] = normalized_messages
    return transformed


class K2ProxyHandler(BaseHTTPRequestHandler):
    server_version = "BonsaiK2Proxy/1"
    protocol_version = "HTTP/1.1"

    def _json_response(self, status: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/health":
            self._json_response(200, {"ok": True})
            return
        if self.path == "/v1/models":
            self._json_response(
                200,
                {
                    "object": "list",
                    "data": [
                        {
                            "id": "MBZUAI-IFM/K2-Think-v2",
                            "object": "model",
                            "owned_by": "MBZUAI",
                        }
                    ],
                },
            )
            return
        self._json_response(404, {"error": "not found"})

    def do_POST(self) -> None:  # noqa: N802
        if self.path != "/v1/chat/completions":
            self._json_response(404, {"error": "not found"})
            return
        try:
            content_length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self._json_response(400, {"error": "invalid content length"})
            return
        if content_length <= 0 or content_length > MAX_REQUEST_BYTES:
            self._json_response(413, {"error": "request size rejected"})
            return
        try:
            decoded = json.loads(self.rfile.read(content_length))
        except (UnicodeDecodeError, json.JSONDecodeError):
            self._json_response(400, {"error": "invalid JSON"})
            return
        if not isinstance(decoded, dict):
            self._json_response(400, {"error": "JSON body must be an object"})
            return

        upstream_url = os.environ.get(
            "K2_UPSTREAM_URL", "https://api.k2think.ai/v2/chat/completions"
        )
        api_key = os.environ.get("K2THINK_API_KEY")
        if not api_key:
            self._json_response(503, {"error": "upstream credential unavailable"})
            return
        request = urllib.request.Request(
            upstream_url,
            method="POST",
            data=json.dumps(transform_request(decoded)).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {api_key}",
                "Accept": "application/json, text/event-stream",
                "Content-Type": "application/json",
            },
        )
        try:
            response = urllib.request.urlopen(request, timeout=900)
        except urllib.error.HTTPError as exc:
            body = exc.read(2 * 1024 * 1024 + 1)
            if len(body) > 2 * 1024 * 1024:
                body = b'{"error":"upstream error body too large"}'
            self.send_response(exc.code)
            self.send_header("Content-Type", exc.headers.get_content_type())
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        except (urllib.error.URLError, TimeoutError) as exc:
            self._json_response(502, {"error": f"upstream unavailable: {type(exc).__name__}"})
            return

        with response:
            self.send_response(response.status)
            self.send_header("Content-Type", response.headers.get("Content-Type", "application/json"))
            self.send_header("Cache-Control", "no-store")
            self.send_header("Connection", "close")
            self.end_headers()
            self.close_connection = True
            try:
                while chunk := response.read(64 * 1024):
                    self.wfile.write(chunk)
                    self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                return

    def log_message(self, format: str, *args: object) -> None:
        # BaseHTTPRequestHandler logs only method/path/status here; request bodies and
        # Authorization headers are never included.
        super().log_message(format, *args)


def main() -> None:
    host = os.environ.get("K2_PROXY_HOST", "127.0.0.1")
    port = int(os.environ.get("K2_PROXY_PORT", "18080"))
    server = ThreadingHTTPServer((host, port), K2ProxyHandler)
    server.serve_forever()


if __name__ == "__main__":
    main()
