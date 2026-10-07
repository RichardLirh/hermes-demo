"""Trusted-demo desktop. All control ports bind to loopback by default."""
import os
import signal
import subprocess
import time
import urllib.request
from pathlib import Path
from playwright.sync_api import sync_playwright

processes = []
stopping = False

def stop(*_):
    global stopping
    stopping = True

def spawn(args):
    child = subprocess.Popen(args)
    processes.append(child)
    return child

def main():
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    try:
        spawn(['Xvfb', ':99', '-screen', '0', '1280x800x24', '-nolisten', 'tcp'])
        for _ in range(100):
            if Path('/tmp/.X11-unix/X99').exists():
                break
            if stopping:
                return
            time.sleep(.1)
        else:
            raise RuntimeError('Xvfb did not start')
        spawn(['python', 'demo_server.py'])
        # A fresh password is mandatory before enabling interactive VNC.
        password = os.environ.pop('VNC_PASSWORD', '')
        if password:
            if len(password) < 8:
                raise ValueError('VNC_PASSWORD must have at least 8 characters')
            import tempfile
            with tempfile.TemporaryDirectory() as temp:
                auth = str(Path(temp) / 'passwd')
                subprocess.run(['x11vnc', '-storepasswd', password, auth], check=True,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                os.chmod(auth, 0o600)
                spawn(['x11vnc', '-display', ':99', '-localhost', '-rfbport', '5900',
                       '-rfbauth', auth, '-forever', '-shared'])
                # x11vnc loads the password before the temporary file is removed.
                time.sleep(1)
                if processes[-1].poll() is not None:
                    raise RuntimeError('VNC failed to start')
                serve_browser()
        else:
            serve_browser()
    finally:
        for child in reversed(processes):
            if child.poll() is None:
                child.terminate()
        for child in reversed(processes):
            try:
                child.wait(timeout=5)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait()

def serve_browser():
    if len(processes) > 2:
        spawn(['websockify', '--web=/usr/share/novnc', '127.0.0.1:6080', '127.0.0.1:5900'])
    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            '/home/pwuser/browser-profile', headless=False,
            viewport={'width': 1280, 'height': 800},
            args=['--remote-debugging-address=127.0.0.1', '--remote-debugging-port=9222',
                  '--disable-dev-shm-usage'])
        page = context.pages[0] if context.pages else context.new_page()
        for attempt in range(50):
            try:
                urllib.request.urlopen('http://127.0.0.1:8765/', timeout=1).close()
                break
            except OSError:
                time.sleep(.1)
        page.goto('http://127.0.0.1:8765/')
        print('Browser ready: loopback CDP 9222; demo CRM 8765', flush=True)
        while not stopping:
            if any(child.poll() is not None for child in processes):
                raise RuntimeError('A runtime service exited')
            page.wait_for_timeout(250)
        context.close()

if __name__ == '__main__':
    main()
