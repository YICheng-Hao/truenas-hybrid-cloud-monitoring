"""Installer must reject live Grafana with a broken datasource or evaluator."""
import importlib.util,json,threading,unittest
from pathlib import Path
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
R=Path(__file__).resolve().parents[1];P=R/'scripts/setup-monitoring-vm.py'
if not P.exists():P=R/'setup-monitoring-vm.py'
s=importlib.util.spec_from_file_location('setup_verification',P);m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
class Verification(unittest.TestCase):
 def setUp(self):
  self.mode='ok';outer=self
  class H(BaseHTTPRequestHandler):
   def do_GET(self):
    if not self.headers.get('Authorization','').startswith('Basic '):self.send_error(401);return
    if self.path.endswith('/health'):x={'status':'ERROR' if outer.mode=='datasource-error' else 'OK','message':'fixture'}
    else:
     rules=[{'name':str(i),'health':'ok','lastEvaluation':'2026-10-19T00:00:00Z'} for i in range(9)]
     if outer.mode=='evaluation-error':rules[0].update(health='error',lastError='plugin not registered')
     x={'data':{'groups':[{'rules':rules}]}}
    body=json.dumps(x).encode();self.send_response(200);self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
   def log_message(self,*a):pass
  self.server=ThreadingHTTPServer(('127.0.0.1',3000),H);self.thread=threading.Thread(target=self.server.serve_forever);self.thread.start()
 def tearDown(self):self.server.shutdown();self.server.server_close();self.thread.join()
 def verify(self):return m.verify_grafana({'grafana_admin_password':'fixture-only-password'})
 def test_all_nine_evaluated(self):self.verify()
 def test_datasource_error_rejected(self):
  self.mode='datasource-error'
  with self.assertRaisesRegex(RuntimeError,'資料源健康檢查失敗'):self.verify()
 def test_loaded_but_evaluation_error_rejected(self):
  self.mode='evaluation-error'
  with self.assertRaisesRegex(RuntimeError,'規則評估失敗'):self.verify()
if __name__=='__main__':unittest.main()
