"""Exercise release() with a real running executable; no network required."""
import hashlib,importlib.util,io,os,shutil,subprocess,tarfile,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1];SCRIPT=ROOT/'scripts/setup-monitoring-vm.py'
if not SCRIPT.exists():SCRIPT=ROOT/'setup-monitoring-vm.py'
spec=importlib.util.spec_from_file_location('installer',SCRIPT);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
class BinaryReinstall(unittest.TestCase):
 def test_running_executable_is_replaced_atomically(self):
  with tempfile.TemporaryDirectory() as tmp:
   p=Path(tmp);dest=p/'bin';dest.mkdir();target=dest/'prometheus';shutil.copy2('/bin/sleep',target)
   proc=subprocess.Popen([str(target),'30'])
   try:
    # Demonstrate the original failure on this actual operating system.
    with self.assertRaises(OSError) as ctx:target.open('wb')
    self.assertEqual(ctx.exception.errno,26)
    old=target.stat().st_ino;name='prometheus-2.54.1.linux-amd64.tar.gz';archive=p/name
    with tarfile.open(archive,'w:gz') as tar:tar.add('/bin/sleep',arcname='prometheus-2.54.1.linux-amd64/prometheus')
    sums=p/'sums';sums.write_text(hashlib.sha256(archive.read_bytes()).hexdigest()+'  '+name+'\n')
    work=p/'work';work.mkdir()
    def download(url,out):shutil.copyfile(sums if url.endswith('sha256sums.txt') else archive,out)
    with patch.object(m,'download',download):m.release('prometheus','2.54.1',['prometheus'],dest,work)
    self.assertNotEqual(target.stat().st_ino,old);self.assertIsNone(proc.poll());self.assertEqual(subprocess.run([str(target),'0']).returncode,0)
   finally:proc.terminate();proc.wait(timeout=5)
if __name__=='__main__':unittest.main()
