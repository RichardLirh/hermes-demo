"""Loopback-only human takeover UI. No API key, CDP URL or password in logs."""
import argparse
import json
import secrets
import threading
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from time import monotonic

from browser_bridge import BrowserBridge
from hermes_driver import HermesDriver


def serve(cdp, sandbox_id, port=18765, ready_file=None, lifetime=1800):
    bridge = BrowserBridge(cdp, sandbox_id)
    driver = HermesDriver(bridge)
    token = secrets.token_urlsafe(32)
    origin = f'http://127.0.0.1:{port}'

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def respond(self, status, value, cookie=None, html=False):
            data = value.encode() if html else json.dumps(value, ensure_ascii=False).encode()
            self.send_response(status)
            self.send_header('Content-Type', 'text/html; charset=utf-8' if html else 'application/json; charset=utf-8')
            self.send_header('Content-Length', str(len(data)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Content-Security-Policy', "default-src 'self'; img-src 'self' data:; script-src 'unsafe-inline'; style-src 'unsafe-inline'; frame-ancestors 'none'")
            if cookie:
                self.send_header('Set-Cookie', cookie)
            self.end_headers()
            self.wfile.write(data)

        def authenticated(self):
            cookie = SimpleCookie()
            cookie.load(self.headers.get('Cookie', ''))
            return 'demo_session' in cookie and secrets.compare_digest(cookie['demo_session'].value, token)

        def do_GET(self):
            if self.headers.get('Host') != f'127.0.0.1:{port}':
                return self.respond(403, {'error': 'Invalid host'})
            if self.path == '/':
                return self.respond(200, Path(__file__).with_name('index.html').read_text(encoding='utf-8'), html=True)
            if not self.authenticated():
                return self.respond(401, {'error': 'Open the launch link to authenticate'})
            if self.path == '/state':
                try:
                    return self.respond(200, {'browser': bridge.read(True), 'hermes': driver.status()})
                except Exception as exc:
                    return self.respond(503, {'error': str(exc)})
            return self.respond(404, {'error': 'Not found'})

        def do_POST(self):
            if self.headers.get('Host') != f'127.0.0.1:{port}' or self.headers.get('Origin') != origin:
                return self.respond(403, {'error': 'Same-origin requests required'})
            try:
                size = int(self.headers.get('Content-Length', '0'))
                if not 0 < size <= 16384:
                    raise ValueError('Invalid request size')
                body = json.loads(self.rfile.read(size))
                if self.path == '/auth':
                    if not secrets.compare_digest(str(body.get('token', '')), token):
                        return self.respond(401, {'error': 'Invalid launch token'})
                    return self.respond(200, {'ok': True}, f'demo_session={token}; HttpOnly; SameSite=Strict; Path=/')
                if not self.authenticated():
                    return self.respond(401, {'error': 'Authentication required'})
                epoch = body.get('epoch')
                if type(epoch) is not int:
                    raise ValueError('Control version required')
                if self.path == '/takeover':
                    result = bridge.transfer(epoch, 'USER')
                    driver.interrupt()
                elif self.path == '/run':
                    if driver.busy:
                        raise ValueError('Wait for the previous turn to stop')
                    state = bridge.control.snapshot()
                    if state['mode'] == 'USER':
                        state = bridge.transfer(epoch, 'AGENT')
                        epoch = state['epoch']
                    driver.start(str(body.get('prompt', ''))[:4000], epoch)
                    result = {'started': True}
                elif self.path == '/action':
                    result = bridge.action('USER', epoch, body['action'], body.get('selector', ''), body.get('value', ''))
                elif self.path == '/submit':
                    result = bridge.approve_submit(epoch, body['draft'], body['operationId'])
                elif self.path == '/stop':
                    bridge.control._check('local-owner', epoch)
                    result = {'stopping': True}
                    threading.Thread(target=httpd.shutdown, daemon=True).start()
                else:
                    return self.respond(404, {'error': 'Not found'})
                self.respond(200, result)
            except Exception as exc:
                self.respond(409, {'error': str(exc)})

    httpd = ThreadingHTTPServer(('127.0.0.1', port), Handler)
    if ready_file:
        Path(ready_file).write_text(json.dumps({'url': origin + '/#' + token, 'sandboxId': sandbox_id}), encoding='utf-8')
    timer = threading.Timer(lifetime, httpd.shutdown)
    timer.daemon = True
    timer.start()
    print(f'Human control ready on {origin}; automatic cleanup after {lifetime // 60} minutes.', flush=True)
    try:
        httpd.serve_forever(poll_interval=.5)
    finally:
        timer.cancel()
        driver.interrupt()
        bridge.close()
        httpd.server_close()
        if ready_file:
            Path(ready_file).unlink(missing_ok=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--cdp', default='http://127.0.0.1:19222')
    parser.add_argument('--sandbox-id', required=True)
    parser.add_argument('--ready-file')
    parser.add_argument('--port', type=int, default=18765)
    parser.add_argument('--lifetime', type=int, default=1800)
    args = parser.parse_args()
    serve(args.cdp, args.sandbox_id, args.port, args.ready_file, args.lifetime)
