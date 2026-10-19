import json
import os
import shutil
from pathlib import Path
from datetime import datetime

directory = Path(os.environ.get('ZFS_ALERT_DIR', '/etc/grafana/provisioning/alerting'))
directory.mkdir(parents=True, exist_ok=True)
target = directory / 'zfs-health-alerts.yaml'
pools = [('100.114.236.88', 'mainpool'), ('100.113.107.95', 'backuppool'),
         ('100.114.236.88', 'boot-pool'), ('100.113.107.95', 'boot-pool')]

def pool_state(ip, pool):
    selector = f'job="truenas_snmp",instance="{ip}",zpoolName="{pool}"'
    parts = [
        f'(zpoolHealthStr{{{selector},zpoolHealthStr="ONLINE"}} == 1)',
        f'(zpoolHealthStr{{{selector},zpoolHealthStr="DEGRADED"}} == 1) * 2',
        f'(zpoolHealthStr{{{selector},zpoolHealthStr!~"ONLINE|DEGRADED"}} == 1) * 3'
    ]
    actual = 'max by (job, instance, zpoolName) (' + ' or '.join(parts) + ')'
    actual = f'({actual} and on (instance) (up{{job="truenas_snmp"}} == 1))'
    missing = 'vector(4)'
    for key, value in [('job', 'truenas_snmp'), ('instance', ip), ('zpoolName', pool)]:
        missing = f'label_replace({missing}, "{key}", "{value}", "", ".*")'
    return f'{actual} or on (job, instance, zpoolName) ({missing})'

query = ' or '.join('(' + pool_state(ip, pool) + ')' for ip, pool in pools)
specs = [
    ('alert_zfs_degraded', 'ZFS 儲存池降級（DEGRADED）', 2, '1m', 'warning'),
    ('alert_zfs_abnormal', 'ZFS 儲存池異常（非 ONLINE／DEGRADED）', 3, '1m', 'critical'),
    ('alert_zfs_health_missing', 'ZFS 健康指標無法取得', 4, '2m', 'warning')
]
for other in directory.iterdir():
    if other != target and other.suffix.lower() in ('.yaml', '.yml'):
        text = other.read_text()
        if any(uid in text for uid, *_ in specs):
            raise SystemExit(f'已有相同 ZFS 規則，未修改任何檔案：{other}')

rules = []
for uid, title, value, pending, severity in specs:
    rules.append({
        'uid': uid, 'title': title, 'condition': 'C', 'for': pending,
        'noDataState': 'NoData', 'execErrState': 'Error', 'isPaused': False,
        'labels': {'severity': severity, 'category': 'zfs_health'},
        'annotations': {'summary': title, 'description': '請依來源位址與儲存池名稱查看 TrueNAS。無資料代表監控無法判讀，不等於磁碟故障。'},
        'data': [
            {'refId': 'A', 'relativeTimeRange': {'from': 300, 'to': 0},
             'datasourceUid': 'cg15oru9k9clcd',
             'model': {'expr': query, 'instant': True, 'range': False, 'refId': 'A'}},
            {'refId': 'B', 'datasourceUid': '__expr__',
             'model': {'type': 'reduce', 'expression': 'A', 'reducer': 'last', 'refId': 'B'}},
            {'refId': 'C', 'datasourceUid': '__expr__',
             'model': {'type': 'threshold', 'expression': 'B', 'refId': 'C',
                       'conditions': [{'evaluator': {'type': 'eq', 'params': [value]}}]}}
        ]
    })
config = {'apiVersion': 1, 'groups': [
    {'orgId': 1, 'name': 'zfs_health_1m', 'folder': 'TrueNAS_Alerts',
     'interval': '1m', 'rules': rules}
]}
if target.exists():
    backup = Path('/root') / ('zfs-health-alerts-' + datetime.now().strftime('%Y%m%d-%H%M%S') + '.bak')
    shutil.copy2(target, backup)
target.write_text(json.dumps(config, ensure_ascii=False, indent=2) + '\n')
target.chmod(0o644)
print('已新增三條 ZFS 告警：' + str(target))
