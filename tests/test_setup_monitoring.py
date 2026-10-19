import copy
import importlib.util
import json
import unittest
from pathlib import Path
import yaml

ROOT=Path(__file__).parents[1]
SCRIPT=ROOT/'scripts/setup-monitoring-vm.py'
if not SCRIPT.exists(): SCRIPT=ROOT/'setup-monitoring-vm.py'
spec=importlib.util.spec_from_file_location('setup',SCRIPT)
setup=importlib.util.module_from_spec(spec);spec.loader.exec_module(setup)
setup.PROJECT=ROOT

def fixture():
    return {'a_ip':'100.100.1.1','b_ip':'100.100.1.2','admin_cidr':'192.168.23.0/24',
        'grafana_url':'http://192.168.23.158:3000/','bucket':'fixture-backup-bucket','region':'ap-east-2',
        'task_id':7,'snmp_community':'fixture-community','aws_access_key_id':'fixture-access',
        'aws_secret_access_key':'fixture-secret','smtp_user':'fixture@example.invalid',
        'smtp_password':'fixture-app-password','alert_email_to':'recipient@example.invalid',
        'discord_webhook':'https://discord.com/api/webhooks/123456/fixture-token',
        'grafana_admin_password':'fixture-only-12-chars'}

def base_snmp():
    return {'auths':{'public_v2':{'version':2,'community':'public'}},
        'modules':{name:{'walk':[],'metrics':[{'name':'fixtureMetric','enum_values':{1:'first',2:'second'}}]} for name in ['if_mib','hrStorage','hrDevice','hrSystem']}}

class SetupContract(unittest.TestCase):
    def setUp(self):
        self.files=setup.render(fixture(),'100.100.2.1','fixture-token-long-enough-123456',base_snmp())
    def test_capacity_is_stable(self):
        dashboard=json.loads(self.files['/var/lib/grafana/dashboards/truenas.json'][0])
        self.assertEqual(len(dashboard['panels']),10)
        self.assertNotIn('${DS_PROMETHEUS}',json.dumps(dashboard))
        self.assertNotIn('__inputs',dashboard)
        for p in dashboard['panels']:
            if p['id'] in [101,102]:
                self.assertTrue(all('hrStorage' in t['expr'] for t in p['targets']))
        self.assertNotIn('100[.]114[.]236[.]88',json.dumps(dashboard))
    def test_nine_rules_and_correct_ids(self):
        rules=yaml.safe_load(self.files['/etc/grafana/provisioning/alerting/truenas-rules.yaml'][0])
        ids=[r['uid'] for g in rules['groups'] for r in g['rules']]
        self.assertEqual(len(ids),9);self.assertEqual(len(set(ids)),9)
        self.assertTrue(all(g['interval']=='1m' for g in rules['groups']))
        text=json.dumps(rules)
        self.assertNotIn('zfsUsablePool',text)
        self.assertNotIn('100.114.236.88',text)
        self.assertIn('task_id=\\"7\\"',text)
    def test_dual_notification_and_recovery(self):
        n=yaml.safe_load(self.files['/etc/grafana/provisioning/alerting/truenas-notifications.yaml'][0])
        receivers=n['contactPoints'][0]['receivers']
        self.assertEqual({x['type'] for x in receivers},{'email','discord'})
        self.assertTrue(all(not x['disableResolveMessage'] for x in receivers))
        self.assertEqual(n['policies'][0]['receiver'],n['contactPoints'][0]['name'])
        self.assertIn('tz "Asia/Taipei"',n['templates'][0]['template'])
    def test_receiver_token_is_passed_not_rotated(self):
        env=self.files['/etc/cloudsync-monitor.env'][0]
        post=self.files['/root/truenas-cloudsync-postscript.sh'][0]
        self.assertIn('fixture-token-long-enough-123456',env)
        self.assertIn('fixture-token-long-enough-123456',post)
        self.assertIn('CLOUD_SYNC_ID:?',post)
    def test_private_file_modes(self):
        self.assertEqual(self.files['/etc/grafana/monitoring.env'][1],0o600)
        self.assertEqual(self.files['/etc/cloudwatch_exporter/credentials'][1],0o600)
        self.assertEqual(self.files['/root/truenas-cloudsync-postscript.sh'][1],0o600)
    def test_no_extra_capacity_dependency(self):
        snmp=yaml.safe_load(self.files['/etc/snmp_exporter/snmp.yml'][0])
        names={m['name'] for m in snmp['modules']['truenas_zfs']['metrics']}
        self.assertEqual(names,{'zpoolHealthStr','zfsMemberFault','zfsStatusCommandExit'})
        self.assertEqual(set(snmp['modules']['if_mib']['metrics'][0]['enum_values']),{1,2})
        p=yaml.safe_load(self.files['/etc/prometheus/prometheus.yml'][0])
        self.assertEqual(len(p['scrape_configs']),4)
        self.assertEqual(next(j for j in p['scrape_configs'] if j['job_name']=='cloudsync_success')['static_configs'][0]['targets'],['100.100.2.1:9108'])
    def test_reject_placeholder(self):
        c=fixture();c['aws_secret_access_key']='YOUR_SECRET'
        with self.assertRaises(ValueError): setup.validate(c)

if __name__=='__main__': unittest.main()
