#!/usr/bin/env python3
"""Generate a pasteable TrueNAS Shell update from the installed receiver settings."""
import argparse
import ipaddress
import json
import os
import re
import shlex
import subprocess
import tempfile
import urllib.parse
import urllib.request
from pathlib import Path


def known_callback(script):
    lines = [line for line in script.splitlines() if line.strip() and not line.lstrip().startswith('#')]
    guard = ': "${CLOUD_SYNC_ID:?This script must run inside a TrueNAS Cloud Sync task}"'
    if lines and lines[0].strip() == guard:
        lines.pop(0)
    try:
        parts = shlex.split('\n'.join(lines).replace('\\\n', ' '))
    except ValueError:
        return False
    return (parts[:9] == ['curl', '-fsS', '--connect-timeout', '5', '--max-time', '15', '-X', 'POST', '-H']
            and len(parts) in (15, 18) and parts[9].startswith('Authorization: Bearer ')
            and parts[10:12] == ['--data-urlencode', 'task_id=${CLOUD_SYNC_ID}']
            and parts[12].startswith('http://')
            and parts[13:] in (['||', 'true'], ['||', 'logger', '-t', 'cloudsync-monitor', 'Cloud Sync callback failed']))


def midclt(method, *args):
    result = subprocess.run(['midclt', 'call', method, *(json.dumps(a) for a in args)],
                            capture_output=True, text=True)
    if result.returncode:
        # Do not echo a response that might include credentials or callback tokens.
        raise RuntimeError('TrueNAS API 呼叫失敗：' + method + '；請確認在 TrueNAS A 的 root Shell 執行及 API 權限。')
    return json.loads(result.stdout)


def apply_on_nas(payload, backup_dir=Path('/root/cloudsync-postscript-backups')):
    task_id = payload['task_id']
    tasks = midclt('cloudsync.query', [['id', '=', task_id]])
    if len(tasks) != 1:
        raise RuntimeError('找不到唯一的 Cloud Sync Task ID；未修改。')
    task = tasks[0]
    if task.get('direction') != 'PUSH' or task.get('attributes', {}).get('bucket') != payload['bucket']:
        raise RuntimeError('任務不是預期的 S3 PUSH／bucket；未修改。請核對監測 VM 的 Task ID 與 bucket。')
    old = task.get('post_script') or ''
    desired = payload['post_script']
    print('任務：id=' + str(task_id) + '；來源=' + str(task.get('path')) + '；bucket=' + payload['bucket'])
    if old == desired:
        print('Post-script 已一致，不需重複修改。')
        return
    if old.strip() and not known_callback(old):
        raise RuntimeError('Post-script 包含無法辨識的自訂命令，未覆寫。請用 Web UI 保留其他命令，只替換回報區塊。')
    backup_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    backup_dir.chmod(0o700)
    fd, name = tempfile.mkstemp(prefix='task-' + str(task_id) + '-', suffix='.json', dir=backup_dir)
    with os.fdopen(fd, 'w') as stream:
        json.dump({'id': task_id, 'post_script': old}, stream, ensure_ascii=False, indent=2)
    midclt('cloudsync.update', task_id, {'post_script': desired})
    check = midclt('cloudsync.query', [['id', '=', task_id]])
    if len(check) != 1 or check[0].get('post_script') != desired:
        raise RuntimeError('更新後讀回不一致；請檢查 Web UI。原內容備份：' + name)
    print('Post-script 已更新並讀回核對。原內容備份：' + name)
    print('回報目的：' + payload['url'])
    print('尚未回報成功。現在到 TrueNAS A 對此任務按 Run Now，成功後再到監測 VM 執行 --check。')


