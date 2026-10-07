"""One Playwright thread and one fenced writer for the existing ACS browser."""
import base64
import concurrent.futures
import json
import queue
import sys
import threading
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'browser-runtime'))
from control import SessionControl, Rejected


class BrowserBridge:
    def __init__(self, cdp, sandbox_id):
        self.control = SessionControl('local-owner', str(uuid4()), sandbox_id, str(uuid4()))
        self.control.transfer('local-owner', 1, 'USER')
        self.jobs = queue.Queue()
        self.ready = concurrent.futures.Future()
        self.thread = threading.Thread(target=self._worker, args=(cdp,), daemon=True)
        self.thread.start()
        self.ready.result(timeout=40)

    def _worker(self, cdp):
        from playwright.sync_api import sync_playwright
        try:
            with sync_playwright() as pw:
                browser = pw.chromium.connect_over_cdp(cdp, timeout=30000)
                self.page = next(p for p in browser.contexts[0].pages if p.url == 'http://127.0.0.1:8765/')
                self.page.set_default_timeout(5000)
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
                browser.close()  # disconnect CDP, runtime owns the persistent context
        except Exception as exc:
            if not self.ready.done():
                self.ready.set_exception(exc)

    def call(self, fn):
        f = concurrent.futures.Future()
        self.jobs.put((fn, f))
        try:
            return f.result(timeout=20)
        except concurrent.futures.TimeoutError:
            f.cancel()  # queued work must never execute after a caller timed out
            raise

    def _read(self, screenshot=False):
        p = self.page
        if p.url != 'http://127.0.0.1:8765/':
            raise Rejected('Browser left the demo origin')
        result = {'url': p.url, 'title': p.title(),
                  'fields': {k: p.locator('#' + k).input_value() for k in ('search', 'username', 'draft')},
                  'customer': p.locator('#customer').inner_text(),
                  'login': p.locator('#login-status').inner_text(),
                  'receipt': p.locator('#message').inner_text(),
                  'control': self.control.snapshot()}
        if screenshot:
            # Mask password input; the real password never enters model observations.
            result['image'] = base64.b64encode(p.screenshot(mask=[p.locator('#password')])).decode()
        return result

    def read(self, screenshot=False):
        return self.call(lambda: self._read(screenshot))

    def transfer(self, epoch, mode):
        return self.call(lambda: self.control.transfer('local-owner', epoch, mode))

    def action(self, actor, epoch, action, selector='', value=''):
        def perform():
            self._read()
            if action == 'read':
                return self._read()
            if action == 'fill' and selector in ('search', 'username', 'password', 'draft'):
                if actor == 'AGENT' and selector in ('username', 'password'):
                    raise Rejected('Login belongs to human takeover')
                self.page.locator('#' + selector).fill(value[:4000])
            elif action == 'click' and selector in ('find', 'login'):
                if actor == 'AGENT' and selector == 'login':
                    raise Rejected('Login belongs to human takeover')
                self.page.locator('#' + selector).click()
                if selector == 'login':
                    self.page.wait_for_function("document.querySelector('#login-status').textContent !== '未登录'")
            else:
                raise Rejected('Action not allowed; submission requires explicit human confirmation')
            return self._read()
        return self.call(lambda: self.control.operate('local-owner', epoch, actor, perform))

    def approve_submit(self, epoch, expected_draft, operation_id):
        # Only invoked by authenticated human HTTP endpoint, never a model tool.
        def perform():
            self.control._check('local-owner', epoch, 'USER')
            actual = self._read()
            if actual['fields']['draft'] != expected_draft:
                raise Rejected('Draft changed: refresh and review it again')
            draft = {'text': expected_draft, 'customer': actual['customer']}
            token = self.control.approve('local-owner', epoch, draft)
            def submit():
                self.page.locator('#submit').click()
                self.page.wait_for_function("document.querySelector('#message').textContent.startsWith('提交成功')")
                return self._read()
            return self.control.submit('local-owner', epoch, 'USER', token, draft, operation_id, submit)
        return self.call(perform)

    def close(self):
        state = self.control.snapshot()
        self.call(lambda: self.control.close('local-owner', state['epoch']))
        self.jobs.put(None)
        self.thread.join(timeout=10)
