import re
import unittest
from pathlib import Path
import yaml

MODULE = yaml.safe_load((Path(__file__).parents[1] / 'configs/snmp-zfs-modules.yml').read_text())['modules']['truenas_zfs']
METRICS = {metric['name']: metric for metric in MODULE['metrics']}

def extract(metric, suffix, text):
    for spec in METRICS[metric]['regex_extracts'][suffix]:
        match = re.fullmatch(spec['regex'], text)
        if match:
            return float(match.group(int(spec['value'][1:]))) if spec['value'].startswith('$') else float(spec['value'])
    return None

class SnmpTextContract(unittest.TestCase):
    def test_online_pool_with_faulted_leaf(self):
        text = 'pool: mainpool\nstate: ONLINE\nconfig:\n\n NAME STATE READ WRITE CKSUM\n mainpool ONLINE 0 0 0\n /dev/sdc FAULTED 3 67 0 too many errors\nerrors: No known data errors'
        self.assertEqual(extract('zfsMemberFault', '', text), 1)

    def test_non_online_rows(self):
        for state in ['DEGRADED','FAULTED','UNAVAIL','OFFLINE','REMOVED','SUSPENDED']:
            with self.subTest(state=state):
                self.assertEqual(extract('zfsMemberFault', '', f'config:\n /dev/disk/a {state} 0 0 0\nerrors: none'), 1)

    def test_valid_online(self):
        self.assertEqual(extract('zfsMemberFault', '', 'config:\n /dev/sda ONLINE 0 0 0\nerrors: No known data errors'), 0)

    def test_errors_are_not_healthy(self):
        for text in ['', 'cannot open /dev/zfs: Permission denied', 'No Such Instance']:
            self.assertEqual(extract('zfsMemberFault', '', text), 2)

    def test_capacity_ignores_boot_pool(self):
        for pool in ['mainpool','backuppool']:
            text = f'boot-pool\t100\t10\t90\t10\n{pool}\t3000\t200\t2800\t6\n'
            for suffix, expected in [('SizeBytes',3000),('AllocatedBytes',200),('FreeBytes',2800),('UsedPercent',6)]:
                self.assertEqual(extract('zfsDataPool', suffix, text), expected)

    def test_missing_capacity_stays_missing(self):
        self.assertIsNone(extract('zfsDataPool','SizeBytes','No Such Instance'))

if __name__ == '__main__':
    unittest.main()
