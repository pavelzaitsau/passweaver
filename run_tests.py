"""Run portable synthetic tests without access to private experiment inputs."""
import os
from pathlib import Path
import subprocess
import sys
import unittest
ROOT = Path(__file__).resolve().parent
PRIVATE_TESTS = {
    'test_cached_hit_outside_verified_range_is_rejected',
    'test_missing_output_attestation_is_rejected',
    'test_modified_hmac_key_is_rejected',
    'test_same_bucket_rank_tampering_fails_hmac',
    'test_verified_baseline_has_all_records_and_checkpoints',
}
def cases(suite):
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            yield from cases(item)
        else:
            yield item
if len(sys.argv) == 1:
    env = {k:v for k,v in os.environ.items() if not k.startswith('WFM_')}
    env['PYTHONDONTWRITEBYTECODE'] = '1'
    codes = [subprocess.run([sys.executable, str(Path(__file__).resolve()), name], env=env).returncode
             for name in ('final-algorithm', 'hybrid-v4', 'hybrid-v5', 'hybrid-v5.1', 'passweaver')]
    sys.exit(any(codes))
folder = ROOT / sys.argv[1]
os.chdir(folder)
sys.path.insert(0, str(folder))
suite = unittest.defaultTestLoader.discover(str(folder))
for case in cases(suite):
    if case.__class__.__module__ == 'test_cache' and case._testMethodName in PRIVATE_TESTS:
        method = getattr(type(case), case._testMethodName)
        setattr(type(case), case._testMethodName, unittest.skip('Requires deliberately excluded private baseline and HMAC key')(method))
print('\n=== ' + folder.name + ' ===', flush=True)
sys.exit(not unittest.TextTestRunner(verbosity=2).run(suite).wasSuccessful())
