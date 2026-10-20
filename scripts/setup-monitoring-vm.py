#!/usr/bin/env python3
"""Fresh Rocky Linux 9/10 VM setup. Uses the confirmed hrStorage dashboard."""
import argparse
import base64
import copy
import getpass
import hashlib
import ipaddress
import json
import math
import os
import re
import shutil
import socket
import subprocess
import tarfile
import tempfile
import time
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path
import yaml

PROJECT = Path(__file__).resolve().parents[1]
STATE = Path('/var/lib/truenas-monitoring-install')
UID = 'cg15oru9k9clcd'
SERVICES = ['snmp_exporter', 's3_realtime_exporter', 'cloudsync-monitor', 'prometheus', 'grafana-server']

def rocky_major(osinfo, architecture):
    values = dict(line.split('=', 1) for line in osinfo.splitlines() if '=' in line)
    major = values.get('VERSION_ID', '').strip('"\'').split('.')[0]
    if values.get('ID', '').strip('"\'') != 'rocky' or major not in ('9', '10') or architecture != 'x86_64':
        raise ValueError('此安裝腳本限定 Rocky Linux 9／10 x86_64')
    return major

def run(*args, capture=False):
    if capture:
        return subprocess.check_output(args, text=True).strip()
    subprocess.run(args, check=True)

def read_url(url, timeout=30):
    with urllib.request.urlopen(url, timeout=timeout) as response:
        return response.read().decode()

def ask(label, default='', secret=False):
    prompt = label + (f' [{default}]' if default and not secret else '') + ': '
    return (getpass.getpass(prompt) if secret else input(prompt)).strip() or default

