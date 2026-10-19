"""Run ONLY on a disposable monitoring-lab VM with synthetic external services."""
import base64,email,email.policy,json,os,pathlib,subprocess,time,urllib.request,urllib.parse,sys
R=pathlib.Path('/opt/monitoring-lab');C=json.loads(pathlib.Path('/root/monitoring-setup.json').read_text())
assert C['aws_access_key_id']=='LAB_ONLY_NOT_REAL'
assert '127.0.0.1 smtp.gmail.com discord.com' in pathlib.Path('/etc/hosts').read_text()
AUTH=base64.b64encode(('admin:'+C['grafana_admin_password']).encode()).decode();RESULT=[]
openurl=urllib.request.build_opener(urllib.request.ProxyHandler({}))
def api(path,data=None):
 req=urllib.request.Request('http://127.0.0.1:3000'+path,headers={'Authorization':'Basic '+AUTH,'Content-Type':'application/json'},data=None if data is None else json.dumps(data).encode())
 with openurl.open(req,timeout=20) as f:return json.load(f)
def prom(expr):
 with openurl.open('http://127.0.0.1:9090/api/v1/query?'+urllib.parse.urlencode({'query':expr}),timeout=20) as f:return json.load(f)['data']['result']
def check(name,fn,timeout=60):
 start=time.time();last=None
 while True:
  try:
   last=fn()
   if last:break
  except Exception as e:last=repr(e)
  if time.time()-start>=timeout:raise AssertionError(f'{name}: {last}')
  time.sleep(3)
 RESULT.append({'name':name,'passed':True,'elapsed':round(time.time()-start,2)});print('PASS',name,flush=True)
 (R/'acceptance-results.json').write_text(json.dumps(RESULT,ensure_ascii=False,indent=2))
def panel_values(expected):
 dashboard=api('/api/dashboards/uid/truenas321-capacity-cloudsync-vm')['dashboard']
 panel=next(p for p in dashboard['panels'] if p['id']==111)
 values=[]
 for target in panel['targets']:
  result=prom(target['expr'])
  if len(result)!=1:return False
  values.append(float(result[0]['value'][1]))
 return values==list(expected)
def runtime():
 return [r for g in api('/api/prometheus/grafana/api/v1/rules')['data']['groups'] for r in g['rules']]
def rule(uid):return next(r for r in runtime() if r.get('uid')==uid or r.get('grafana_alert',{}).get('uid')==uid)
def notifications(channel,title,recovery=False,since=0):
 if not (R/'events.jsonl').exists():return False
 for line in (R/'events.jsonl').read_text().splitlines():
  e=json.loads(line)
  if e['channel']!=channel or e['time']<since:continue
  if channel=='email':
   msg=email.message_from_string(e['body'],policy=email.policy.default);body=str(msg['subject'])+'\n'+'\n'.join(p.get_content() for p in msg.walk() if p.get_content_type().startswith('text/'))
  else:body=json.dumps(json.loads(e['body']),ensure_ascii=False)
  # Error notifications copy annotations: require the actual alertname line.
  if '告警規則：'+title in body and ('[監控恢復]' if recovery else '[災難備援告警]') in body and '告警規則：DatasourceError' not in body:return True
 return False
