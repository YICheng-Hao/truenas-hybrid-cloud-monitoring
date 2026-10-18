#!/usr/bin/env python3
'''Minimal Prometheus endpoint for TrueNAS Cloud Sync successful post-script
callbacks.
Run on a monitoring VM reachable ONLY on a private/Tailscale address.
'''
import hmac
import json
import os
import re
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs
BIND = os.environ.get('CLOUDSYNC_BIND', '127.0.0.1')
PORT = int(os.environ.get('CLOUDSYNC_PORT', '9108'))
TOKEN = os.environ.get('CLOUDSYNC_TOKEN', '')
STATE = Path(os.environ.get('CLOUDSYNC_STATE', '/var/lib/cloudsync-monitor/last_success.json'))
lock = threading.Lock()
def read_state():
    try:
        obj = json.loads(STATE.read_text())
        return obj if isinstance(obj, dict) else {}
    except (FileNotFoundError, ValueError, OSError):
        return {}
def save_state(data):
    STATE.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix='.last_success-', dir=str(STATE.parent))
    try:
        with os.fdopen(fd, 'w') as f:
            json.dump(data, f, sort_keys=True)
            f.write('\n')
        os.replace(tmp, STATE)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path != '/metrics':
            self.send_error(404)
            return
        with lock:
            data = read_state()
        lines = [
            '# HELP truenas_cloudsync_last_success_timestamp_seconds Time callback received after successful Cloud Sync task (Unix seconds).',
            '# TYPE truenas_cloudsync_last_success_timestamp_seconds gauge',
        ]
        for task_id, ts in sorted(data.items(), key=lambda p: int(p[0])):
            lines.append(f'truenas_cloudsync_last_success_timestamp_seconds{{task_id="{task_id}"}} {float(ts):.3f}')
        body = ('\n'.join(lines) + '\n').encode()
        self.send_response(200)
        self.send_header('Content-Type', 'text/plain; version=0.0.4; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)
    def do_POST(self):
        if self.path != '/success':
            self.send_error(404)
            return
        if not TOKEN or not hmac.compare_digest(self.headers.get('Authorization', ''), 'Bearer ' + TOKEN):
            self.send_error(403)
            return
        try:
            n = int(self.headers.get('Content-Length', '0'))
        except ValueError:
            self.send_error(400)
            return
        if not 0 < n < 1024:
            self.send_error(400)
            return
        fields = parse_qs(self.rfile.read(n).decode('utf-8'), strict_parsing=True)
        task_id = fields.get('task_id', [''])[0]
        if not re.fullmatch(r'[1-9][0-9]{0,8}', task_id):
            self.send_error(400, 'Invalid task_id')
            return
        try:
            with lock:
                data = read_state()
                data[task_id] = time.time()
                save_state(data)
        except OSError:
            self.send_error(500)
            return
        self.send_response(204)
        self.end_headers()
    def log_message(self, format, *args):
        pass
if __name__ == '__main__':
    if len(TOKEN) < 24:
        raise SystemExit('CLOUDSYNC_TOKEN must be set to a strong random token (24+ chars)')
    print(f'Listening on {BIND}:{PORT}; persistent state: {STATE}', flush=True)
    ThreadingHTTPServer((BIND, PORT), Handler).serve_forever()
