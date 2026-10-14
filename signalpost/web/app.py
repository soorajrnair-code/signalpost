"""
Lightweight local HTTP server serving the SignalPost interactive Web Dashboard.
Zero additional dependencies required.
"""

import os
import json
import urllib.parse
from http.server import HTTPServer, BaseHTTPRequestHandler

from signalpost.agent import SignalPostAgent
from signalpost.storage import Storage

WEB_DIR = os.path.dirname(os.path.abspath(__file__))


class SignalPostHandler(BaseHTTPRequestHandler):
    agent = None
    storage = None

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        query_params = urllib.parse.parse_qs(parsed.query)

        if path == "/" or path == "/index.html":
            self.serve_file(os.path.join(WEB_DIR, "index.html"), "text/html")
        elif path == "/api/profile":
            q = query_params.get("query", [""])[0]
            if not q:
                self.send_json({"error": "No query provided"}, status=400)
                return
            profile = self.agent.research_company(q, fetch_web=False)
            self.send_json(profile.to_dict())
        elif path == "/api/profiles":
            limit = int(query_params.get("limit", [25])[0])
            profiles = self.storage.list_all(limit=limit)
            self.send_json([p.to_dict() for p in profiles])
        else:
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b"404 Not Found")

    def serve_file(self, filepath: str, content_type: str):
        if not os.path.exists(filepath):
            self.send_response(404)
            self.end_headers()
            return
        with open(filepath, "rb") as f:
            content = f.read()
        self.send_response(200)
        self.send_header("Content-Type", f"{content_type}; charset=utf-8")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def send_json(self, data, status: int = 200):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        # Clean logging
        pass


def run_server(port: int = 8080):
    storage = Storage()
    agent = SignalPostAgent(storage=storage)
    SignalPostHandler.storage = storage
    SignalPostHandler.agent = agent

    server = HTTPServer(("127.0.0.1", port), SignalPostHandler)
    print("\n" + "=" * 65)
    print(f" [+] SignalPost Interactive Dashboard running at:")
    print(f"     http://127.0.0.1:{port}")
    print("=" * 65)
    print(" Press Ctrl+C to stop.\n")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping server.")
        server.server_close()


if __name__ == "__main__":
    run_server()
