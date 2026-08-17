"""Simple mock target that records EventIds and returns reply references."""

from __future__ import annotations

from http.server import BaseHTTPRequestHandler, HTTPServer
import json
from urllib.parse import urlparse


SEEN: dict[str, str] = {}


class Handler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length)
        json.loads(raw.decode("utf-8") or "{}")  # consume/validate payload; identity is in headers
        event_id = self.headers.get("X-Outbox-Event-Id")
        path = urlparse(self.path).path
        if event_id in SEEN:
            reply = SEEN[event_id]
        else:
            reply = f"JE-{len(SEEN) + 1}"
            SEEN[event_id] = reply
        payload = {
            "success": True,
            "replyReferenceType": "JOURNAL_ENTRY",
            "replyReference": reply,
            "path": path,
        }
        data = json.dumps(payload).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("X-Outbox-Reply-Reference-Type", "JOURNAL_ENTRY")
        self.send_header("X-Outbox-Reply-Reference", reply)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, format: str, *args: object) -> None:  # noqa: A003
        return


if __name__ == "__main__":
    HTTPServer(("0.0.0.0", 8099), Handler).serve_forever()