try:
 check('SELinux Enforcing',lambda:subprocess.check_output(['getenforce'],text=True).strip()=='Enforcing')
 for svc in ['snmp_exporter','s3_realtime_exporter','cloudsync-monitor','prometheus','grafana-server']:
  check(svc+' active',lambda s=svc:subprocess.call(['systemctl','is-active','--quiet',s])==0)
 check('9 provisioned rules',lambda:len(api('/api/v1/provisioning/alert-rules'))==9)
 check('10 dashboard panels',lambda:len(api('/api/dashboards/uid/truenas321-capacity-cloudsync-vm')['dashboard']['panels'])==10)
 check('Both notification receivers',lambda:{x['type'] for x in api('/api/v1/provisioning/contact-points')}=={'discord','email'})
 check('Five real scrape targets UP',lambda:len(prom('up'))==5 and all(float(r['value'][1])==1 for r in prom('up')),360)
 for node,pool in [('TrueNAS_A','mainpool'),('TrueNAS_B','backuppool')]:
  q=f'hrStorageSize{{nodename="{node}",hrStorageDescr="/mnt/{pool}"}} * hrStorageAllocationUnits{{nodename="{node}",hrStorageDescr="/mnt/{pool}"}}'
  check(node+' capacity exactly 2 TB',lambda q=q:len(prom(q))==1 and float(prom(q)[0]['value'][1])==2000000000000,100)
 check('Real AWS CLI lists fixture inventory',lambda:float(prom('aws_s3_bucket_size_bytes_average')[0]['value'][1])==3072,160)
 env=dict(line.split('=',1) for line in pathlib.Path('/etc/cloudsync-monitor.env').read_text().splitlines() if '=' in line)
 token=json.loads(env['CLOUDSYNC_TOKEN']);url='http://100.104.101.117:9108/success'
 req=urllib.request.Request(url,data=b'task_id=1',headers={'Authorization':'Bearer WRONG'})
 try:openurl.open(req);raise AssertionError('bad token accepted')
 except urllib.error.HTTPError as e:assert e.code==403
 check('Invalid callback token rejected',lambda:True)
 if '--baseline-only' not in sys.argv:
  os.environ['CLOUD_SYNC_ID']='1';subprocess.run(['sh','/root/truenas-cloudsync-postscript.sh'],check=True)
 check('Generated postscript callback scraped',lambda:len(prom('truenas_cloudsync_last_success_timestamp_seconds{task_id="1"}'))==1,60)
 check('All 9 rules evaluated without errors',lambda:len(runtime())==9 and all(r.get('health')=='ok' and not r.get('lastError') for r in runtime()),150)
 (R/'runtime-healthy.json').write_text(json.dumps(runtime(),ensure_ascii=False,indent=2))
 check('Dashboard A/B health values ONLINE 0/0',lambda:panel_values((0,0)),60)
 query={'from':str(int((time.time()-300)*1000)),'to':str(int(time.time()*1000)),'queries':[{'refId':'A','datasource':{'uid':'cg15oru9k9clcd','type':'prometheus'},'expr':'up','instant':True}]}
 check('Grafana datasource actually returns frames',lambda:len(api('/api/ds/query',query)['results']['A'].get('frames',[]))>0)
 if '--baseline-only' in sys.argv:
  print('BASELINE ACCEPTANCE PASSED',flush=True);raise SystemExit(0)
 for mode,filename,title,uid in [('OFFLINE','mainpool.member','ZFS 磁碟成員或 VDEV 異常','zfs_member_fault_v1'),('DEGRADED','mainpool.state','ZFS 儲存池降級（DEGRADED）','alert_zfs_degraded')]:
  start=time.time();(R/filename).write_text(mode)
  check(title+' panel state',lambda mode=mode:panel_values((3 if mode=='OFFLINE' else 1,0)),90)
  check(title+' firing in Grafana',lambda uid=uid:rule(uid)['state']=='firing',240)
  for channel in ['discord','email']:check(title+' '+channel+' notification',lambda ch=channel:notifications(ch,title,since=start),150)
  (R/('runtime-firing-'+mode+'.json')).write_text(json.dumps(runtime(),ensure_ascii=False,indent=2))
  restore=time.time();(R/filename).unlink()
  check(title+' panel returns ONLINE',lambda:panel_values((0,0)),90)
  check(title+' returns inactive',lambda uid=uid:rule(uid)['state']=='inactive',180)
  for channel in ['discord','email']:check(title+' '+channel+' recovery',lambda ch=channel:notifications(ch,title,True,restore),150)
 print('ISOLATED INTEGRATION ACCEPTANCE PASSED',flush=True)
except Exception as e:
 RESULT.append({'name':'FAILED','passed':False,'error':repr(e)});(R/'acceptance-results.json').write_text(json.dumps(RESULT,ensure_ascii=False,indent=2));raise
finally:
 for name in ['mainpool.member','mainpool.state']:(R/name).unlink(missing_ok=True)
