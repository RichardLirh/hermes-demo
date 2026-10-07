"""Loopback-only, fictional CRM target for browser integration tests."""
import json
import secrets
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

PAGE = Path(__file__).with_name("demo.html").read_bytes()
SESSIONS = set()
RECORDS = {}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def reply(self, status, body, cookie=None):
        data = json.dumps(body, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        if cookie:
            self.send_header("Set-Cookie", cookie)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path != "/":
            return self.reply(404, {"error": "Not found"})
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(PAGE)))
        self.end_headers()
        self.wfile.write(PAGE)

    def do_POST(self):
        try:
            size = int(self.headers.get("Content-Length", 0))
            if not 0 < size <= 8192:
                raise ValueError()
            data = json.loads(self.rfile.read(size))
            if not isinstance(data, dict):
                raise ValueError()
        except (ValueError, TypeError):
            return self.reply(400, {"error": "Invalid request"})
        if self.path == "/api/login":
            if data.get("username") != "demo" or data.get("password") != "demo-password":
                return self.reply(401, {"error": "演示账号或密码错误"})
            token = secrets.token_urlsafe(24)
            SESSIONS.add(token)
            return self.reply(200, {"ok": True}, f"demo_session={token}; HttpOnly; SameSite=Strict; Path=/")
        if self.path != "/api/followups":
            return self.reply(404, {"error": "Not found"})
        cookie = SimpleCookie(self.headers.get("Cookie", ""))
        token = cookie.get("demo_session")
        if not token or token.value not in SESSIONS:
            return self.reply(401, {"error": "请先登录"})
        text, op = data.get("text"), data.get("operationId")
        if data.get("customerId") != "demo-customer-001" or not isinstance(text, str) or not text.strip() or not isinstance(op, str) or not 1 <= len(op) <= 128:
            return self.reply(400, {"error": "请选择客户并填写跟进内容"})
        if op in RECORDS:
            if RECORDS[op]["text"] != text:
                return self.reply(409, {"error": "同一提交编号不能用于不同内容"})
            return self.reply(200, RECORDS[op])
        record = {"id": "followup-" + str(len(RECORDS) + 1), "text": text, "customerId": "demo-customer-001"}
        RECORDS[op] = record
        return self.reply(201, record)


if __name__ == "__main__":
    print("Fictional CRM: http://127.0.0.1:8765", flush=True)
    HTTPServer(("127.0.0.1", 8765), Handler).serve_forever()
