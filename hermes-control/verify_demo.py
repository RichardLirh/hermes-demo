"""Real model/ACS integration check; human-side actions are automated test input."""
import argparse
import base64
import http.cookiejar
import json
import time
import urllib.error
import urllib.request
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
SESSION = Path.home() / '.config/xiaozhi-sandbox-demo/secrets/hermes-control-session.json'


def main(bridge_only=False):
    session = json.loads(SESSION.read_text())
    base, token = session['url'].split('/#')
    cookie = http.cookiejar.CookieJar()
    client = urllib.request.build_opener(urllib.request.ProxyHandler({}), urllib.request.HTTPCookieProcessor(cookie))
    epoch = None

    def request(path, body=None, expected=200):
        data = json.dumps({'epoch': epoch, **body}).encode() if body is not None else None
        req = urllib.request.Request(base + path, data=data, headers={'Origin': base, 'Content-Type': 'application/json'})
        try:
            response = client.open(req, timeout=30)
        except urllib.error.HTTPError as exc:
            response = exc
        assert response.status == expected, (path, response.status, response.read().decode())
        return json.load(response)

    request('/auth', {'token': token})
    state = request('/state')
    epoch = state['browser']['control']['epoch']
    session_id = state['browser']['control']['browserSessionId']
    def sync():
        nonlocal epoch
        value = request('/state')
        epoch = value['browser']['control']['epoch']
        assert value['browser']['control']['browserSessionId'] == session_id
        return value

    def wait_model():
        deadline = time.monotonic() + 240
        while time.monotonic() < deadline:
            value = sync()
            if not value['hermes']['busy']:
                assert not value['hermes']['error'], value['hermes']['error']
                assert not value['hermes']['result'].get('error'), value['hermes']['result']
                return value
            time.sleep(2)
        raise TimeoutError('Hermes turn did not complete')

    def action(action, selector, value=''):
        return request('/action', {'action': action, 'selector': selector, 'value': value})

    report = {'sandboxId': session['sandboxId'], 'humanTest': 'Automated human-side test, not a claim of user acceptance', 'checks': {}}
    if bridge_only:
        action('fill', 'search', '演示')
        action('click', 'find')
        report['checks']['browserConnected'] = True
    else:
        request('/run', {'prompt': '先观察。把搜索框 search 填入“演示”（此演示网页只识别这个关键词），点击 find。找到陈女士后在 draft 起草简短产品试用跟进内容，不登录，不提交。完成后停止。'})
        state = wait_model()
        assert 'demo-customer-001' in state['browser']['customer'], state['browser']['customer']
        assert len(state['browser']['fields']['draft']) > 10
        assert state['hermes']['events'], 'No Hermes tool calls'
        assert not state['browser']['receipt']
        report['checks']['realHermesQwenDraft'] = True
        request('/action', {'action': 'fill', 'selector': 'draft', 'value': 'WRONG OWNER'}, expected=409)
        report['checks']['wrongWriterRejected'] = True
        old_epoch = epoch
        request('/takeover', {})
        sync()
        request('/action', {'epoch': old_epoch, 'action': 'fill', 'selector': 'draft', 'value': 'STALE'}, expected=409)
        report['checks']['staleCommandRejected'] = True
    action('fill', 'username', 'demo')
    action('fill', 'password', 'demo-password')
    action('click', 'login')
    human_text = '人工补充：客户希望周五下午联系，请保留这一安排。'
    action('fill', 'draft', human_text)
    if not bridge_only:
        request('/run', {'prompt': '我已人工登录并修改草稿。先观察当前页面，保留人工草稿完整原文，在末尾追加一句“届时介绍试用进展。”，不提交，然后停止。'})
        state = wait_model()
        assert human_text in state['browser']['fields']['draft'], state['browser']['fields']['draft']
        assert '届时介绍试用进展' in state['browser']['fields']['draft']
        assert '已登录' in state['browser']['login']
        assert not state['browser']['receipt']
        report['checks']['sameSessionLoginAndHumanDraftPreserved'] = True
        request('/takeover', {})
        state = sync()
        draft = state['browser']['fields']['draft']
        op = str(uuid4())
        first = request('/submit', {'draft': draft, 'operationId': op})
        second = request('/submit', {'draft': draft, 'operationId': op})
        assert first['receipt'] == second['receipt'] and 'followup-1' in first['receipt']
        report['checks']['explicitHumanSubmitAndDuplicateReceipt'] = True
        report['receipt'] = first['receipt']
        report['hermes'] = state['hermes']
    state = sync()
    Path(ROOT / 'hermes-control-verified.png').write_bytes(base64.b64decode(state['browser']['image']))
    output = ROOT / ('hermes-bridge-verification.json' if bridge_only else 'hermes-model-handoff-verification.json')
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report['checks'], ensure_ascii=False), flush=True)


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--bridge-only', action='store_true')
    main(p.parse_args().bridge_only)
