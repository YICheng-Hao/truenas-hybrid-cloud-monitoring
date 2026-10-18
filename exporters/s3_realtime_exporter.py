#!/usr/bin/env python3
'''S3 object inventory exporter (not a backup-success monitor).
Requires AWS CLI credentials with s3:ListBucket for the configured bucket.
Config via environment: S3_BUCKET, AWS_SHARED_CREDENTIALS_FILE,
S3_STORAGE_PRICE_USD_PER_GB_MONTH, S3_REFRESH_SECONDS, S3_AWS_TIMEOUT_SECONDS.
'''
import math
import os
import subprocess
import threading
import time
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
BUCKET = os.getenv('S3_BUCKET', 'truenas-backup-myhome-2026')
CREDENTIALS = os.getenv('AWS_SHARED_CREDENTIALS_FILE', '/etc/cloudwatch_exporter/credentials')
PRICE = float(os.getenv('S3_STORAGE_PRICE_USD_PER_GB_MONTH', '0.025'))
REFRESH = max(60, int(os.getenv('S3_REFRESH_SECONDS', '300')))
TIMEOUT = max(10, int(os.getenv('S3_AWS_TIMEOUT_SECONDS', '120')))
lock = threading.Lock()
cache = {'expires': 0, 'text': ''}
def line(name, value, description, type_='gauge'):
    return f'# HELP {name} {description}\n# TYPE {name} {type_}\n{name}{{bucket_name="{BUCKET}"}} {value}\n'
def scrape_inventory():
    env = os.environ.copy()
    env['AWS_SHARED_CREDENTIALS_FILE'] = CREDENTIALS
    env['PATH'] = '/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/root/bin'
    start = time.monotonic()
    status = 0
    total = math.nan
    objects = math.nan
    latest = math.nan
    try:
        cmd = ['aws', 's3', 'ls', f's3://{BUCKET}', '--recursive', '--summarize']
        p = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=TIMEOUT, check=False)
        if p.returncode != 0:
            raise RuntimeError(p.stderr.strip() or 'AWS CLI returned nonzero exit status')
        status = 1
        total, objects = 0, 0
        latest = 0
        for row in p.stdout.splitlines():
            s = row.strip()
            if s.startswith('Total Objects:'):
                objects = int(s.partition(':')[2].strip())
            elif s.startswith('Total Size:'):
                total = int(s.partition(':')[2].strip())
            elif len(s) >= 19 and s[4] == '-' and s[7] == '-' and s[10] == ' ':
                try:
                    ts = datetime.strptime(s[:19], '%Y-%m-%d %H:%M:%S').astimezone().timestamp()
                    latest = max(latest, ts)
                except ValueError:
                    pass
    except (OSError, RuntimeError, subprocess.TimeoutExpired, ValueError) as error:
        print(f'S3 inventory failed: {error}', flush=True)
    elapsed = time.monotonic() - start
    estimate = total / 1_000_000_000 * PRICE if status else math.nan
    last_age = max(0, time.time() - latest) if status and latest > 0 else math.nan
    return ''.join([
        line('aws_s3_bucket_health_status', status, 'Inventory list API succeeded on last refresh (not backup health)'),
        line('aws_s3_bucket_size_bytes_average', total, 'Listed current object sizes in bytes; not CloudWatch daily BucketSizeBytes'),
        line('aws_s3_number_of_objects_average', objects, 'Number of listed current objects'),
        line('aws_s3_estimated_monthly_cost_usd', estimate, 'Single price storage only estimate for current object footprint'),
        line('aws_s3_last_backup_age_seconds', last_age, 'Legacy metric name: elapsed seconds since newest object upload, NOT successful backup'),
        line('aws_s3_last_object_upload_timestamp_seconds', latest if latest > 0 and status else math.nan, 'Newest listed object upload timestamp'),
        line('aws_s3_api_latency_seconds', elapsed, 'Duration of inventory scan in seconds'),
        line('aws_s3_inventory_last_refresh_timestamp_seconds', time.time(), 'Last inventory scan timestamp'),
    ])
class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path != '/metrics':
            self.send_error(404)
            return
        with lock:
            if time.monotonic() >= cache['expires']:
                cache['text'] = scrape_inventory()
                cache['expires'] = time.monotonic() + REFRESH
        content = cache['text'].encode()
        self.send_response(200)
        self.send_header('Content-Type', 'text/plain; version=0.0.4; charset=utf-8')
        self.send_header('Content-Length', str(len(content)))
        self.end_headers()
        self.wfile.write(content)
if __name__ == '__main__':
    ThreadingHTTPServer(('127.0.0.1', 9107), Handler).serve_forever()
