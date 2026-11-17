"""Run portable synthetic tests without access to private experiment inputs."""
import os
from pathlib import Path
import subprocess
import sys
import unittest
ROOT = Path(__file__).resolve().parent

if len(sys.argv) == 1:
    env = {k:v for k,v in os.environ.items() if not k.startswith('WFM_')}
    env['PYTHONDONTWRITEBYTECODE'] = '1'
    codes = [subprocess.run([sys.executable, str(Path(__file__).resolve()), name], env=env).returncode
             for name in ('final-algorithm', 'hybrid-v4')]
    sys.exit(any(codes))
folder = ROOT / sys.argv[1]
os.chdir(folder)
sys.path.insert(0, str(folder))
suite = unittest.defaultTestLoader.discover(str(folder))
print('\n=== ' + folder.name + ' ===', flush=True)
sys.exit(not unittest.TextTestRunner(verbosity=2).run(suite).wasSuccessful())
