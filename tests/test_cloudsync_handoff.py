import contextlib
import importlib.util
import io
import json
import os
import subprocess
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('handoff', ROOT/'scripts/prepare-cloudsync-handoff.py')
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)


class Handoff(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.root = Path(self.tmp.name)
        self.config = self.root/'config.json'; self.env = self.root/'receiver.env'
        self.config.write_text(json.dumps({'task_id': 7, 'bucket': 'fixture-bucket'}))
        self.token = 'fixture-token-12345678901234567890'
        self.env.write_text('CLOUDSYNC_BIND="127.0.0.1"\nCLOUDSYNC_PORT="9108"\nCLOUDSYNC_TOKEN="'+self.token+'"\n')
        self.payload = m.payload_from_installed(self.config, self.env)
        self.old = 'curl -fsS --connect-timeout 5 --max-time 15 \\\n -X POST \\\n -H "Authorization: Bearer old-fixture-token" \\\n --data-urlencode "task_id=${CLOUD_SYNC_ID}" \\\n http://100.81.0.1 || true'
        self.task = {'id':7, 'attributes':{'bucket':'fixture-bucket'}, 'path':'/mnt/mainpool/data',
                     'direction':'PUSH', 'post_script':self.old, 'pre_script':'echo untouched',
                     'schedule':{'hour':'19'}, 'transfer_mode':'COPY'}
        self.calls = []
    def tearDown(self): self.tmp.cleanup()
    def api(self, method, *args):
        self.calls.append((method,args))
        if method == 'cloudsync.query': return [dict(self.task)]
        self.assertEqual(method, 'cloudsync.update')
        self.assertEqual(args[0], 7)
        self.assertEqual(set(args[1]), {'post_script'})
        self.task.update(args[1]); return dict(self.task)
    def apply(self):
        with patch.object(m, 'midclt', side_effect=self.api), contextlib.redirect_stdout(io.StringIO()):
            m.apply_on_nas(self.payload, self.root/'backups')
    def test_replaces_old_callback_and_backs_up_without_touching_task_settings(self):
        self.apply()
        self.assertEqual(self.task['post_script'], self.payload['post_script'])
        self.assertEqual(self.task['pre_script'],'echo untouched')
        self.assertEqual(self.task['schedule'], {'hour':'19'})
        backup = next((self.root/'backups').glob('*.json'))
        self.assertEqual(json.loads(backup.read_text())['post_script'], self.old)
        self.assertEqual(backup.stat().st_mode & 0o777, 0o600)
    def test_second_apply_does_not_write(self):
        self.apply(); self.calls.clear(); self.apply()
        self.assertEqual([name for name,args in self.calls], ['cloudsync.query'])
    def test_refuses_unknown_custom_commands(self):
        self.task['post_script'] = self.old + '\necho keep-me'
        with self.assertRaisesRegex(RuntimeError, '自訂命令'): self.apply()
        self.assertNotIn('cloudsync.update', [name for name,args in self.calls])
    def test_wrong_task_bucket_refused(self):
        self.task['attributes']['bucket'] = 'other-bucket'
        with self.assertRaisesRegex(RuntimeError, 'bucket'): self.apply()
    def test_payload_uses_installed_token_and_complete_url(self):
        self.assertIn(self.token, self.payload['post_script'])
        self.assertIn('http://127.0.0.1:9108/success', self.payload['post_script'])
        self.assertTrue(m.known_callback(self.payload['post_script']))
    def test_generated_paste_command_runs_update_and_readback(self):
        command = m.paste_command(self.payload)
        code = command.split('\n',1)[1].rsplit('\nTRUENAS_CLOUDSYNC_UPDATE',1)[0]
        # Execute the exact generated source, changing only the local API transport and backup directory.
        namespace = {}; exec(compile(code.rsplit('\napply_on_nas(',1)[0], '<generated>', 'exec'), namespace)
        namespace['midclt'] = self.api
        with contextlib.redirect_stdout(io.StringIO()):
            namespace['apply_on_nas'](self.payload, self.root/'backups')
        self.assertEqual(self.task['post_script'],self.payload['post_script'])
        self.assertEqual(len(self.calls),3)
    def test_actual_generated_postscript_posts_receiver_with_task_environment(self):
        spec = importlib.util.spec_from_file_location('handoff_receiver', ROOT/'exporters/cloudsync_success_receiver.py')
        receiver = importlib.util.module_from_spec(spec); spec.loader.exec_module(receiver)
        receiver.TOKEN = self.token; receiver.STATE = self.root/'success.json'
        server = ThreadingHTTPServer(('127.0.0.1',0),receiver.Handler)
        thread = threading.Thread(target=server.serve_forever); thread.start()
        try:
            self.env.write_text(self.env.read_text().replace('9108',str(server.server_port)))
            payload = m.payload_from_installed(self.config,self.env)
            result = subprocess.run(['sh'], input=payload['post_script'], text=True,
                                    env=dict(os.environ,CLOUD_SYNC_ID='7'),capture_output=True)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertIn('7',receiver.read_state())
            self.assertNotIn('1',receiver.read_state())
        finally:
            server.shutdown(); server.server_close(); thread.join()

if __name__ == '__main__': unittest.main()
