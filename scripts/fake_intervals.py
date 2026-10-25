"""A stand-in for intervals.icu, for trying workout delivery locally without a real account.

    python scripts/fake_intervals.py 8099
    INTERVALS_BASE_URL=http://localhost:8099 INTERVALS_CLIENT_ID=dev INTERVALS_CLIENT_SECRET=dev-secret ...

It implements only what CoachQuest uses: the OAuth authorize page (approves at
once), the token exchange, events bulk upsert and bulk delete, and
disconnect-app. Received events are printed. Set FAIL=503 (or 401, 429...) to
make calendar calls fail with that status.
"""

import json
import os
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlencode, urlparse

EVENTS: dict[str, dict] = {}


class Handler(BaseHTTPRequestHandler):
    def _send(self, status, body=None, headers=None):
        self.send_response(status)
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        data = json.dumps(body).encode() if body is not None else b""
        if body is not None:
            self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        return self.rfile.read(n).decode() if n else ""

    def do_GET(self):
        url = urlparse(self.path)
        if url.path == "/oauth/authorize":
            q = parse_qs(url.query)
            back = q["redirect_uri"][0] + "?" + urlencode({"code": "dev-code", "state": q["state"][0]})
            return self._send(302, headers={"Location": back})
        if url.path == "/events":
            return self._send(200, list(EVENTS.values()))
        self._send(404, {"error": "not here"})

    def do_POST(self):
        url = urlparse(self.path)
        body = self._body()
        if url.path == "/api/oauth/token":
            return self._send(
                200,
                {
                    "access_token": "dev-token",
                    "token_type": "Bearer",
                    "scope": "CALENDAR:WRITE",
                    "athlete": {"id": "i1", "name": "Dev Rider"},
                },
            )
        if os.getenv("FAIL"):
            return self._send(int(os.environ["FAIL"]), {"error": "forced"}, {"Retry-After": "30"})
        if url.path.endswith("/events/bulk"):
            out = []
            for e in json.loads(body):
                ev = EVENTS.setdefault(e["external_id"], {"id": 1000 + len(EVENTS)})
                ev.update({k: v for k, v in e.items() if k != "file_contents"})
                out.append(ev)
                print("upsert", e["external_id"], e["start_date_local"], e["name"], flush=True)
            return self._send(200, out)
        self._send(404, {})

    def do_PUT(self):
        if self.path.startswith("/api/v1/athlete/0/events/bulk-delete"):
            gone = [EVENTS.pop(e["external_id"], None) for e in json.loads(self._body())]
            print("delete", gone, flush=True)
            return self._send(200, {"deleted": sum(1 for g in gone if g)})
        self._send(404, {})

    def do_DELETE(self):
        print("disconnect-app", flush=True)
        self._send(200, {})


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8099
    print(f"Fake intervals.icu on http://localhost:{port}", flush=True)
    HTTPServer(("127.0.0.1", port), Handler).serve_forever()
