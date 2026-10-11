#!/usr/bin/env python3
import http.server
import socketserver
import os
import json
import sys

PORT = 8050
DIRECTORY = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(DIRECTORY)
DATA_FILE_PATH = os.path.join(PROJECT_ROOT, "trade_retrospective.json")

class DashboardHTTPRequestHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        # Serve files from the dashboard directory
        super().__init__(*args, directory=DIRECTORY, **kwargs)

    def do_GET(self):
        # Expose the trade_retrospective.json via a direct API endpoint or asset
        if self.path == "/api/retrospective" or self.path == "/trade_retrospective.json":
            self.serve_retrospective_json()
        else:
            super().do_GET()

    def serve_retrospective_json(self):
        if not os.path.exists(DATA_FILE_PATH):
            self.send_response(404)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"error": "trade_retrospective.json not found in project root"}).encode("utf-8"))
            return

        try:
            with open(DATA_FILE_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            
            response_bytes = json.dumps(data, ensure_ascii=False).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(response_bytes)))
            self.send_header("Access-Control-Allow-Origin", "*") # Enable CORS for development
            self.end_headers()
            self.wfile.write(response_bytes)
        except Exception as e:
            self.send_response(500)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"error": str(e)}).encode("utf-8"))

def main():
    # Changes python directory to the directory containing this script
    os.chdir(DIRECTORY)
    
    # Allow port reuse
    socketserver.TCPServer.allow_reuse_address = True
    
    with socketserver.TCPServer(("", PORT), DashboardHTTPRequestHandler) as httpd:
        print(f"\n" + "="*60)
        print(f"🚀 AI-Vibe-Trader Retro Dashboard is running!")
        print(f"👉 Local URL: http://localhost:{PORT}")
        print(f"👉 Serving data from: {DATA_FILE_PATH}")
        print(f"="*60 + "\n")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nShutting down server...")
            sys.exit(0)

if __name__ == "__main__":
    main()
