#!/usr/bin/env python3
"""Run on each TrueNAS 25.10 host. Preserve all capacity-related options."""
import json
import re
import subprocess
from datetime import datetime
from pathlib import Path

COMMUNITY = 'public'
LINE = 'extend zfs /usr/sbin/zpool status -P'

def call(method,*args):
    return json.loads(subprocess.check_output(['midclt','call',method]+[json.dumps(x) for x in args],text=True))

def main():
    subprocess.run(['/usr/sbin/zpool','status','-P'],check=True,stdout=subprocess.DEVNULL)
    config=call('snmp.config')
    previous={'options':config.get('options') or '', 'community':config['community']}
    backup=Path('/root/snmp-stable-'+datetime.now().strftime('%Y%m%d-%H%M%S-%f')+'.json')
    backup.write_text(json.dumps(previous));backup.chmod(0o600)
    lines=[s for s in previous['options'].splitlines() if not re.match(r'^\s*extend\s+zfs\s',s)]
    new={'options':'\n'.join(lines+[LINE]).strip()+'\n', 'community':COMMUNITY}
    try:
        call('snmp.update',new)
        call('service.update','snmp',{'enable':True})
        if not call('service.restart','snmp',{'silent':False}):
            raise RuntimeError('SNMP 未啟動')
    except Exception:
        call('snmp.update',previous)
        call('service.restart','snmp',{'silent':False})
        raise
    print('SNMP 已啟用並設為開機啟動；已保存：'+LINE)
    print('容量來源保持既有 hrStorage；其他附屬參數已保留。備份：'+str(backup))

if __name__=='__main__': main()
