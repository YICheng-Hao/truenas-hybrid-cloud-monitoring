import json, re, shutil, subprocess, time, urllib.request
from pathlib import Path
from datetime import datetime
import yaml

snmp = Path('/etc/snmp_exporter/snmp.yml')
prom = Path('/etc/prometheus/prometheus.yml')
alert = Path('/etc/grafana/provisioning/alerting/zfs-member-alerts.yaml')
backup = Path('/root/zfs-member-backup-' + datetime.now().strftime('%Y%m%d-%H%M%S-%f'))
backup.mkdir(mode=0o700)
paths = [snmp, prom, alert]
for i, path in enumerate(paths):
    if path.exists():
        shutil.copy2(path, backup / str(i))

def run(*args):
    subprocess.run(args, check=True)

def read_url(url):
    with urllib.request.urlopen(url, timeout=20) as response:
        return response.read().decode()

def build():
    config = yaml.safe_load(snmp.read_text())
    module = config['modules']['truenas_zfs']
    output_oid = '1.3.6.1.4.1.8072.1.3.2.3.1.2.3.122.102.115'
    result_oid = '1.3.6.1.4.1.8072.1.3.2.3.1.4.3.122.102.115'
    for oid in [output_oid, result_oid]:
        if oid not in module.setdefault('get', []):
            module['get'].append(oid)
    metrics = module.setdefault('metrics', [])
    metrics[:] = [m for m in metrics if m['name'] not in ('zfsMemberFault', 'zfsStatusCommandExit')]
    metrics.extend([
        {'name': 'zfsMemberFault', 'oid': output_oid, 'type': 'DisplayString',
         'help': 'ZFS status table: 0 healthy, 1 non-online member or vdev, 2 unrecognized output',
         'regex_extracts': {'': [
             {'regex': r'(?s).*\s(?:DEGRADED|FAULTED|UNAVAIL|OFFLINE|REMOVED|SUSPENDED)\s+\d+\s+\d+\s+\d+.*', 'value': '1'},
             {'regex': r'(?s).*config:.*\sONLINE\s+\d+\s+\d+\s+\d+.*errors:.*', 'value': '0'},
             {'regex': r'(?s).*', 'value': '2'}]}},
        {'name': 'zfsStatusCommandExit', 'oid': result_oid, 'type': 'gauge',
         'help': 'Exit status of the SNMP extend zpool command; zero means success'}
    ])
    pc = yaml.safe_load(prom.read_text())
    jobs = [j for j in pc['scrape_configs'] if j['job_name'] == 'truenas_snmp']
    if len(jobs) != 1:
        raise RuntimeError('Expected exactly one truenas_snmp job')
    modules = jobs[0].setdefault('params', {}).setdefault('module', [])
    if 'truenas_zfs' not in modules:
        modules.append('truenas_zfs')
    query = '(max by(instance) (zfsMemberFault{job="truenas_snmp"} and on(instance) (zfsStatusCommandExit{job="truenas_snmp"} == 0) and on(instance) (up{job="truenas_snmp"} == 1)))'
    for ip in ['100.114.236.88', '100.113.107.95']:
        query += ' or on(instance) label_replace(vector(2), "instance", "' + ip + '", "", ".*")'
    rules = []
    specs = [
        ('zfs_member_fault_v1', 'ZFS 磁碟成員或 VDEV 異常', 1, '0s', 'critical'),
        ('zfs_member_missing_v1', 'ZFS 磁碟成員狀態無法取得', 2, '2m', 'warning')]
    for uid, title, value, pending, severity in specs:
        rules.append({'uid': uid, 'title': title, 'condition': 'C', 'for': pending,
            'noDataState': 'NoData', 'execErrState': 'Error', 'isPaused': False,
            'labels': {'severity': severity, 'category': 'zfs_members'},
            'annotations': {'summary': title, 'description': '請在來源 TrueNAS 執行 zpool status -P。成員異常不代表整個儲存池已無法存取；狀態無法取得也不等於磁碟故障。'},
            'data': [
                {'refId': 'A', 'relativeTimeRange': {'from': 300, 'to': 0}, 'datasourceUid': 'cg15oru9k9clcd', 'model': {'expr': query, 'instant': True, 'range': False, 'refId': 'A'}},
                {'refId': 'B', 'datasourceUid': '__expr__', 'model': {'type': 'reduce', 'expression': 'A', 'reducer': 'last', 'refId': 'B'}},
                {'refId': 'C', 'datasourceUid': '__expr__', 'model': {'type': 'threshold', 'expression': 'B', 'refId': 'C', 'conditions': [{'evaluator': {'type': 'eq', 'params': [value]}}]}}]})
    ac = {'apiVersion': 1, 'groups': [{'orgId': 1, 'name': 'zfs_members_1m', 'folder': 'TrueNAS_Alerts', 'interval': '1m', 'rules': rules}]}
    return config, pc, ac

try:
    sc, pc, ac = build()
    snmp.write_text(yaml.safe_dump(sc, sort_keys=False, allow_unicode=True))
    run('/usr/local/bin/snmp_exporter', '--config.file=' + str(snmp), '--dry-run')
    run('systemctl', 'restart', 'snmp_exporter')
    time.sleep(1)
    live = read_url('http://127.0.0.1:9116/snmp?target=100.114.236.88&auth=public_v2&module=truenas_zfs')
    if not re.search(r'^zfsMemberFault(?:\{[^\n]*\})? [012](?:\.0)?$', live, re.M):
        raise RuntimeError('A site did not return zfsMemberFault; changes will be rolled back')
    if not re.search(r'^zfsStatusCommandExit(?:\{[^\n]*\})? 0(?:\.0)?$', live, re.M):
        raise RuntimeError('A site zpool command failed; changes will be rolled back')
    print('\n'.join(line for line in live.splitlines() if line.startswith(('zfsMemberFault', 'zfsStatusCommandExit'))))
    prom.write_text(yaml.safe_dump(pc, sort_keys=False, allow_unicode=True))
    run('/usr/local/bin/promtool', 'check', 'config', str(prom))
    alert.write_text(json.dumps(ac, ensure_ascii=False, indent=2) + '\n')
    alert.chmod(0o644)
    run('systemctl', 'restart', 'prometheus', 'grafana-server')
    for attempt in range(30):
        try:
            health = json.loads(read_url('http://127.0.0.1:3000/api/health'))
            if health.get('database') == 'ok':
                break
        except Exception:
            pass
        time.sleep(1)
    else:
        raise RuntimeError('Grafana failed its health check')
    print('套用完成：新增兩條成員監測規則。備份：' + str(backup))
except Exception:
    for i, path in enumerate(paths):
        saved = backup / str(i)
        if saved.exists():
            shutil.copy2(saved, path)
        elif path == alert:
            path.unlink(missing_ok=True)
    subprocess.run(['systemctl', 'restart', 'snmp_exporter', 'prometheus', 'grafana-server'])
    print('套用失敗，已還原原有三份設定。備份：' + str(backup))
    raise
