#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Hudson Aikins / IntelIP
# SPDX-License-Identifier: Apache-2.0
"""Expose only selected GET endpoints to a Docker bridge, keeping the backend private."""
import argparse
import ipaddress
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import re
import sys
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import urlopen

READ_PATH = re.compile(r"/api/(?:health|info|organizations|remote/(?:organizations|projects|issues)(?:/[a-zA-Z0-9_-]+)?|repos(?:/[a-zA-Z0-9_-]+)?|workspaces(?:/[a-zA-Z0-9_-]+)?|sessions(?:/[a-zA-Z0-9_-]+)?|execution-processes(?:/[a-zA-Z0-9_-]+)?)\Z")


def handler(backend):
    class ReadOnly(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def send_response(self, code, message=None):
            if code >= 400:
                print(f"AgentShift bridge: {self.command} {urlsplit(self.path).path} -> {code}", file=sys.stderr, flush=True)
            super().send_response(code, message)

        def do_GET(self):
            parsed = urlsplit(self.path)
            if parsed.scheme or parsed.netloc or not READ_PATH.fullmatch(parsed.path):
                self.send_error(403, "Endpoint not allowed")
                return
            try:
                with urlopen(backend.rstrip("/") + self.path, timeout=15) as response:
                    data = response.read(8 * 1024 * 1024)
                    self.send_response(response.status)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(data)))
                    self.end_headers()
                    self.wfile.write(data)
            except HTTPError as error:
                self.send_error(error.code)
            except (URLError, TimeoutError):
                self.send_error(502, "Backend unavailable")

        def deny(self):
            self.send_error(405, "AgentShift worker access is read-only")

        do_POST = do_PUT = do_PATCH = do_DELETE = do_CONNECT = deny
    return ReadOnly


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bind", required=True, help="Docker bridge or WSL private address, never a public interface")
    parser.add_argument("--port", type=int, default=39001)
    parser.add_argument("--backend", default="http://127.0.0.1:3000")
    args = parser.parse_args()
    address = ipaddress.ip_address(args.bind)
    if not address.is_private or address.is_unspecified or address.is_loopback:
        parser.error("An explicit private bridge address is required")
    ThreadingHTTPServer((args.bind, args.port), handler(args.backend)).serve_forever()
