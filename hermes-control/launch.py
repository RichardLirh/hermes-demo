"""Create one demo browser, tunnel CDP locally, always scale back to zero."""
import json
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
KUBE = str(Path.home() / 'AppData/Local/KubernetesCLI/kubectl.exe')
CONFIG = str(Path.home() / '.kube/xiaozhi-sandbox-demo.yaml')
CMD = [KUBE, '--kubeconfig', CONFIG, '-n', 'xiaozhi-demo']
READY = Path.home() / '.config/xiaozhi-sandbox-demo/secrets/hermes-control-session.json'
STOP = Path(os.environ['HERMES_STOP_FILE']) if os.environ.get('HERMES_STOP_FILE') else None


def kubectl(*args):
    return subprocess.check_output(CMD + list(args), text=True, encoding='utf-8', stderr=subprocess.PIPE, timeout=45)


def related_resources(items, known=None):
    known = set(known or ())
    related = []
    pending = list(items)
    while pending:
        found = []
        for item in pending:
            metadata = item['metadata']
            owners = metadata.get('ownerReferences', [])
            if (metadata.get('uid') in known or metadata['name'].startswith('demo-hermes-browser-') or
                any(o.get('uid') in known or o.get('name', '').startswith('demo-hermes-browser') for o in owners)):
                found.append(item)
                known.add(metadata.get('uid'))
        if not found:
            break
        related.extend(found)
        pending = [item for item in pending if item not in found]
    return related, known


def cleanup(tunnel, created):
    try:
        try:
            if tunnel and tunnel.poll() is None:
                tunnel.terminate()
                try:
                    tunnel.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    tunnel.kill()
                    tunnel.wait(timeout=5)
        finally:
            if created:
                known = set()
                try:
                    before = json.loads(kubectl('get', 'pods,sandboxes,pvc', '-o', 'json'))['items']
                    _, known = related_resources(before)
                finally:
                    # A failed inventory or tunnel shutdown must not skip scaling down.
                    kubectl('scale', 'sandboxset/demo-hermes-browser', '--replicas=0')
                for _ in range(60):
                    items = json.loads(kubectl('get', 'pods,sandboxes,pvc', '-o', 'json'))['items']
                    remaining, known = related_resources(items, known)
                    template = json.loads(kubectl('get', 'sandboxset', 'demo-hermes-browser', '-o', 'json'))
                    if not remaining and template['spec'].get('replicas') == 0:
                        print('Cleanup verified: related Pods, Sandboxes and PVCs absent; template replicas=0.', flush=True)
                        break
                    time.sleep(2)
                else:
                    raise RuntimeError('Cleanup requested but cloud resource removal is not yet verified')
    finally:
        READY.unlink(missing_ok=True)


def main():
    aliyun = str(Path.home() / 'AppData/Local/AliyunCLI/aliyun.exe')
    raw = subprocess.check_output([aliyun, 'cs', 'GET',
        '/k8s/c3c70a016529748d6b1d12b13f259d9ff/user_config',
        '--PrivateIpAddress', 'false', '--TemporaryDurationMinutes', '60',
        '--region', 'cn-shenzhen', '--profile', 'xiaozhi-demo'], stderr=subprocess.PIPE)
    credentials = json.loads(raw)
    if not credentials.get('config'):
        raise RuntimeError('Aliyun did not return a temporary kubeconfig')
    Path(CONFIG).write_text(credentials['config'], encoding='utf-8')
    template = json.loads(kubectl('get', 'sandboxset', 'demo-hermes-browser', '-o', 'json'))
    if template['spec'].get('replicas', 0) != 0:
        raise RuntimeError('Template already has a running session; refusing to replace it')
    tunnel = None
    created = False
    try:
        kubectl('scale', 'sandboxset/demo-hermes-browser', '--replicas=1')
        created = True
        deadline = time.monotonic() + 360
        pod = None
        while time.monotonic() < deadline:
            if STOP and STOP.exists():
                print('Cancellation received before browser readiness.', flush=True)
                return
            pods = json.loads(kubectl('get', 'pods', '-o', 'json'))['items']
            candidates = [p for p in pods if any(o.get('name') == 'demo-hermes-browser' for o in p['metadata'].get('ownerReferences', []))
                          or p['metadata']['name'].startswith('demo-hermes-browser-')]
            for p in candidates:
                if p.get('status', {}).get('reason') == 'InsufficientBalance':
                    raise RuntimeError('Aliyun balance is insufficient; replenish before retrying')
                if any(c.get('type') == 'Ready' and c.get('status') == 'True' for c in p.get('status', {}).get('conditions', [])):
                    pod = p['metadata']['name']
                    break
            if pod:
                break
            events = json.loads(kubectl('get', 'events', '-o', 'json'))['items']
            candidate_names = {p['metadata']['name'] for p in candidates}
            if any(e.get('reason') == 'InsufficientBalance' and
                   e.get('involvedObject', {}).get('name') in candidate_names for e in events):
                raise RuntimeError('ACS InsufficientBalance: check Aliyun available balance')
            time.sleep(3)
        if not pod:
            raise TimeoutError('Browser pod did not become ready in six minutes')
        print(f'Browser sandbox ready: {pod}', flush=True)
        with (ROOT / 'hermes-control-tunnel.log').open('w') as log:
            tunnel = subprocess.Popen(CMD + ['port-forward', '--address=127.0.0.1', 'pod/' + pod, '19222:9222'], stdout=log, stderr=log)
            for _ in range(30):
                try:
                    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
                    opener.open('http://127.0.0.1:19222/json/version', timeout=2).close()
                    break
                except OSError:
                    if tunnel.poll() is not None:
                        raise RuntimeError('CDP tunnel exited')
                    time.sleep(1)
            else:
                raise TimeoutError('CDP tunnel not ready')
            from server import serve
            serve('http://127.0.0.1:19222', pod, ready_file=READY, stop_file=STOP)
    finally:
        cleanup(tunnel, created)


if __name__ == '__main__':
    main()
