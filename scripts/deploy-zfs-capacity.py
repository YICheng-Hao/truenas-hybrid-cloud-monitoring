"""Update only capacity collection; leave Grafana and member alerts running."""
import math
import re
import shutil
import subprocess
import time
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path
import yaml

CONFIG = Path('/etc/snmp_exporter/snmp.yml')
OID = '1.3.6.1.4.1.8072.1.3.2.3.1.2.12.122.102.115.95.99.97.112.97.99.105.116.121'
SITES = [('A', '100.114.236.88'), ('B', '100.113.107.95')]
ROW = r'(?s).*(?:^|\n)(?:mainpool|backuppool)[ \t]+([0-9]+)[ \t]+([0-9]+)[ \t]*(?:\n.*)?'

def fetch(url):
    with urllib.request.urlopen(url, timeout=25) as response:
        return response.read().decode()

def metric_value(text, name):
    match = re.search(r'^' + re.escape(name) + r'(?:\{[^\n]*\})?\s+([^\s]+)', text, re.M)
    if not match:
        raise ValueError('未產生 ' + name)
    value = float(match.group(1))
    if not math.isfinite(value) or value < 0:
        raise ValueError('容量值無效：' + name)
    return value

def main():
    original = CONFIG.read_bytes()
    backup = Path('/root/snmp-capacity-' + datetime.now().strftime('%Y%m%d-%H%M%S-%f') + '.bak')
    shutil.copy2(CONFIG, backup)
    backup.chmod(0o600)
    config = yaml.safe_load(original)
    module = config['modules']['truenas_zfs']
    if OID not in module.setdefault('get', []):
        module['get'].append(OID)
    metrics = module.setdefault('metrics', [])
    # Keep unrelated metrics, including working member/pool health metrics.
    metrics[:] = [m for m in metrics if m['name'] != 'zfsUsablePool']
    metrics.append({'name': 'zfsUsablePool', 'oid': OID, 'type': 'DisplayString',
        'help': 'Pool-root dataset USED and AVAILABLE from zfs list',
        'regex_extracts': {suffix: [{'regex': ROW, 'value': '$' + str(i)}]
            for i, suffix in enumerate(['UsedBytes', 'AvailableBytes'], 1)}})
    try:
        CONFIG.write_text(yaml.safe_dump(config, sort_keys=False, allow_unicode=True))
        subprocess.run(['/usr/local/bin/snmp_exporter', '--config.file=' + str(CONFIG), '--dry-run'], check=True)
        subprocess.run(['systemctl', 'restart', 'snmp_exporter'], check=True)
        time.sleep(1)
        for site, ip in SITES:
            url = 'http://127.0.0.1:9116/snmp?' + urllib.parse.urlencode({
                'target': ip, 'auth': 'public_v2', 'module': 'truenas_zfs'})
            try:
                text = fetch(url)
                used = metric_value(text, 'zfsUsablePoolUsedBytes')
                available = metric_value(text, 'zfsUsablePoolAvailableBytes')
            except Exception as error:
                print(f'{site} 站容量驗證失敗：{error}', flush=True)
                print('該站 zfs_capacity 原始回覆如下：', flush=True)
                subprocess.run(['snmpget', '-v2c', '-c', 'public', '-t', '3', '-r', '0', ip, OID], timeout=5)
                raise RuntimeError(f'{site} 站需確認 extend zfs_capacity /usr/sbin/zfs list -Hp -o name,used,available 已儲存並重啟 SNMP') from error
            print(f'{site} 站已驗證：USED={used:.0f} bytes，AVAILABLE={available:.0f} bytes，合計={(used+available)/2**40:.3f} TiB')
        print('兩站容量指標均已實際讀取成功。Grafana 與告警設定未改動。')
        print('請等下一次 Prometheus 採集後重新整理目前面板。備份：' + str(backup))
    except Exception:
        CONFIG.write_bytes(original)
        subprocess.run(['systemctl', 'restart', 'snmp_exporter'])
        print('容量更新失敗，已還原 SNMP Exporter 設定；未重啟 Grafana。備份：' + str(backup))
        raise

if __name__ == '__main__':
    main()