def validate(c):
    for key in ['aws_access_key_id', 'aws_secret_access_key', 'smtp_user', 'smtp_password',
                'alert_email_to', 'discord_webhook', 'grafana_admin_password']:
        if not c.get(key) or any(s in c[key] for s in ['REPLACE_', 'YOUR_', '\n', '\r']):
            raise ValueError('必須填入有效的 ' + key)
    for key in ['a_ip', 'b_ip']:
        ipaddress.IPv4Address(c[key])
    if c['a_ip'] == c['b_ip']:
        raise ValueError('A、B IP 不可相同')
    if '/' not in c['admin_cidr']:
        raise ValueError('管理來源請填 CIDR：整個網段用 192.168.23.0/24；單台管理電腦用其 IP/32，不是監測 VM IP')
    ipaddress.IPv4Network(c['admin_cidr'], strict=True)
    if not c.get('snmp_community') or any(x in c['snmp_community'] for x in ['\n', '\r']):
        raise ValueError('SNMP Community 不可空白或換行')
    if not re.fullmatch(r'[a-z]{2}(?:-[a-z]+)+-\d+', c['region']):
        raise ValueError('Region 請填區域代碼，例如 ap-east-2，不是區域中文名稱')
    if int(c['task_id']) < 1 or len(c['grafana_admin_password']) < 8:
        raise ValueError('Task ID 必須大於 0；Grafana 密碼至少 8 字元')
    grafana = urllib.parse.urlparse(c['grafana_url'])
    if grafana.scheme not in ('http', 'https') or not grafana.hostname:
        raise ValueError('Grafana URL 必須是 http 或 https')
    url = urllib.parse.urlparse(c['discord_webhook'])
    if url.scheme != 'https' or url.hostname not in ('discord.com', 'discordapp.com') or not url.path.startswith('/api/webhooks/'):
        raise ValueError('請填 Discord Webhook URL')
    if not re.fullmatch(r'[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]', c['bucket']):
        raise ValueError('S3 bucket 格式錯誤')
    if not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', c['smtp_user']):
        raise ValueError('SMTP 帳號格式錯誤')
    recipients = re.split(r'[,;]', c['alert_email_to'])
    if not all(re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', x.strip()) for x in recipients):
        raise ValueError('告警收件地址格式錯誤')
    c['alert_email_to'] = ';'.join(x.strip() for x in recipients)

def prompt_field(c, key, label, default='', secret=False, help_text=''):
    if help_text:
        print('\n' + help_text, flush=True)
    while True:
        value = ask(label, default, secret=secret)
        if key == 'smtp_password':
            value = value.replace(' ', '')
        candidate = dict(c, **{key: value})
        try:
            # Validate this field using harmless valid values for fields not asked yet.
            validate(candidate)
            c[key] = int(value) if key == 'task_id' else candidate[key]
            return
        except (ValueError, TypeError) as error:
            print('輸入未接受：' + str(error) + '；請重新填這一欄。', flush=True)


def create_input(path, edit=False):
    previous = json.loads(path.read_text()) if path.exists() else {}
    if previous and not edit:
        validate(previous)
        print('沿用既有輸入檔：' + str(path) + '；需重填請加 --edit-config')
        return previous
    route = json.loads(run('ip', '-j', 'route', 'get', '1.1.1.1', capture=True))[0]
    address = route.get('prefsrc') or route.get('src')
    if not address:
        raise RuntimeError('找不到管理 IP，請先設定 VM 網路及預設路由')
    c = {'a_ip':'100.114.236.88', 'b_ip':'100.113.107.95',
         'admin_cidr':str(ipaddress.ip_network(address + '/24', strict=False)),
         'grafana_url':f'http://{address}:3000/', 'bucket':'truenas-backup-myhome-2026',
         'region':'ap-east-2', 'task_id':1, 'snmp_community':'public',
         'aws_access_key_id':'pending', 'aws_secret_access_key':'pending',
         'smtp_user':'pending@example.invalid', 'smtp_password':'pending',
         'alert_email_to':'pending@example.invalid',
         'discord_webhook':'https://discord.com/api/webhooks/pending/pending',
         'grafana_admin_password':'pending-password'}
    fields = [
        ('a_ip','A 站 Tailscale IP',False,'到 Tailscale 管理頁找 A 站 NAS 的 100.x IP；不是監測 VM，也不是 192.168.x IP。'),
        ('b_ip','B 站 Tailscale IP',False,'同上，改找 B 站 NAS；A、B 位址不可相同。'),
        ('admin_cidr','可管理此 VM 的來源網段（必須含 /24 或 /32）',False,
         '填開啟 Grafana 的管理電腦來源：例如同網段全部允許 192.168.23.0/24；只允許某台電腦用該電腦 IP/32。不是監測 VM 的位址。'),
        ('grafana_url','Grafana 瀏覽網址',False,'填瀏覽器開啟監測 VM 的完整網址，包含 http:// 與 :3000/；預設依 VM IP 偵測。'),
        ('bucket','S3 儲存桶',False,'AWS S3 → Buckets，複製目的儲存桶名稱；不含 s3:// 或路徑。'),
        ('region','AWS Region',False,'在該 S3 bucket 內容確認區域代碼；例如 ap-east-2。'),
        ('task_id','TrueNAS A Cloud Sync Task ID',False,'在 TrueNAS A Shell 執行 midclt call cloudsync.query，依 description/path 找出該 S3 任務的 id；不是 job ID。'),
        ('snmp_community','兩站 SNMP Community',False,'填 TrueNAS A、B SNMP 服務的 Community，兩站必須一致。'),
        ('aws_access_key_id','監控 IAM Access Key ID',True,'AWS IAM → 監控用使用者 → 安全憑證 → 存取金鑰；此處填 Access key ID。不可空白。'),
        ('aws_secret_access_key','監控 IAM Secret Access Key',True,'填同一把金鑰的 Secret access key；只在建立時提供。不是 TrueNAS 回報 Token。'),
        ('smtp_user','寄件 Gmail 帳號',False,'填用來寄出告警的完整 Gmail 地址。'),
        ('smtp_password','Google App Password',True,'Google 帳戶啟用兩步驟驗證後建立應用程式密碼；填 16 碼應用程式密碼，不是一般登入密碼。'),
        ('alert_email_to','告警收件 Email；多個以分號分隔',False,'填接收告警的完整信箱；可以和寄件 Gmail 相同。'),
        ('discord_webhook','Discord Webhook URL',True,'Discord 目標頻道 → 編輯頻道 → 整合 → Webhooks → 建立／複製 Webhook URL；填完整 https://discord.com/api/webhooks/...。'),
        ('grafana_admin_password','Grafana admin 密碼，至少8字元',True,'自行設定至少 8 碼的新 Grafana 登入密碼；隱藏輸入時不顯示星號，正常輸入後按 Enter。')]
    print('所有欄位皆必填。一般欄位 Enter 採用 [預設值]；秘密不顯示。編輯時秘密直接 Enter 保留舊值。', flush=True)
    for key, label, secret, help_text in fields:
        default = previous.get(key, c[key] if not secret and key not in ('smtp_user','alert_email_to') else '')
        prompt_field(c, key, label, str(default), secret, help_text)
    validate(c)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    os.fchmod(fd, 0o600)
    with os.fdopen(fd, 'w') as stream:
        json.dump(c, stream, ensure_ascii=False, indent=2)
        stream.write('\n')
    return c


def setup_tailscale(major):
    print('先完成 Tailscale 登入，再填監控資料。', flush=True)
    run('dnf','install','-y','dnf-plugins-core')
    if not shutil.which('tailscale'):
        run('dnf','config-manager','--add-repo',f'https://pkgs.tailscale.com/stable/rhel/{major}/tailscale.repo')
        run('dnf','install','-y','tailscale')
    run('systemctl','enable','--now','tailscaled')
    status=json.loads(run('tailscale','status','--json',capture=True))
    if status.get('BackendState') != 'Running':
        print('請開啟下方 https://login.tailscale.com/... 網址，登入與 A／B 相同的帳戶並核准節點。',flush=True)
        run('tailscale','up')
        status=json.loads(run('tailscale','status','--json',capture=True))
        if status.get('BackendState') != 'Running':
            raise RuntimeError('Tailscale 尚未就緒；請到管理頁核准節點後重跑 --tailscale-only')
    else:
        print('此 VM 已登入 Tailscale，因此不會再出現新的登入網址，不需要登出。',flush=True)
    ts_ip=run('tailscale','ip','-4',capture=True).splitlines()[0]
    ipaddress.IPv4Address(ts_ip)
    print('監測 VM Tailscale IP：' + ts_ip, flush=True)
    return ts_ip


def replace_values(obj, c):
    if isinstance(obj, dict):
        return {k: replace_values(v, c) for k, v in obj.items()}
    if isinstance(obj, list):
        return [replace_values(v, c) for v in obj]
    if isinstance(obj, str):
        for old, new in [('100.114.236.88', c['a_ip']), ('100.113.107.95', c['b_ip']),
                         ('100[.]114[.]236[.]88', c['a_ip'].replace('.', '[.]')),
                         ('100[.]113[.]107[.]95', c['b_ip'].replace('.', '[.]')),
                         ('truenas-backup-myhome-2026', c['bucket']),
                         ('task_id="1"', f'task_id="{c["task_id"]}"'), ('${DS_PROMETHEUS}', UID)]:
            obj = obj.replace(old, new)
    return obj

def render(c, ts_ip, token, base_snmp):
    """Pure rendering, also used by tests. No services or network are changed."""
    validate(c)
    files = {}
    def put(path, content, mode=0o640, group='root'):
        files[path] = (content, mode, group)
    def y(value):
        return yaml.safe_dump(value, sort_keys=False, allow_unicode=True)
    def env(value):
        return ''.join(k + '=' + json.dumps(str(v), ensure_ascii=False) + '\n' for k, v in value.items())
    extra = yaml.safe_load((PROJECT/'configs/snmp-zfs-stable.yml').read_text())
    snmp = copy.deepcopy(base_snmp)
    snmp['modules'].update(extra['modules'])
    snmp['auths']['public_v2']['community'] = c['snmp_community']
    needed = {'if_mib', 'hrStorage', 'hrDevice', 'hrSystem', 'truenas_zfs'}
    if not needed.issubset(snmp['modules']):
        raise ValueError('SNMP 發行版缺少標準模組：' + str(needed - snmp['modules'].keys()))
    put('/etc/snmp_exporter/snmp.yml', y(snmp), 0o644)
    prom = replace_values(yaml.safe_load((PROJECT/'configs/prometheus.yml').read_text()), c)
    for job in prom['scrape_configs']:
        if job['job_name'] == 'cloudsync_success':
            job['static_configs'][0]['targets'] = [ts_ip + ':9108']
        if job['job_name'] == 'aws_s3':
            job['scrape_timeout'] = '130s'
    put('/etc/prometheus/prometheus.yml', y(prom), group='prometheus')
    put('/etc/cloudwatch_exporter/credentials',
        '[default]\naws_access_key_id = ' + c['aws_access_key_id'] + '\naws_secret_access_key = ' + c['aws_secret_access_key'] + '\n', 0o600, 'cloudwatch_exporter')
    put('/etc/s3-exporter.env', env({'S3_BUCKET':c['bucket'], 'AWS_SHARED_CREDENTIALS_FILE':'/etc/cloudwatch_exporter/credentials',
        'AWS_DEFAULT_REGION':c['region'], 'S3_STORAGE_PRICE_USD_PER_GB_MONTH':'0.025', 'S3_REFRESH_SECONDS':'300', 'S3_AWS_TIMEOUT_SECONDS':'120'}), group='cloudwatch_exporter')
    put('/etc/cloudsync-monitor.env', env({'CLOUDSYNC_BIND':ts_ip,'CLOUDSYNC_PORT':'9108','CLOUDSYNC_TOKEN':token,
        'CLOUDSYNC_STATE':'/var/lib/cloudsync-monitor/last_success.json'}), group='cloudsync-monitor')
    put('/etc/grafana/provisioning/datasources/prometheus.yaml', (PROJECT/'configs/grafana-datasource.yaml').read_text(), group='grafana')
    alerts = replace_values(yaml.safe_load((PROJECT/'configs/grafana-alerts-stable.yaml').read_text()), c)
    ids = [r['uid'] for g in alerts['groups'] for r in g['rules']]
    if len(ids) != 9 or len(set(ids)) != 9 or any(g['interval'] != '1m' for g in alerts['groups']):
        raise ValueError('告警設定不是九個唯一 UID／1m 群組')
    put('/etc/grafana/provisioning/alerting/truenas-rules.yaml', y(alerts), group='grafana')
    notification = {'apiVersion':1,
        'templates':[{'orgId':1,'name':'zh_tw_alert_template','template':replace_values((PROJECT/'configs/grafana-notification-template.tmpl').read_text(), c)}],
        'contactPoints':[{'orgId':1,'name':'NAS_Alerts_Email_Discord','receivers':[
            {'uid':'nas-email-v1','type':'email','disableResolveMessage':False,'settings':{
                'addresses':c['alert_email_to'],'singleEmail':True,'subject':'{{ template "nas.title" . }}','message':'{{ template "nas.body" . }}'}},
            {'uid':'nas-discord-v1','type':'discord','disableResolveMessage':False,'settings':{
                'url':c['discord_webhook'],'title':'{{ template "nas.title" . }}','message':'{{ template "nas.body" . }}'}}]}],
        'policies':[{'orgId':1,'receiver':'NAS_Alerts_Email_Discord','group_by':['grafana_folder','alertname','instance'],
            'group_wait':'10s','group_interval':'1m','repeat_interval':'4h'}]}
    put('/etc/grafana/provisioning/alerting/truenas-notifications.yaml', y(notification), group='grafana')
    dashboard = replace_values(json.loads((PROJECT/'grafana/TrueNAS_Hybrid_Cloud.json').read_text()), c)
    dashboard.pop('__inputs', None)
    dashboard['id'] = None
    if len(dashboard['panels']) != 10:
        raise ValueError('Dashboard 必須為十個面板')
    for p in dashboard['panels']:
        if p['id'] in (101,102) and any('hrStorage' not in t['expr'] for t in p['targets']):
            raise ValueError('容量面板必須沿用已確認的 hrStorage 查詢')
    put('/var/lib/grafana/dashboards/truenas.json', json.dumps(dashboard,ensure_ascii=False,indent=2)+'\n', group='grafana')
    provider = {'apiVersion':1,'providers':[{'name':'TrueNAS','orgId':1,'folder':'TrueNAS_Alerts','type':'file',
        'disableDeletion':False,'allowUiUpdates':True,'updateIntervalSeconds':30,'options':{'path':'/var/lib/grafana/dashboards'}}]}
    put('/etc/grafana/provisioning/dashboards/truenas.yaml', y(provider), group='grafana')
    put('/etc/grafana/monitoring.env', env({'GF_SECURITY_ADMIN_USER':'admin','GF_SECURITY_ADMIN_PASSWORD':c['grafana_admin_password'],
        'GF_SERVER_ROOT_URL':c['grafana_url'],'GF_SERVER_DOMAIN':urllib.parse.urlparse(c['grafana_url']).hostname,
        'GF_SMTP_ENABLED':'true','GF_SMTP_HOST':'smtp.gmail.com:587','GF_SMTP_USER':c['smtp_user'],
        'GF_SMTP_PASSWORD':c['smtp_password'],'GF_SMTP_FROM_ADDRESS':c['smtp_user'],'GF_SMTP_FROM_NAME':'NAS_Alert',
        'GF_SMTP_SKIP_VERIFY':'false','GF_SMTP_STARTTLS_POLICY':'MandatoryStartTLS'}), 0o600)
    put('/etc/systemd/system/grafana-server.service.d/monitoring.conf', '[Service]\nEnvironmentFile=/etc/grafana/monitoring.env\n', 0o644)
    for name in SERVICES[:-1]:
        put('/etc/systemd/system/'+name+'.service', (PROJECT/'systemd'/ (name+'.service')).read_text(), 0o644)
    put('/usr/local/bin/s3_realtime_exporter.py', (PROJECT/'exporters/s3_realtime_exporter.py').read_text(), 0o755)
    put('/opt/cloudsync-monitor/cloudsync_success_receiver.py', (PROJECT/'exporters/cloudsync_success_receiver.py').read_text(), 0o755)
    post = '#!/bin/sh\n# 僅貼到 TrueNAS Cloud Sync Post-script；不要在監控 VM 執行。\n'
    post += ': "${CLOUD_SYNC_ID:?This script must run inside a TrueNAS Cloud Sync task}"\n'
    post += 'curl -fsS --connect-timeout 5 --max-time 15 -X POST \\\n'
    post += '  -H "Authorization: Bearer '+token+'" \\\n  --data-urlencode "task_id=${CLOUD_SYNC_ID}" \\\n'
    post += '  "http://'+ts_ip+':9108/success" || logger -t cloudsync-monitor "Cloud Sync callback failed"\n'
    put('/root/truenas-cloudsync-postscript.sh', post, 0o600)
    return files

def download(url, target):
    print('下載：' + url, flush=True)
    for attempt in range(3):
        try:
            with urllib.request.urlopen(url, timeout=60) as src, target.open('wb') as dst:
                shutil.copyfileobj(src, dst)
            return
        except Exception:
            if attempt == 2:
                raise

def release(repo, version, binaries, dest, work):
    name = repo + '-' + version + '.linux-amd64.tar.gz'
    base = f'https://github.com/prometheus/{repo}/releases/download/v{version}/'
    archive, sums = work/name, work/(repo+'-checksums.txt')
    download(base+name, archive)
    download(base+'sha256sums.txt', sums)
    entries = [line.split()[0] for line in sums.read_text().splitlines() if line.split()[-1].lstrip('*') == name]
    if len(entries) != 1 or hashlib.sha256(archive.read_bytes()).hexdigest() != entries[0]:
        raise RuntimeError('SHA256 校驗失敗：' + name)
    with tarfile.open(archive) as tar:
        prefix = repo + '-' + version + '.linux-amd64/'
        for binary in binaries:
            member = tar.extractfile(prefix+binary)
            if member is None:
                raise RuntimeError('發行版缺少 ' + binary)
            target = dest/binary
            target.parent.mkdir(parents=True,exist_ok=True)
            # Replace the inode: overwriting a running executable raises ETXTBSY.
            fd, temporary = tempfile.mkstemp(prefix='.' + binary + '-', dir=target.parent)
            try:
                with os.fdopen(fd, 'wb') as stream:
                    shutil.copyfileobj(member, stream)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.chmod(temporary, 0o755)
                os.replace(temporary, target)
            finally:
                Path(temporary).unlink(missing_ok=True)
        if repo == 'snmp_exporter':
            return yaml.safe_load(tar.extractfile(prefix+'snmp.yml').read())
        for member in tar.getmembers():
            if member.name.startswith((prefix+'consoles/', prefix+'console_libraries/')) and member.isfile():
                target = Path('/etc/prometheus') / member.name[len(prefix):]
                target.parent.mkdir(parents=True, exist_ok=True)
                with target.open('wb') as stream:
                    shutil.copyfileobj(tar.extractfile(member), stream)

def write_files(files, backup):
    import grp
    for name,(content,mode,group) in files.items():
        path=Path(name)
        if path.exists():
            saved=backup/name.lstrip('/')
            saved.parent.mkdir(parents=True,exist_ok=True)
            shutil.copy2(path,saved)
        path.parent.mkdir(parents=True,exist_ok=True)
        temporary=path.with_name(path.name+'.monitoring-new')
        temporary.write_text(content)
        temporary.chmod(mode)
        owner='cloudwatch_exporter' if name.endswith('/credentials') else 'root'
        shutil.chown(temporary,user=owner,group=group)
        temporary.replace(path)

def wait_ready(url):
    for i in range(45):
        try:
            return read_url(url, timeout=3)
        except Exception:
            if i % 5 == 0:
                print('等待服務就緒：'+url,flush=True)
            time.sleep(2)
    raise RuntimeError('服務未就緒：'+url)

def verify_grafana(c):
    """Loading YAML is insufficient: require a working datasource and evaluated rules."""
    auth = base64.b64encode(('admin:' + c['grafana_admin_password']).encode()).decode()
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    def get(path):
        req = urllib.request.Request('http://127.0.0.1:3000' + path,
                                     headers={'Authorization': 'Basic ' + auth})
        with opener.open(req, timeout=20) as response:
            return json.load(response)
    health = get('/api/datasources/uid/' + UID + '/health')
    if health.get('status') != 'OK':
        raise RuntimeError('Grafana Prometheus 資料源健康檢查失敗：' + str(health.get('message')))
    for attempt in range(60):
        groups = get('/api/prometheus/grafana/api/v1/rules')['data']['groups']
        rules = [rule for group in groups for rule in group['rules']]
        failures = [rule for rule in rules if rule.get('health') == 'error' or rule.get('lastError')]
        if failures:
            raise RuntimeError('Grafana 規則評估失敗：' + '; '.join(
                str(rule.get('name')) + ': ' + str(rule.get('lastError')) for rule in failures))
        if len(rules) == 9 and all(rule.get('lastEvaluation') and
                not rule['lastEvaluation'].startswith('0001') for rule in rules):
            print('Grafana：資料源正常；九條規則已實際評估，沒有評估錯誤', flush=True)
            return
        time.sleep(3)
    raise RuntimeError('Grafana 九條規則尚未完成實際評估；請查看 Alert rules 與 grafana-server 日誌')

def verify(c, ts_ip):
    wait_ready('http://127.0.0.1:9090/-/ready')
    wait_ready('http://127.0.0.1:3000/api/health')
    read_url('http://'+ts_ip+':9108/metrics')
    inventory=read_url('http://127.0.0.1:9107/metrics',timeout=150)
    if not re.search(r'^aws_s3_bucket_health_status\{[^\n]*\}\s+1(?:\.0)?$',inventory,re.M):
        raise RuntimeError('S3 API 未成功；請查 IAM 憑證、bucket／region 與 s3_realtime_exporter 日誌')
    def query(expr):
        result=json.loads(read_url('http://127.0.0.1:9090/api/v1/query?'+urllib.parse.urlencode({'query':expr})))
        if result.get('status')!='success':
            raise RuntimeError('Prometheus 查詢失敗')
        return result['data']['result']
    for label,ip,pool in [('A',c['a_ip'],'mainpool'),('B',c['b_ip'],'backuppool')]:
        selector=f'job="truenas_snmp",instance="{ip}"'
        expr=f'hrStorageSize{{{selector},hrStorageDescr="/mnt/{pool}"}} * hrStorageAllocationUnits{{{selector},hrStorageDescr="/mnt/{pool}"}}'
        for attempt in range(15):
            capacity=query(expr)
            members=query('zfsMemberFault{'+selector+'}')
            exitcode=query('zfsStatusCommandExit{'+selector+'}')
            if capacity and members and exitcode:
                break
            time.sleep(3)
        if not capacity or not math.isfinite(float(capacity[0]['value'][1])) or float(capacity[0]['value'][1])<=0:
            raise RuntimeError(label+' 站根掛載點容量未取得；請查 SNMP、hrStorage 與掛載路徑')
        if not members or float(members[0]['value'][1]) not in (0,1) or not exitcode or float(exitcode[0]['value'][1])!=0:
            raise RuntimeError(label+' 站成員來源未就緒；請在該 NAS 設定 extend zfs /usr/sbin/zpool status -P，儲存並重啟 SNMP')
        print(label+' 站：容量與成員指標已由 Prometheus 實際取得',flush=True)
    verify_grafana(c)
    return True

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config',default='/root/monitoring-setup.json')
    modes=parser.add_mutually_exclusive_group()
    modes.add_argument('--verify-only',action='store_true')
    modes.add_argument('--tailscale-only',action='store_true',help='只安裝與登入 Tailscale，不詢問監控資料')
    modes.add_argument('--edit-config',action='store_true',help='逐欄重填已保存的資料後繼續安裝')
    args=parser.parse_args()
    if os.geteuid()!=0:
        raise SystemExit('請先 sudo -i')
    if args.verify_only:
        c=json.loads(Path(args.config).read_text());validate(c)
        verify(c,run('tailscale','ip','-4',capture=True).splitlines()[0])
        print('現有服務及容量／成員指標驗證通過；通知收訊與真實 Cloud Sync 回報另行驗證。')
        return
    osinfo=Path('/etc/os-release').read_text()
    major=rocky_major(osinfo, run('uname','-m',capture=True))
    if args.tailscale_only:
        setup_tailscale(major)
        print('Tailscale 步驟完成。接著依文件準備 TrueNAS 與監控資料，再執行安裝器。')
        return
    if not (STATE/'managed.json').exists() and any(Path(p).exists() for p in ['/etc/prometheus/prometheus.yml','/var/lib/grafana/grafana.db']):
        raise SystemExit('偵測到未由此腳本建立的監控設定。這是全新 VM 安裝器，已停止，未覆寫現有服務。')
    ts_ip=setup_tailscale(major)
    c=create_input(Path(args.config), edit=args.edit_config)
    STATE.mkdir(mode=0o700,parents=True,exist_ok=True)
    (STATE/'managed.json').write_text(json.dumps({'managed':True,'version':1}))
    print('[1/6] 安裝監控依賴套件與校時（Tailscale 已完成）',flush=True)
    run('dnf','install','-y','dnf-plugins-core','curl','git','tar','gzip','unzip','jq','python3-pyyaml','net-snmp-utils','chrony','firewalld')
    run('systemctl','enable','--now','chronyd','firewalld')
    run('timedatectl','set-timezone','Asia/Taipei')
    print('[2/6] 安裝監控主程式與 Grafana',flush=True)
    Path('/etc/yum.repos.d/grafana.repo').write_text('[grafana]\nname=grafana\nbaseurl=https://rpm.grafana.com\nrepo_gpgcheck=1\nenabled=1\ngpgcheck=1\ngpgkey=https://rpm.grafana.com/gpg.key\nsslverify=1\nsslcacert=/etc/pki/tls/certs/ca-bundle.crt\n')
    run('dnf','install','-y','grafana-13.2.4')
    for user in ['snmp_exporter','cloudwatch_exporter','cloudsync-monitor','prometheus']:
        import pwd
        try: pwd.getpwnam(user)
        except KeyError: run('useradd','--system','--no-create-home','--shell','/sbin/nologin',user)
    subprocess.run(['systemctl','disable','--now','cockpit.socket','cockpit.service'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    with tempfile.TemporaryDirectory(prefix='truenas-monitoring-') as temp:
        work=Path(temp)
        base_snmp=release('snmp_exporter','0.26.0',['snmp_exporter'],Path('/usr/local/bin'),work)
        release('prometheus','2.54.1',['prometheus','promtool'],Path('/usr/local/bin'),work)
        if not Path('/usr/local/bin/aws').exists():
            archive=work/'aws.zip';download('https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip',archive)
            run('unzip','-q',str(archive),'-d',str(work))
            installer=[str(work/'aws/install')]
            if Path('/usr/local/aws-cli').exists(): installer.append('--update')
            run(*installer)
    print('[3/6] 產生設定、保留 Receiver Token、自動載入九規則及十面板',flush=True)
    old_env=Path('/etc/cloudsync-monitor.env')
    if old_env.exists():
        values=dict(line.split('=',1) for line in old_env.read_text().splitlines() if '=' in line and not line.startswith('#'))
        token=values.get('CLOUDSYNC_TOKEN','').strip().strip('"')
        if len(token)<24: raise RuntimeError('已有 Receiver Token 無效，停止避免覆寫')
    else:
        import secrets
        token=secrets.token_urlsafe(32)
    for name,owner,group,mode in [('/var/lib/prometheus','prometheus','prometheus',0o755),
        ('/var/lib/cloudsync-monitor','cloudsync-monitor','cloudsync-monitor',0o750),
        ('/etc/cloudwatch_exporter','cloudwatch_exporter','cloudwatch_exporter',0o750)]:
        p=Path(name);p.mkdir(parents=True,exist_ok=True);p.chmod(mode);shutil.chown(p,owner,group)
    backup=STATE/'backups'/datetime.now().strftime('%Y%m%d-%H%M%S-%f')
    backup.mkdir(parents=True,mode=0o700)
    files=render(c,ts_ip,token,base_snmp)
    write_files(files,backup)
    run('/usr/local/bin/snmp_exporter','--config.file=/etc/snmp_exporter/snmp.yml','--dry-run')
    run('/usr/local/bin/promtool','check','config','/etc/prometheus/prometheus.yml')
    print('[4/6] 設定管理網段防火牆',flush=True)
    route=json.loads(run('ip','-j','route','get','1.1.1.1',capture=True))[0]
    try:
        zone=run('firewall-cmd','--get-zone-of-interface='+route['dev'],capture=True)
    except subprocess.CalledProcessError:
        zone='no zone'
    if not zone or zone=='no zone': zone=run('firewall-cmd','--get-default-zone',capture=True)
    for port in ['9090','3000']:
        rule=f'rule family="ipv4" source address="{c["admin_cidr"]}" port port="{port}" protocol="tcp" accept'
        run('firewall-cmd','--permanent','--zone='+zone,'--add-rich-rule='+rule)
    rule=f'rule family="ipv4" source address="{c["a_ip"]}/32" port port="9108" protocol="tcp" accept'
    run('firewall-cmd','--permanent','--zone='+zone,'--add-rich-rule='+rule)
    run('firewall-cmd','--reload')
    print('[5/6] 啟動服務',flush=True)
    run('systemctl','daemon-reload')
    run('systemctl','enable',*SERVICES)
    run('systemctl','restart',*SERVICES)
    print('[6/6] 驗證 S3 API、Prometheus、Grafana 與兩站容量／成員',flush=True)
    verify(c,ts_ip)
    print('\nVM 基礎建置與指標驗證通過。Grafana：'+c['grafana_url'])
    print('帳號 admin；密碼為你剛輸入的值。Dashboard 已自動載入，不需匯入 JSON。')
    print('下一步：將 /root/truenas-cloudsync-postscript.sh 內容貼到 A 站 Cloud Sync Post-script，執行真實任務。')
    print('Email／Discord 已配置，請在 Grafana Contact points 分別 Test 確認收訊。')
    print('秘密輸入檔：'+args.config+'；請勿提交 GitHub。備份：'+str(backup))

if __name__=='__main__':
    try:
        main()
    except Exception as error:
        print('\n建置／驗證尚未完成：'+str(error),flush=True)
        print('請修正這項原因後重跑相同命令；既有 Receiver Token 與成功回報檔會保留。',flush=True)
        raise SystemExit(1)
