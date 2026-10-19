"""Exercise real snmp_exporter with a local synthetic SNMP GET responder.
Usage: python3 tests/snmp-capacity-smoke.py /path/to/snmp_exporter
No TrueNAS host is contacted.
"""
import copy, socket, subprocess, sys, tempfile, threading, time, urllib.request
from pathlib import Path
import yaml

def unpack(data, pos=0):
    tag, length = data[pos], data[pos+1]
    pos += 2
    if length & 128:
        count = length & 127
        length = int.from_bytes(data[pos:pos+count], 'big')
        pos += count
    return tag, data[pos:pos+length], pos+length

def pack(tag, content):
    size = len(content)
    if size < 128:
        length = bytes([size])
    else:
        digits = size.to_bytes((size.bit_length()+7)//8, 'big')
        length = bytes([128+len(digits)]) + digits
    return bytes([tag]) + length + content

def fields(content):
    result, pos = [], 0
    while pos < len(content):
        tag, value, pos = unpack(content, pos)
        result.append((tag, value))
    return result

fixture = {'text': ''}
udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
udp.bind(('127.0.0.1', 0))
snmp_port = udp.getsockname()[1]
def respond():
    while True:
        try:
            data, peer = udp.recvfrom(65535)
            message = fields(unpack(data)[1])
            pdu = fields(message[2][1])
            variables = fields(pdu[3][1])
            bindings = []
            for _, binding in variables:
                oid = fields(binding)[0]
                bindings.append(pack(48, pack(*oid) + pack(4, fixture['text'].encode())))
            response = pack(162, pack(*pdu[0]) + pack(2,b'\0') + pack(2,b'\0') + pack(48,b''.join(bindings)))
            udp.sendto(pack(48, pack(*message[0]) + pack(*message[1]) + response), peer)
        except OSError:
            return
threading.Thread(target=respond, daemon=True).start()
probe = socket.socket(); probe.bind(('127.0.0.1',0)); http_port = probe.getsockname()[1]; probe.close()
root = Path(__file__).parents[1]
metric = next(m for m in yaml.safe_load((root/'configs/snmp-zfs-modules.yml').read_text())['modules']['truenas_zfs']['metrics'] if m['name']=='zfsUsablePool')
config = {'auths':{'public_v2':{'version':2,'community':'public'}}, 'modules':{'capacity':{'get':[metric['oid']],'metrics':[metric]}}}
with tempfile.TemporaryDirectory() as directory:
    path = Path(directory)/'snmp.yml'; path.write_text(yaml.safe_dump(config))
    process = subprocess.Popen([sys.argv[1], '--config.file='+str(path), '--web.listen-address=127.0.0.1:'+str(http_port)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        time.sleep(.5)
        for text, expected in [
            ('boot-pool\t100\t900\nmainpool\t200\t1800\nmainpool/data\t190\t1800\n', (200,1800)),
            ('backuppool\t300\t1700\nbackuppool/backup_snapshot\t290\t1700\n', (300,1700)),
            ('mainpool\t3000\t200\t2800\t6\n', None)]:
            fixture['text'] = text
            body = urllib.request.urlopen(f'http://127.0.0.1:{http_port}/snmp?target=127.0.0.1:{snmp_port}&auth=public_v2&module=capacity',timeout=5).read().decode()
            if expected is None:
                assert '\nzfsUsablePoolUsedBytes ' not in body, body
            else:
                assert f'\nzfsUsablePoolUsedBytes {expected[0]}\n' in body, body
                assert f'\nzfsUsablePoolAvailableBytes {expected[1]}\n' in body, body
        print('PASS: real snmp_exporter parsed A/B root capacity, ignored child rows, rejected old raw format')
    finally:
        process.terminate(); process.wait(timeout=5); udp.close()
