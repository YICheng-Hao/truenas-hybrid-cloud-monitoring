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

    def test_capacity_uses_root_and_does_not_sum_children(self):
        for pool in ['mainpool','backuppool']:
            text = f'boot-pool\t100\t900\n{pool}\t200\t1800\n{pool}/data\t190\t1800\n'
            for suffix, expected in [('UsedBytes',200),('AvailableBytes',1800)]:
                self.assertEqual(extract('zfsUsablePool', suffix, text), expected)

    def test_missing_capacity_stays_missing(self):
        self.assertIsNone(extract('zfsUsablePool','UsedBytes','No Such Instance'))

    def test_old_raw_pool_columns_are_not_accepted(self):
        self.assertIsNone(extract('zfsUsablePool','UsedBytes','mainpool\t3000\t200\t2800\t6\n'))

if __name__ == '__main__':
    unittest.main()
