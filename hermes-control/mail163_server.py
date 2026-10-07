"""Same-session 163 human login. Mail contents never enter login logs or model history.

This adapter deliberately starts in manual mode. Sending/scanning is not marked
complete until a separately verified mail executor supplies actual UI evidence.
"""
import base64
import concurrent.futures
import json
import queue
import re
import secrets
import threading
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

from browser_bridge import BrowserBridge, Rejected
from control import SessionControl
from uuid import uuid4


def allowed_mail_url(url):
    parsed = urlsplit(url)
    return parsed.scheme == 'https' and (parsed.hostname == '163.com' or
           (parsed.hostname or '').endswith('.163.com') or
           parsed.hostname == '126.com' or (parsed.hostname or '').endswith('.126.com'))


class MailBridge(BrowserBridge):
    def __init__(self, cdp, sandbox_id, config):
        self.config = config
        self.authenticated = False
        self.identity = None
        self.mail_report = None
        self.send_state = 'not_started'
        self.mail_events = []
        self.driver = None
        self.requested_identity = None
        self.control = SessionControl('local-owner', config['run_id'], sandbox_id, str(uuid4()))
        self.control.transfer('local-owner', 1, 'USER')
        self.jobs = queue.Queue()
        self.ready = concurrent.futures.Future()
        self.thread = threading.Thread(target=self._worker, args=(cdp,), daemon=True)
        self.thread.start()
        self.ready.result(timeout=70)

    def _worker(self, cdp):
        from playwright.sync_api import sync_playwright
        try:
            with sync_playwright() as pw:
                browser = pw.chromium.connect_over_cdp(cdp, timeout=30000)
                self.page = browser.contexts[0].pages[0]
                self.page.set_default_timeout(5000)
                self.page.goto('https://mail.163.com/', wait_until='domcontentloaded', timeout=60000)
                self.ready.set_result(True)
                while True:
                    job = self.jobs.get()
                    if job is None:
                        break
                    fn, future = job
                    if not future.set_running_or_notify_cancel():
                        continue
                    try:
                        future.set_result(fn())
                    except Exception as exc:
                        future.set_exception(exc)
                browser.close()
        except Exception as exc:
            if not self.ready.done():
                self.ready.set_exception(exc)

    def _read(self, screenshot=False):
        # Do not expose login DOM, inputs, cookies, URL query tokens or credentials.
        parsed = urlsplit(self.page.url)
        if self.authenticated:
            if not self._try_identity(self.identity):
                self.authenticated=False
        elif self.requested_identity:
            self._try_identity(self.requested_identity)
        value = {'url': f'{parsed.scheme}://{parsed.netloc}{parsed.path}',
                 'title': self.page.title(), 'control': self.control.snapshot(),
                 'workflow': 'mail163', 'authenticated': self.authenticated,
                 'identity': self.identity, 'scan_window': self.config['scan_window'],
                 'phase': 'ready_for_mail_adapter' if self.authenticated else 'awaiting_login',
                 'send_state': self.send_state, 'report': self.mail_report,
                 'events': self.mail_events[-20:]}
        if self.driver:
            value['hermes'] = self.driver.status()
        if screenshot:
            masks = []
            for frame in self.page.frames:
                masks.append(frame.locator('input[type=password]'))
            value['image'] = base64.b64encode(self.page.screenshot(mask=masks)).decode()
        return value

    def _try_identity(self, address):
        parsed=urlsplit(self.page.url)
        if parsed.scheme!='https' or parsed.hostname!='mail.163.com':
            return False
        try:
            account=self.page.locator('ul[role="navigation"] li[name="account"] #spnUid')
            if account.count()!=1 or not account.is_visible():
                return False
            if account.inner_text().strip().lower()!=address:
                return False
            was_authenticated=self.authenticated
            self.identity,self.authenticated=address,True
            if not was_authenticated:
                self.mail_events.append('人工登录已验证，保持同一浏览器会话；尚未发送邮件或完成扫描')
            return True
        except Exception:
            return False

    def login(self,epoch,address,password):
        address=str(address).strip().lower()
        if not re.fullmatch(r'[a-z0-9_.+-]+@163\.com',address):
            raise Rejected('请输入完整的 @163.com 邮箱账号')
        if not isinstance(password,str) or not 1<=len(password)<=4000:
            raise Rejected('请输入密码')
        def perform():
            if self.authenticated:
                raise Rejected('当前会话已登录，请继续原任务')
            if urlsplit(self.page.url).hostname!='mail.163.com':
                raise Rejected('当前页面不是163登录页，请刷新后检查')
            frames=[frame for frame in self.page.frames if urlsplit(frame.url).scheme=='https' and urlsplit(frame.url).hostname=='dl.reg.163.com']
            candidates=[]
            for frame in frames:
                accounts=frame.locator('input[name="email"][type="text"]')
                passwords=frame.locator('input[name="password"][type="password"]')
                buttons=frame.locator('a#dologin')
                if accounts.count()==passwords.count()==buttons.count()==1 and accounts.is_visible() and passwords.is_visible() and buttons.is_visible():
                    candidates.append((frame,accounts,passwords,buttons))
            if len(candidates)!=1:
                raise Rejected('登录控件已变化或当前是扫码页；请切换到密码登录后重试')
            frame,account_box,password_box,button=candidates[0]
            account_box.fill(address)
            # Revalidate origin/type immediately before writing the password.
            parsed_frame=urlsplit(frame.url)
            if parsed_frame.scheme!='https' or parsed_frame.hostname!='dl.reg.163.com' or password_box.get_attribute('type')!='password':
                raise Rejected('密码输入框校验失败，未输入密码')
            password_box.fill(password)
            self.requested_identity=address
            button.click()
            return {'submitted':True,'message':'登录信息已输入原站；如出现验证码或扫码，请在下方云端画面自行完成。'}
        return self.call(lambda:self.control.operate('local-owner',epoch,'USER',perform))

    def human(self, epoch, body):
        def perform():
            action = body.get('action')
            if action == 'click':
                x, y = body.get('x'), body.get('y')
                size = self.page.viewport_size or {'width': 1280, 'height': 800}
                if not isinstance(x, (int, float)) or not isinstance(y, (int, float)) or not (0 <= x < size['width'] and 0 <= y < size['height']):
                    raise ValueError('Click outside viewport')
                self.page.mouse.click(x, y)
            elif action == 'type':
                text = body.get('text', '')
                if not isinstance(text, str) or len(text) > 4000:
                    raise ValueError('Invalid input')
                self.page.keyboard.insert_text(text)
            elif action == 'key':
                key = body.get('key')
                if key not in {'Enter', 'Tab', 'Backspace', 'Escape', 'Control+A'}:
                    raise ValueError('Unsupported key')
                self.page.keyboard.press(key)
            elif action == 'scroll':
                self.page.mouse.wheel(0, max(-700, min(700, int(body.get('dy', 500)))))
            elif action == 'drag':
                points = body.get('points', [])
                size = self.page.viewport_size or {'width':1280,'height':800}
                if not 2 <= len(points) <= 150 or any(not 0<=p['x']<size['width'] or not 0<=p['y']<size['height'] for p in points):
                    raise ValueError('Invalid pointer path')
                self.page.mouse.move(points[0]['x'], points[0]['y'])
                self.page.mouse.down()
                try:
                    for point in points[1:]:
                        self.page.mouse.move(point['x'], point['y'])
                        self.page.wait_for_timeout(12)
                finally:
                    self.page.mouse.up()
            else:
                raise ValueError('Unsupported human action')
            return {'ok': True}
        return self.call(lambda: self.control.operate('local-owner', epoch, 'USER', perform))

    def confirm_login(self, epoch, address):
        address = str(address).strip().lower()
        if not re.fullmatch(r'[a-z0-9_.+-]+@163\.com', address):
            raise Rejected('请输入当前登录的完整 @163.com 邮箱地址')
        def perform():
            self.control._check('local-owner', epoch, 'USER')
            if not allowed_mail_url(self.page.url):
                raise Rejected('当前页面不是网易邮箱域名')
            if not self._try_identity(address):
                raise Rejected('尚未在邮箱顶部识别到该账号及邮箱导航；请完成登录，展开账号后再继续')
            return {'ok': True, 'identity': address}
        return self.call(perform)

    def mail_action(self, epoch, body):
        from mail163_adapter import handle
        return self.call(lambda: self.control.operate('local-owner', epoch, 'AGENT', lambda:handle(self,body)))

    def start_mail(self, epoch):
        if not self.authenticated:
            raise Rejected('请先完成人工登录')
        if self.driver and self.driver.busy:
            raise Rejected('模型仍在执行')
        from mail163_driver import MailHermesDriver
        self.driver = self.driver or MailHermesDriver(self)
        control=self.control.snapshot()
        if control['mode']=='USER':
            control=self.transfer(epoch,'AGENT')
        prompt='完成用户授权的163任务。先观察真实邮箱界面。时间窗：'+json.dumps(self.config['scan_window'],ensure_ascii=False)+'。仅给本人发送服务端固定联调邮件，之后扫描时间窗内邮件并总结，附覆盖范围和遗漏。'
        if self.config.get('scan_only'):
            prompt='这是仅扫描恢复任务。绝不发信，也不调用send_self。沿用原任务时间窗：'+json.dumps(self.config['scan_window'],ensure_ascii=False)+'。先observe然后scan_next，直到scan_complete才总结。保留原发送账本状态。'
        self.driver.start(prompt,control['epoch'])
        return {'started':True}

    def takeover(self,epoch):
        value=self.transfer(epoch,'USER')
        if self.driver:
            self.driver.interrupt()
        return value

    def close(self):
        if self.driver:
            self.driver.interrupt()
        super().close()

    def inspect_mail(self, epoch):
        """Read the actual authenticated UI, never an imagined site structure."""
        def perform():
            self.control._check('local-owner', epoch, 'USER')
            if not self.authenticated or not allowed_mail_url(self.page.url):
                raise Rejected('请先完成人工登录确认')
            frames = []
            for index, frame in enumerate(self.page.frames):
                if frame!=self.page.main_frame and not frame.frame_element().is_visible():
                    continue
                if not allowed_mail_url(frame.url) and frame != self.page.main_frame:
                    continue
                data = frame.locator('body').evaluate('''body => {
                    const nodes=[];
                    for(const el of body.querySelectorAll('a,button,input,textarea,[role],label,[contenteditable=true],iframe')) {
                        const r=el.getBoundingClientRect();
                        if(!r.width||!r.height||getComputedStyle(el).visibility==='hidden')continue;
                        if(el.type==='password')continue;
                        nodes.push({tag:el.tagName,role:el.getAttribute('role'),id:el.id,name:el.getAttribute('name'),
                          type:el.getAttribute('type'),label:el.getAttribute('aria-label'),placeholder:el.getAttribute('placeholder'),
                          text:(el.innerText||'').slice(0,250),title:el.getAttribute('title'),
                          x:r.x,y:r.y,width:r.width,height:r.height});
                    }
                    return {text:body.innerText.slice(0,40000),nodes};
                }''')
                frames.append({'index': index, **data})
            return {'identity': self.identity, 'scan_window': self.config['scan_window'], 'frames': frames}
        return self.call(perform)