def payload_from_installed(config, env_path):
    c = json.loads(config.read_text())
    env = dict(line.split('=', 1) for line in env_path.read_text().splitlines()
               if '=' in line and not line.startswith('#'))
    env = {key: json.loads(value) if value.startswith('"') else value for key, value in env.items()}
    ip = str(ipaddress.IPv4Address(env['CLOUDSYNC_BIND']))
    port = int(env['CLOUDSYNC_PORT'])
    if not 1 <= port <= 65535:
        raise ValueError('Receiver port 無效')
    token = env['CLOUDSYNC_TOKEN']
    if not re.fullmatch(r'[A-Za-z0-9_-]{24,}', token):
        raise ValueError('Receiver Token 無效；未產生新 Token。')
    task_id = int(c['task_id'])
    if task_id < 1:
        raise ValueError('Task ID 必須大於零')
    url = f'http://{ip}:{port}/success'
    post = '#!/bin/sh\n# 僅由 TrueNAS Cloud Sync 成功後執行。\n'
    post += ': "${CLOUD_SYNC_ID:?This script must run inside a TrueNAS Cloud Sync task}"\n'
    post += 'curl -fsS --connect-timeout 5 --max-time 15 -X POST \\\n'
    post += '  -H ' + shlex.quote('Authorization: Bearer ' + token) + ' \\\n'
    post += '  --data-urlencode "task_id=${CLOUD_SYNC_ID}" \\\n'
    post += '  ' + shlex.quote(url) + ' || logger -t cloudsync-monitor "Cloud Sync callback failed"\n'
    return {'task_id': task_id, 'bucket': c['bucket'], 'post_script': post, 'url': url}


def paste_command(payload):
    # Include only the NAS-side functions and their standard-library imports.
    source = Path(__file__).read_text()
    functions = source[source.index('def known_callback('):source.index('\ndef payload_from_installed(')]
    code = 'import json, os, shlex, subprocess, tempfile\nfrom pathlib import Path\n' + functions
    code += '\napply_on_nas(' + repr(payload) + ')\n'
    return "python3 - <<'TRUENAS_CLOUDSYNC_UPDATE'\n" + code + 'TRUENAS_CLOUDSYNC_UPDATE\n'


def check_callback(payload):
    url = payload['url'].removesuffix('/success') + '/metrics'
    with urllib.request.urlopen(url, timeout=10) as response:
        metrics = response.read().decode()
    pattern = r'^truenas_cloudsync_last_success_timestamp_seconds\{task_id="' + str(payload['task_id']) + r'"\} (\S+)$'
    match = re.search(pattern, metrics, re.M)
    if not match:
        raise RuntimeError('Receiver 可連線，但此 Task ID 尚無成功回報；請檢查 NAS Post-script／任務日誌／403 Token 錯誤。')
    query = 'truenas_cloudsync_last_success_timestamp_seconds{task_id="' + str(payload['task_id']) + '"}'
    with urllib.request.urlopen('http://127.0.0.1:9090/api/v1/query?' + urllib.parse.urlencode({'query': query}), timeout=10) as response:
        result = json.load(response)
    if result.get('status') != 'success' or not result['data']['result']:
        raise RuntimeError('Receiver 已有回報，但 Prometheus 尚未採集；等待約 1 分鐘後重試並檢查 cloudsync_success Target。')
    from datetime import datetime, timezone
    print('Receiver 已收到 Task ID ' + str(payload['task_id']) + ' 的回報；時間（UTC）：' + datetime.fromtimestamp(float(match[1]), timezone.utc).isoformat())
    print('Prometheus 已採集。回 Grafana Refresh；告警解除仍需等待評估及通知排程。')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, default=Path('/root/monitoring-setup.json'))
    parser.add_argument('--env', type=Path, default=Path('/etc/cloudsync-monitor.env'))
    parser.add_argument('--output', type=Path, default=Path('/root/truenas-cloudsync-apply-command.sh'))
    parser.add_argument('--check', action='store_true', help='唯讀檢查此 Task ID 的 Receiver 及 Prometheus 回報')
    args = parser.parse_args()
    payload = payload_from_installed(args.config, args.env)
    if args.check:
        check_callback(payload)
        return
    content = paste_command(payload)
    # Parse embedded Python before creating the handoff file.
    compile(content.split('\n', 1)[1].rsplit('\nTRUENAS_CLOUDSYNC_UPDATE', 1)[0], '<nas-handoff>', 'exec')
    fd = os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    os.fchmod(fd, 0o600)
    with os.fdopen(fd, 'w') as stream:
        stream.write(content)
    print('已產生 TrueNAS A 專用更新命令：' + str(args.output))
    print('Task ID：' + str(payload['task_id']) + '；回報目的：' + payload['url'])
    print('只產生檔案，尚未修改 NAS。執行 cat ' + str(args.output) + '，複製全部輸出到 TrueNAS A 的 root Shell。')
    print('命令含 Receiver Token，不要分享輸出或提交 GitHub。不需要重裝監控服務。')


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        raise SystemExit(str(error))
