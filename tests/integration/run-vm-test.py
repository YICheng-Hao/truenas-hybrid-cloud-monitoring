#!/usr/bin/env python3
"""Disposable QEMU VM integration test. Intended for GitHub-hosted Ubuntu runners.
External NAS/S3/SMTP/Discord and Tailnet identity are synthetic; all monitoring
programs, AWS CLI, RPM services and SELinux run inside real Rocky Linux.
"""
import argparse,functools,hashlib,http.server,json,os,pathlib,re,shutil,subprocess,tarfile,threading,time,urllib.request
R=pathlib.Path(__file__).resolve().parents[2]
P=argparse.ArgumentParser();P.add_argument('--major',choices=['9','10'],default='9');P.add_argument('--repetitions',type=int,default=1);A=P.parse_args()
D=R/'_lab';D.mkdir(exist_ok=True);summary=[]
def run(args,**kw):return subprocess.run(args,check=True,**kw)
def download(url,p):
 for attempt in range(3):
  try:
   with urllib.request.urlopen(url,timeout=90) as src,p.open('wb') as out:shutil.copyfileobj(src,out)
   return
  except Exception:
   if attempt==2:raise
print('Preparing official Rocky '+A.major+' cloud image',flush=True)
base=f'https://download.rockylinux.org/pub/rocky/{A.major}/images/x86_64/'
name=f'Rocky-{A.major}-GenericCloud-Base.latest.x86_64.qcow2'
image=D/name;download(base+name,image);download(base+'CHECKSUM',D/'CHECKSUM')
expected=re.search(r'SHA256 \('+re.escape(name)+r'\) = ([a-f0-9]+)',(D/'CHECKSUM').read_text()).group(1)
actual=hashlib.file_digest(image.open('rb'),'sha256').hexdigest();assert actual==expected
(D/'image-verification.json').write_text(json.dumps({'url':base+name,'sha256':actual,'verified':True}))
run(['ssh-keygen','-q','-t','ed25519','-N','','-f',str(D/'lab-key')])
run(['openssl','req','-x509','-newkey','rsa:2048','-nodes','-keyout',str(D/'key.pem'),'-out',str(D/'cert.pem'),'-days','2','-subj','/CN=monitoring-lab','-addext','subjectAltName=DNS:smtp.gmail.com,DNS:discord.com,IP:127.0.0.1'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
with tarfile.open(D/'source.tar.gz','w:gz') as tar:
 for name in ['scripts','configs','systemd','exporters','grafana']:tar.add(R/name,arcname='truenas-hybrid-cloud-monitoring/'+name)
class Files(http.server.SimpleHTTPRequestHandler):
 def __init__(self,*a,**k):super().__init__(*a,directory=str(R),**k)
 def log_message(self,*a):pass
server=http.server.ThreadingHTTPServer(('0.0.0.0',18080),Files);threading.Thread(target=server.serve_forever,daemon=True).start()
key=(D/'lab-key.pub').read_text().strip()
ssh=['ssh','-i',str(D/'lab-key'),'-p','2222','-o','StrictHostKeyChecking=no','-o','UserKnownHostsFile=/dev/null','-o','ConnectTimeout=10','-o','ServerAliveInterval=15','-o','ServerAliveCountMax=4','root@127.0.0.1']
def command(script,log,timeout=1800):
 print('RUN',log.name,flush=True)
 try:
  with log.open('w') as out:run(ssh+['bash -s'],input=script,text=True,stdout=out,stderr=subprocess.STDOUT,timeout=timeout)
 except Exception:
  print('FAILED COMMAND LOG: '+str(log), flush=True)
  print(log.read_text(errors='replace')[-24000:], flush=True)
  raise
 print('PASS',log.name,flush=True)
def wait_ssh(timeout=600):
 until=time.monotonic()+timeout
 while time.monotonic()<until:
  try:
   p=subprocess.run(ssh+['test -f /root/lab-ready'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=20)
   if p.returncode==0:return
  except subprocess.TimeoutExpired:pass
  time.sleep(3)
 raise RuntimeError('VM did not finish cloud-init within timeout')
def collect(out):
 for remote,name in [('/opt/monitoring-lab/acceptance-results.json','acceptance-results.json'),('/opt/monitoring-lab/acceptance-full-results.json','acceptance-full-results.json'),('/opt/monitoring-lab/events.jsonl','notification-events.jsonl'),('/var/log/dnf.log','dnf.log')]:
  with (out/name).open('w') as stream:subprocess.run(ssh+['cat '+remote],stdout=stream,stderr=subprocess.DEVNULL,text=True,timeout=60)
 command('systemctl --no-pager status snmp_exporter s3_realtime_exporter cloudsync-monitor prometheus grafana-server; journalctl -u grafana-server --no-pager -n 160',out/'final-service-status.log',120)
try:
 for repetition in range(1,A.repetitions+1):
  out=D/f'round-{repetition:02}';out.mkdir()
  overlay=out/'disk.qcow2';run(['qemu-img','create','-f','qcow2','-F','qcow2','-b',str(image),str(overlay)]);run(['qemu-img','resize',str(overlay),'40G'])
  user=out/'user-data';user.write_text('#cloud-config\nusers:\n- name: root\n  ssh_authorized_keys:\n  - '+key+'\ndisable_root: false\nssh_pwauth: false\nruncmd:\n- [touch, /root/lab-ready]\n')
  meta=out/'meta-data';meta.write_text(f'instance-id: monitoring-lab-{repetition}\nlocal-hostname: monitoring-lab\n')
  seed=out/'seed.iso';run(['cloud-localds',str(seed),str(user),str(meta)])
  kvm=os.path.exists('/dev/kvm') and os.access('/dev/kvm',os.R_OK|os.W_OK)
  args=['qemu-system-x86_64','-machine','q35,accel='+('kvm' if kvm else 'tcg'),'-cpu','host' if kvm else 'max','-smp','2','-m','4096','-display','none','-serial','file:'+str(out/'serial.log'),'-monitor','none','-drive','file='+str(overlay)+',format=qcow2,if=virtio','-drive','file='+str(seed)+',format=raw,media=cdrom','-netdev','user,id=n1,hostfwd=tcp:127.0.0.1:2222-:22','-device','virtio-net-pci,netdev=n1','-no-reboot']
  print('Starting fresh VM',repetition,'accelerator',('kvm' if kvm else 'tcg'),flush=True)
  proc=subprocess.Popen(args,stdout=open(out/'qemu.log','w'),stderr=subprocess.STDOUT)
  try:
   wait_ssh()
   # Use a stable kernel-log boot so a first-boot kdump job does not compete with DNF.
   command('set -e\ncat /etc/os-release\ngetenforce\nsystemctl disable --now kdump || true\ncurl --noproxy "*" -fsS http://10.0.2.2:18080/tests/integration/bootstrap.sh -o /root/lab-bootstrap.sh\nbash /root/lab-bootstrap.sh\n',out/'01-fresh-install.log',1800)
   command('set -e\ncurl --noproxy "*" -fsS http://10.0.2.2:18080/tests/integration/acceptance.py -o /opt/monitoring-lab/acceptance.py\npython3 /opt/monitoring-lab/acceptance.py\ncp /opt/monitoring-lab/acceptance-results.json /opt/monitoring-lab/acceptance-full-results.json\n',out/'02-fault-recovery-acceptance.log',1500)
   # Receiver token and successful-callback state must survive reinstall.
   preserve='sha256sum /etc/cloudsync-monitor.env /var/lib/cloudsync-monitor/last_success.json'
   command('set -e\n'+preserve+' > /root/pre-reinstall.sha256\npython3 /root/truenas-hybrid-cloud-monitoring/scripts/setup-monitoring-vm.py\nsha256sum -c /root/pre-reinstall.sha256\npython3 /opt/monitoring-lab/acceptance.py --baseline-only\n',out/'03-reinstall.log',1200)
   command("nohup sh -c 'sleep 2; systemctl reboot' >/dev/null 2>&1 < /dev/null &\necho REBOOT_SCHEDULED\n",out/'04-reboot-request.log',60)
   proc.wait(timeout=180)
   proc=subprocess.Popen(args,stdout=open(out/'qemu-reboot.log','w'),stderr=subprocess.STDOUT)
   wait_ssh()
   command('set -e\nsha256sum -c /root/pre-reinstall.sha256\npython3 /opt/monitoring-lab/acceptance.py --baseline-only\n',out/'05-after-reboot.log',600)
   collect(out)
   summary.append({'round':repetition,'os_major':A.major,'accelerator':'kvm' if kvm else 'tcg','fresh_install':True,'fault_and_recovery':True,'reinstall_preserves_state':True,'reboot':True})
  except Exception as e:
   summary.append({'round':repetition,'passed':False,'error':repr(e)})
   try:collect(out)
   except Exception as err:print('Collect failed:',repr(err),flush=True)
   raise
  finally:
   (D/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2))
   proc.terminate()
   try:proc.wait(timeout=15)
   except subprocess.TimeoutExpired:proc.kill()
finally:server.shutdown()
