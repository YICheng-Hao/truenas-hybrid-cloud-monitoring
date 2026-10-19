"""Run with sudo on each TrueNAS 25.10 host, not on the monitoring VM."""
import json
import re
import subprocess
from datetime import datetime
from pathlib import Path

LINES = ['extend zfs /usr/sbin/zpool status -P',
         'extend zfs_capacity /usr/sbin/zfs list -Hp -o name,used,available']

def call(method, *args):
    return json.loads(subprocess.check_output(
        ['midclt', 'call', method] + [json.dumps(arg) for arg in args], text=True))

def normalize(old):
    keep = [line for line in old.splitlines()
            if not re.match(r'^\s*extend\s+(zfs|zfs_capacity)\s', line)]
    return '\n'.join(keep + LINES).strip() + '\n'

def main():
    rows = subprocess.check_output(['/usr/sbin/zfs', 'list', '-Hp', '-o', 'name,used,available'], text=True)
    roots = [line for line in rows.splitlines() if line.split()[0] in ('mainpool', 'backuppool')]
    if not roots:
        raise SystemExit('沒有找到 mainpool／backuppool，請確認是在 TrueNAS A 或 B 執行。')
    old = call('snmp.config').get('options') or ''
    backup = Path('/root/snmp-options-' + datetime.now().strftime('%Y%m%d-%H%M%S-%f') + '.json')
    backup.write_text(json.dumps({'options': old}, ensure_ascii=False))
    backup.chmod(0o600)
    new = normalize(old)
    try:
        call('snmp.update', {'options': new})
        if not call('service.restart', 'snmp', {'silent': False}):
            raise RuntimeError('SNMP 重啟後未啟動')
        actual = call('snmp.config').get('options') or ''
        assert all(line in actual.splitlines() for line in LINES), 'TrueNAS 未保存新設定'
    except Exception:
        call('snmp.update', {'options': old})
        call('service.restart', 'snmp', {'silent': False})
        print('設定失敗，已還原原有附屬參數。備份：' + str(backup))
        raise
    print('已保存以下設定並重啟 SNMP：\n' + '\n'.join(LINES))
    print('本機資料容量（名稱、USED、AVAILABLE）：\n' + '\n'.join(roots))
    print('原設定備份：' + str(backup))

if __name__ == '__main__':
    main()
