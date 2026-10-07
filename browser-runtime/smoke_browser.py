"""Run inside the started container; exercises its actual headed browser."""
import json
import time
from pathlib import Path
from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    for attempt in range(60):
        try:
            browser = p.chromium.connect_over_cdp('http://127.0.0.1:9222')
            break
        except Exception:
            if attempt == 59:
                raise
            time.sleep(1)
    context = browser.contexts[0]
    page = context.new_page()
    page.goto('http://127.0.0.1:8765/')
    page.locator('#search').fill('演示')
    page.locator('#find').click()
    assert 'demo-customer-001' in page.locator('#customer').inner_text()
    page.locator('#username').fill('demo')
    page.locator('#password').fill('demo-password')
    page.locator('#login').click()
    page.locator('#login-status').filter(has_text='已登录').wait_for()
    page.locator('#draft').fill('镜像启动测试：仅虚构客户。')
    # This is an explicitly disposable fixture, never a real CRM submission.
    page.locator('#submit').click()
    page.locator('#message').filter(has_text='提交成功').wait_for()
    receipt = page.locator('#message').inner_text()
    page.locator('#submit').click()
    page.wait_for_timeout(300)
    assert page.locator('#message').inner_text() == receipt
    Path('/home/pwuser/artifacts').mkdir(exist_ok=True)
    page.screenshot(path='/home/pwuser/artifacts/browser-smoke.png')
    print(json.dumps({'browser': 'headed Chromium', 'login': True,
                      'fictionalSubmission': True, 'receipt': receipt}, ensure_ascii=False))
    page.close()
    browser.close()
