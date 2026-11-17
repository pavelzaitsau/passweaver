import json
import hashlib
import hmac
import tempfile
import subprocess
import sys
import os
import time
from pathlib import Path
import unittest
from unittest.mock import patch

import compare_v5


class CacheTests(unittest.TestCase):
    def test_busy_worker_termination_closes_native_descendant(self):
        with tempfile.TemporaryDirectory() as folder:
            pidfile = Path(folder) / 'native.pid'
            def native():
                child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'])
                pidfile.write_text(str(child.pid))
                try:
                    time.sleep(30)
                    yield 'SyntheticValue42'
                finally:
                    child.terminate()
                    child.wait(timeout=3)
            parent, pipe = compare_v5.mp.get_context('fork').Pipe()
            with patch.object(compare_v5.v5, 'prince_stream', native):
                worker = compare_v5.mp.get_context('fork').Process(target=compare_v5._worker,
                    args=(pipe, 'prince', {'words': []}, {}))
                worker.start()
                pipe.close()
                parent.send(1000000)
                for _ in range(200):
                    if pidfile.exists(): break
                    time.sleep(.01)
                self.assertTrue(pidfile.exists())
                native_pid = int(pidfile.read_text())
                try:
                    with patch.object(compare_v5.os, 'killpg', side_effect=PermissionError):
                        compare_v5.cleanup_workers([worker])
                    with self.assertRaises(ProcessLookupError): os.kill(native_pid, 0)
                finally:
                    if worker.is_alive(): worker.kill();worker.join()
                    try: os.kill(native_pid, 9)
                    except ProcessLookupError: pass
                    parent.close()
    def test_mask_mix_matches_fixed_block_stream_at_a_partial_limit(self):
        import itertools
        sources = {'words': ['maple', 'harbor']}
        streams = (compare_v5.v5.hybrid.rules.filtered(compare_v5.v5.hybrid.word_masks(sources['words'], n)) for n in (3, 4))
        values = list(itertools.islice(compare_v5.v5.hybrid.rules.mix(streams, 256), 300))
        targets = {value: i for i, value in enumerate(values)}
        state = compare_v5.mask_state(sources, targets, 300)
        self.assertEqual(state['hits'], {target: i + 1 for i, target in enumerate(targets.values())})
    def test_verified_baseline_has_all_records_and_checkpoints(self):
        cached = compare_v5.read_source()
        self.assertEqual(len(cached['rows']), 852)
        self.assertEqual(len(cached['protocol']['checkpoints']), 8)

    def test_modified_hmac_key_is_rejected(self):
        original = Path.read_bytes
        def changed(path, *args, **kwargs):
            data = original(path, *args, **kwargs)
            return data + b'changed' if path.name == 'attestation.key' else data
        with patch.object(Path, 'read_bytes', changed), self.assertRaises(ValueError):
            compare_v5.read_source()

    def test_cached_hit_outside_verified_range_is_rejected(self):
        cached = compare_v5.read_source()
        values = [{'hit': [0, 999999999999], 'emitted': [p['total_candidates'] for p in cached['protocol']['checkpoints']]}]
        with self.assertRaises(ValueError):
            compare_v5.validate_outcomes(values, cached['protocol']['checkpoints'])

    def test_missing_output_attestation_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder, self.assertRaises(ValueError):
            compare_v5.read_cache(evidence=folder)

    def test_permission_denied_group_signal_still_terminates_worker(self):
        class Worker:
            pid = 123456789
            alive = True
            def is_alive(self): return self.alive
            def terminate(self): self.alive = False
            def kill(self): self.alive = False
            def join(self, timeout=None): pass
        child = Worker()
        with patch.object(compare_v5.os, 'killpg', side_effect=PermissionError):
            compare_v5.cleanup_workers([child])
        self.assertFalse(child.is_alive())

    def test_same_bucket_rank_tampering_fails_hmac(self):
        protocol = json.loads((compare_v5.CACHE / 'protocol.json').read_text())
        rows = [{'ssid': 'Synthetic', 'password': 'secret42'}]
        protocol['total'] = 1
        canonical = json.dumps(rows, ensure_ascii=False, separators=(',', ':')).encode()
        source = dict(rows=rows, labels=['p01'], protocol=protocol, canonical=canonical)
        config = compare_v5.v5.base_config(protocol['checkpoints'][-1]['total_candidates'])
        binding = dict(records=1, rate=235000, checkpoints=protocol['checkpoints'], datasets=protocol['datasets'],
            input_attestation=protocol['snapshot_attestation_hmac_sha256'],
            source_files_sha256=protocol['method']['files_sha256'],
            producer_sha256=hashlib.sha256((compare_v5.ROOT / 'refresh_baseline.py').read_bytes()).hexdigest(),
            config=config, creation='fresh exact reference evaluation, not adopted old outcomes')
        original = json.dumps([{'hit': [0, 2], 'emitted': [p['total_candidates'] for p in protocol['checkpoints']]}], separators=(',', ':')).encode()
        key = b'A' * 32
        signed = json.dumps(binding, sort_keys=True, separators=(',', ':')).encode()
        certificate = dict(binding=binding, hmac_sha256=hmac.new(key, signed+b'\0'+original+b'\0'+canonical, hashlib.sha256).hexdigest())
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/'private-inputs').mkdir()
            (root/'certificate.json').write_text(json.dumps(certificate))
            (root/'private-inputs/cache.key').write_bytes(key)
            (root/'private-inputs/v3-outcomes.json').write_bytes(original.replace(b'[0,2]', b'[0,3]'))
            with patch.object(compare_v5, 'read_source', return_value=source), self.assertRaises(ValueError):
                compare_v5.read_cache(evidence=root)


if __name__ == '__main__':
    unittest.main()
