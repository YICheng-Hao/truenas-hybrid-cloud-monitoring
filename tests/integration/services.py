"""Isolated test doubles only: no real NAS, S3, email or Discord account."""
import socket,threading,time,os,json,ssl,socketserver,http.server,urllib.parse
from pathlib import Path
ROOT=Path(os.environ.get('LAB_ROOT','/opt/monitoring-lab'));ROOT.mkdir(exist_ok=True,parents=True)
def event(channel,body):
 with (ROOT/'events.jsonl').open('a') as f:f.write(json.dumps({'channel':channel,'body':body,'time':time.time()},ensure_ascii=False)+'\n')
def unpack(data,p=0):
 tag,n=data[p:p+2];p+=2
 if n&128:k=n&127;n=int.from_bytes(data[p:p+k],'big');p+=k
 return tag,data[p:p+n],p+n
def fields(data):
 result=[];p=0
 while p<len(data):t,v,p=unpack(data,p);result.append((t,v))
 return result
def pack(t,v):
 n=len(v);b=n.to_bytes(max(1,(n.bit_length()+7)//8),'big');return bytes([t])+(bytes([n]) if n<128 else bytes([128+len(b)])+b)+v
def integer(n,t=2):
 b=n.to_bytes(max(1,(n.bit_length()+7)//8),'big');return (t,(b'\0'+b if b[0]&128 else b))
def oidtuple(b):
 out=[b[0]//40,b[0]%40];n=0
 for x in b[1:]:
  n=(n<<7)|(x&127)
  if x<128:out.append(n);n=0
 return tuple(out)
def oidbytes(o):
 b=bytes([o[0]*40+o[1]])
 for n in o[2:]:
  a=[n&127];n>>=7
  while n:a.insert(0,128|(n&127));n>>=7
  b+=bytes(a)
 return b
def table(pool):
 d={}
 def put(oid,v):d[tuple(map(int,oid.split('.')))]=v
 state=(ROOT/(pool+'.state')).read_text().strip() if (ROOT/(pool+'.state')).exists() else 'ONLINE'
 member=(ROOT/(pool+'.member')).read_text().strip() if (ROOT/(pool+'.member')).exists() else ('OFFLINE' if state!='ONLINE' else 'ONLINE')
 for i,p in [(1,pool),(2,'boot-pool')]:
  put(f'1.3.6.1.4.1.50536.1.1.1.1.2.{i}',(4,p.encode()));put(f'1.3.6.1.4.1.50536.1.1.1.1.3.{i}',(4,(state if i==1 else 'ONLINE').encode()))
 txt=f'  pool: {pool}\n state: {state}\nconfig:\n\n NAME STATE READ WRITE CKSUM\n {pool} {state} 0 0 0\n   raidz2-0 {state} 0 0 0\n     /dev/lab-disk {member} 0 0 0\n\nerrors: No known data errors\n'
 put('1.3.6.1.4.1.8072.1.3.2.3.1.2.3.122.102.115',(4,txt.encode()));put('1.3.6.1.4.1.8072.1.3.2.3.1.4.3.122.102.115',integer(0))
 for i,desc,size,used,unit in [(1,'/mnt/'+pool,488281250,100000,4096),(2,'Physical memory',1048576,400000,4096)]:
  for col,v in [(1,integer(i)),(3,(4,desc.encode())),(4,integer(unit)),(5,integer(size)),(6,integer(used))]:put(f'1.3.6.1.2.1.25.2.3.1.{col}.{i}',v)
 put('1.3.6.1.2.1.25.3.3.1.2.1',integer(12));put('1.3.6.1.2.1.25.1.1.0',integer(100000,67))
 for o,v in [('1.3.6.1.2.1.2.2.1.1.1',integer(1)),('1.3.6.1.2.1.2.2.1.2.1',(4,b'tailscale0')),('1.3.6.1.2.1.31.1.1.1.1.1',(4,b'tailscale0')),('1.3.6.1.2.1.31.1.1.1.18.1',(4,b'')),('1.3.6.1.2.1.31.1.1.1.6.1',integer(int(time.time()*1000),70)),('1.3.6.1.2.1.31.1.1.1.10.1',integer(int(time.time()*2000),70))]:put(o,v)
 return d
def snmp(ip,pool,port=161):
 s=socket.socket(socket.AF_INET,socket.SOCK_DGRAM);s.bind((ip,port))
 while True:
  try:
   data,peer=s.recvfrom(65535);msg=fields(unpack(data)[1]);tag=msg[2][0];pdu=fields(msg[2][1]);vs=fields(pdu[3][1]);d=table(pool);keys=sorted(d);bindings=[]
   repetitions=min(30,int.from_bytes(pdu[2][1],'big')) if tag==165 else 1
   requested=[oidtuple(fields(v)[0][1]) for _,v in vs]
   for rep in range(repetitions):
    new=[]
    for o in requested:
     if tag==160:key=o;val=d.get(o,(128,b''))
     else:
      key=next((k for k in keys if k>o),None);val=d[key] if key else (130,b'');key=key or o
     bindings.append(pack(48,pack(6,oidbytes(key))+pack(*val)));new.append(key)
    requested=new
   response=pack(162,pack(*pdu[0])+pack(2,b'\0')+pack(2,b'\0')+pack(48,b''.join(bindings)))
   s.sendto(pack(48,pack(*msg[0])+pack(*msg[1])+response),peer)
  except Exception as e:event('snmp-error',str(e))
class S3(http.server.BaseHTTPRequestHandler):
 def do_GET(self):
  body=b'<?xml version="1.0" encoding="UTF-8"?><ListBucketResult xmlns="http://s3.amazonaws.com/doc/2006-03-01/"><Name>truenas-backup-myhome-2026</Name><Prefix/><KeyCount>2</KeyCount><MaxKeys>1000</MaxKeys><IsTruncated>false</IsTruncated><Contents><Key>a.txt</Key><LastModified>2026-10-19T00:00:00.000Z</LastModified><ETag>"abc"</ETag><Size>1024</Size><StorageClass>STANDARD</StorageClass></Contents><Contents><Key>b.txt</Key><LastModified>2026-10-19T01:00:00.000Z</LastModified><ETag>"def"</ETag><Size>2048</Size><StorageClass>STANDARD</StorageClass></Contents></ListBucketResult>'
  self.send_response(200);self.send_header('Content-Type','application/xml');self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
 def log_message(self,*a):pass
class Discord(http.server.BaseHTTPRequestHandler):
 def do_POST(self):
  body=self.rfile.read(int(self.headers.get('Content-Length','0'))).decode();event('discord',body);self.send_response(204);self.end_headers()
 def log_message(self,*a):pass
class SMTP(socketserver.StreamRequestHandler):
 def handle(self):
  self.wfile.write(b'220 monitoring-lab ESMTP\r\n');self.wfile.flush()
  while True:
   line=self.rfile.readline()
   if not line:return
   command=line.decode(errors='replace').strip();verb=command.split(' ')[0].upper()
   if verb in ('EHLO','HELO'):self.wfile.write(b'250-lab\r\n250-STARTTLS\r\n250 AUTH PLAIN LOGIN\r\n')
   elif verb=='STARTTLS':
    self.wfile.write(b'220 Ready for TLS\r\n');self.wfile.flush();self.connection=ctx.wrap_socket(self.connection,server_side=True);self.rfile=self.connection.makefile('rb');self.wfile=self.connection.makefile('wb')
   elif verb=='AUTH':self.wfile.write(b'235 Authentication successful\r\n')
   elif verb in ('MAIL','RCPT','RSET','NOOP'):self.wfile.write(b'250 OK\r\n')
   elif verb=='DATA':
    self.wfile.write(b'354 End with dot\r\n');self.wfile.flush();lines=[]
    while True:
     row=self.rfile.readline()
     if row in (b'.\r\n',b''):break
     lines.append(row)
    event('email',b''.join(lines).decode(errors='replace'));self.wfile.write(b'250 Queued\r\n')
   elif verb=='QUIT':self.wfile.write(b'221 Bye\r\n');self.wfile.flush();return
   else:self.wfile.write(b'250 OK\r\n')
   self.wfile.flush()
if __name__=='__main__':
 for ip,pool in [('100.114.236.88','mainpool'),('100.113.107.95','backuppool')]:threading.Thread(target=snmp,args=(ip,pool),daemon=True).start()
 ctx=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER);ctx.load_cert_chain(str(ROOT/'cert.pem'),str(ROOT/'key.pem'))
 servers=[http.server.ThreadingHTTPServer(('127.0.0.1',19000),S3),http.server.ThreadingHTTPServer(('127.0.0.1',443),Discord),socketserver.ThreadingTCPServer(('127.0.0.1',587),SMTP)]
 servers[1].socket=ctx.wrap_socket(servers[1].socket,server_side=True)
 for s in servers:threading.Thread(target=s.serve_forever,daemon=True).start()
 print('LAB FIXTURES READY',flush=True)
 threading.Event().wait()
