"""Interactive installer boundaries: no real credentials or service mutations."""
import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from test_setup_monitoring import setup, fixture


class InputFlow(unittest.TestCase):
    def test_password_boundary(self):
        for size in (8, 12):
            c = fixture(); c['grafana_admin_password'] = 'x' * size
            setup.validate(c)
        c['grafana_admin_password'] = 'x' * 7
        with self.assertRaisesRegex(ValueError, '至少 8'):
            setup.validate(c)

    def test_admin_source_requires_explicit_cidr(self):
        for value in ('192.168.23.158', '192.168.23.158/24'):
            c = fixture(); c['admin_cidr'] = value
            with self.assertRaises(ValueError): setup.validate(c)
        for value in ('192.168.23.0/24', '192.168.23.20/32'):
            c['admin_cidr'] = value; setup.validate(c)

    def test_bad_task_reprompts_same_field(self):
        c = fixture()
        with patch.object(setup, 'ask', side_effect=['abc', '0', '7']) as ask, contextlib.redirect_stdout(io.StringIO()):
            setup.prompt_field(c, 'task_id', 'Task ID')
        self.assertEqual(c['task_id'], 7)
        self.assertEqual(ask.call_count, 3)

    def test_bad_source_reprompts_without_accepting_vm_ip(self):
        c = fixture()
        with patch.object(setup, 'ask', side_effect=['192.168.23.158', '192.168.23.0/24']), contextlib.redirect_stdout(io.StringIO()):
            setup.prompt_field(c, 'admin_cidr', '來源網段')
        self.assertEqual(c['admin_cidr'], '192.168.23.0/24')

    def test_blank_secret_reprompts(self):
        c = fixture()
        with patch.object(setup, 'ask', side_effect=['', 'fixture-secret']) as ask, contextlib.redirect_stdout(io.StringIO()):
            setup.prompt_field(c, 'aws_secret_access_key', 'Secret', secret=True)
        self.assertEqual(ask.call_count, 2)

    def test_edit_keeps_secrets_and_private_permissions(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'input.json'; path.write_text(json.dumps(fixture())); path.chmod(0o644)
            def answer(label, default='', secret=False):
                return '192.168.23.0/24' if '來源網段' in label else default
            # Reproduce the screenshot's invalid saved value; edit must recover it.
            c = fixture(); c['admin_cidr'] = '192.168.23.158'; path.write_text(json.dumps(c))
            with patch.object(setup, 'run', return_value='[{"prefsrc":"192.168.23.158"}]'), patch.object(setup, 'ask', side_effect=answer), contextlib.redirect_stdout(io.StringIO()):
                result = setup.create_input(path, edit=True)
            self.assertEqual(result, fixture())
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_first_run_collects_all_fields(self):
        values = ['100.100.1.1', '100.100.1.2', '192.168.23.0/24',
                  'http://192.168.23.158:3000/', 'fixture-backup-bucket', 'ap-east-2', '7',
                  'fixture-community', 'fixture-access', 'fixture-secret',
                  'fixture@example.invalid', 'fixture-app-password', 'recipient@example.invalid',
                  'https://discord.com/api/webhooks/123456/fixture-token', '12345678']
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'input.json'
            with patch.object(setup, 'run', return_value='[{"prefsrc":"192.168.23.158"}]'), patch.object(setup, 'ask', side_effect=values) as ask, contextlib.redirect_stdout(io.StringIO()):
                result = setup.create_input(path)
            self.assertEqual(ask.call_count, 15)
            expected = fixture(); expected['grafana_admin_password'] = '12345678'
            self.assertEqual(result, expected)
            self.assertEqual(json.loads(path.read_text()), expected)

    def test_tailscale_logged_in_does_not_request_new_login(self):
        calls = []
        def run(*args, **kwargs):
            calls.append(args)
            if args[:2] == ('tailscale', 'status'): return '{"BackendState":"Running"}'
            if args[:2] == ('tailscale', 'ip'): return '100.100.2.1'
        with patch.object(setup, 'run', side_effect=run), patch.object(setup.shutil, 'which', return_value='/usr/bin/tailscale'), contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(setup.setup_tailscale('10'), '100.100.2.1')
        self.assertNotIn(('tailscale', 'up'), calls)
        self.assertIn('不會再出現', output.getvalue())

    def test_tailscale_new_login_precedes_ip_read(self):
        calls = []; states = iter(['NeedsLogin', 'Running'])
        def run(*args, **kwargs):
            calls.append(args)
            if args[:2] == ('tailscale', 'status'): return json.dumps({'BackendState': next(states)})
            if args[:2] == ('tailscale', 'ip'): return '100.100.2.1'
        with patch.object(setup, 'run', side_effect=run), patch.object(setup.shutil, 'which', return_value=None), contextlib.redirect_stdout(io.StringIO()):
            setup.setup_tailscale('10')
        self.assertLess(calls.index(('tailscale', 'up')), calls.index(('tailscale', 'ip', '-4')))
        self.assertIn(('dnf','config-manager','--add-repo','https://pkgs.tailscale.com/stable/rhel/10/tailscale.repo'), calls)

    def test_tailscale_only_exits_before_collecting_secrets(self):
        with patch('sys.argv', ['setup', '--tailscale-only']), patch.object(setup.os, 'geteuid', return_value=0), patch.object(setup, 'rocky_major', return_value='10'), patch.object(setup, 'run'), patch.object(setup, 'setup_tailscale') as ts, patch.object(setup, 'create_input') as inputs, contextlib.redirect_stdout(io.StringIO()):
            setup.main()
        ts.assert_called_once_with('10'); inputs.assert_not_called()

    def test_still_unapproved_node_stops(self):
        with patch.object(setup, 'run', return_value='{"BackendState":"NeedsMachineAuth"}'), patch.object(setup.shutil, 'which', return_value='/usr/bin/tailscale'), contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaisesRegex(RuntimeError, '尚未就緒'):
                setup.setup_tailscale('9')


if __name__ == '__main__': unittest.main()