def serve(cdp, sandbox_id, config, port=18765, ready_file=None, lifetime=3300, stop_file=None):
    bridge = MailBridge(cdp, sandbox_id, config)
    token = secrets.token_urlsafe(32)
    origin = f'http://127.0.0.1:{port}'
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass
        def respond(self, status, value, cookie=None, html=False):
            raw = value.encode() if html else json.dumps(value, ensure_ascii=False).encode()
            self.send_response(status)
            self.send_header('Content-Type', 'text/html; charset=utf-8' if html else 'application/json; charset=utf-8')
            self.send_header('Content-Length', str(len(raw)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Content-Security-Policy', "default-src 'self'; img-src 'self' data:; script-src 'unsafe-inline'; style-src 'unsafe-inline'; frame-ancestors 'none'")
            if cookie:
                self.send_header('Set-Cookie', cookie)
            self.end_headers()
            self.wfile.write(raw)
        def authenticated(self):
            cookie = SimpleCookie()
            cookie.load(self.headers.get('Cookie', ''))
            return 'mail_session' in cookie and secrets.compare_digest(cookie['mail_session'].value, token)
        def do_GET(self):
            if self.headers.get('Host') != f'127.0.0.1:{port}':
                return self.respond(403, {'error': 'Invalid host'})
            if self.path == '/':
                return self.respond(200, Path(__file__).with_name('mail163.html').read_text(encoding='utf-8'), html=True)
            if not self.authenticated():
                return self.respond(401, {'error': '请从 App 打开会话入口'})
            if self.path == '/state':
                try:
                    return self.respond(200, {'browser': bridge.read(True)})
                except Exception:
                    return self.respond(503, {'error': '云端画面暂时不可用，请稍后刷新'})
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
                    return self.respond(200, {'ok': True}, f'mail_session={token}; HttpOnly; SameSite=Strict; Path=/')
                if not self.authenticated():
                    return self.respond(401, {'error': 'Authentication required'})
                epoch = body.get('epoch')
                if type(epoch) is not int:
                    raise ValueError('Control version required')
                if self.path == '/human':
                    value = bridge.human(epoch, body)
                elif self.path == '/login':
                    try:
                        value = bridge.login(epoch,body.get('address'),body.get('password'))
                    finally:
                        body.pop('password',None)
                elif self.path == '/continue':
                    value = bridge.confirm_login(epoch, body.get('address'))
                elif self.path == '/inspect-mail':
                    value = bridge.inspect_mail(epoch)
                elif self.path == '/mail-run':
                    value = bridge.start_mail(epoch)
                elif self.path == '/takeover':
                    value = bridge.takeover(epoch)
                elif self.path == '/stop':
                    bridge.control._check('local-owner', epoch)
                    value = {'stopping': True}
                    threading.Thread(target=httpd.shutdown, daemon=True).start()
                else:
                    return self.respond(404, {'error': 'Not found'})
                self.respond(200, value)
            except Rejected as exc:
                self.respond(409, {'error': str(exc)})
            except Exception:
                # Playwright errors may echo the value typed into a login field.
                self.respond(409, {'error': '操作未完成；请刷新画面后重试'})
    httpd = ThreadingHTTPServer(('127.0.0.1', port), Handler)
    if ready_file:
        Path(ready_file).write_text(json.dumps({'url': origin+'/#'+token, 'sandboxId': sandbox_id, 'workflow':'mail163'}), encoding='utf-8')
    timer = threading.Timer(lifetime, httpd.shutdown)
    timer.daemon=True
    timer.start()
    finished=threading.Event()
    if stop_file:
        def watch_stop():
            while not finished.wait(.5):
                if Path(stop_file).exists():
                    httpd.shutdown()
                    return
        threading.Thread(target=watch_stop, daemon=True).start()
    print(f'163 human login ready on {origin}; automatic cleanup after {lifetime//60} minutes.', flush=True)
    try:
        httpd.serve_forever(poll_interval=.5)
    finally:
        finished.set()
        timer.cancel()
        bridge.close()
        httpd.server_close()
        if ready_file:
            Path(ready_file).unlink(missing_ok=True)
