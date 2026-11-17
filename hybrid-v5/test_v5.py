import hashlib
import itertools
import json
from pathlib import Path
import random
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import v5


class V5Tests(unittest.TestCase):
    def test_close_error_still_closes_all_sources(self):
        class Source:
            closed = False
            def __iter__(self): return self
            def __next__(self): return 'SyntheticValue42'
            def close(self): self.closed = True
        base, extra = Source(), Source()
        def fail():
            base.closed = True
            raise OSError('close failed')
        base.close = fail
        stream = v5.compose(base, {'extra': extra}, 10, 5, [('v3_continue', 1), ('extra', 1)])
        next(stream)
        with self.assertRaises(OSError): stream.close()
        self.assertTrue(extra.closed)

    def test_generator_close_failure_removes_export(self):
        class Source:
            def __iter__(self): return self
            def __next__(self): return (0, 'v3_prefix', 'SyntheticValue42')
            def close(self): raise OSError('close failed')
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'out.txt'
            argv = ['v5.py', '--ssid', 'Demo', '--rate', '1', '--until', '10',
                    '--output', str(path), '--max-candidates', '1']
            with patch.object(v5.sys, 'argv', argv), patch.object(v5, 'candidates', return_value=Source()):
                self.assertEqual(v5.main(), 1)
            self.assertFalse(path.exists())
    def test_all_checkpoints_preserve_the_same_prefix(self):
        def run(budget, boundaries):
            return list(v5.compose(iter(['BaseValue%04d' % i for i in range(100)]),
                                   {'extra': iter(['ExtraValue%04d' % i for i in range(100)])},
                                   budget, 5, [('v3_continue', 4), ('extra', 3)], batch_size=3,
                                   boundaries=boundaries))
        short = run(23, [23])
        longer = run(60, [23, 60])
        self.assertEqual(short, longer[:len(short)])
    def test_protected_prefix_is_byte_exact_v3(self):
        base = ['BaseValue%04d' % i for i in range(100)]
        output = list(v5.compose(iter(base), {'extra': iter(['ExtraValue000'])}, 40, 50,
                                 [('v3_continue', 4), ('extra', 1)], batch_size=2))
        self.assertEqual([value for _, _, value in output], base[:40])

    def test_first_extension_attempt_follows_prefix(self):
        output = list(v5.compose(iter(['BaseValue%04d' % i for i in range(20)]),
                                 {'extra': iter(['ExtraValue%04d' % i for i in range(20)])},
                                 12, 5, [('v3_continue', 1), ('extra', 1)], batch_size=1))
        self.assertEqual(len(output), 12)
        self.assertEqual(output[5], (5, 'v3_continue', 'BaseValue0005'))
        self.assertEqual(output[6], (5, 'extra', 'ExtraValue0000'))

    def test_exhaustion_uses_actual_prefix_length(self):
        output = list(v5.compose(iter(['BaseValue0000']), {'extra': iter(['ExtraValue%04d' % i for i in range(20)])},
                                 12, 5, [('v3_continue', 1), ('extra', 1)], batch_size=1))
        self.assertEqual(len(output), 12)
        self.assertEqual(output[1], (5, 'extra', 'ExtraValue0000'))

    def test_protected_short_run_does_not_unlock_late_families(self):
        self.assertEqual(list(v5.compose(iter([]), {'extra': iter(['ExtraValue000'])},
                                        3, 5, [('v3_continue', 1), ('extra', 1)])), [])

    def test_index_matches_reference_randomly(self):
        rng = random.Random(55279)
        for _ in range(500):
            p, budget, quantum = rng.randrange(1, 20), rng.randrange(1, 100), rng.randrange(1, 5)
            base = ['BaseValue%04d' % i for i in range(rng.randrange(50))]
            extra = ['ExtraValue%04d' % i for i in range(rng.randrange(70))]
            weights = [('v3_continue', rng.randrange(1, 5)), ('extra', rng.randrange(1, 5))]
            reference = list(v5.compose(iter(base), {'extra': iter(extra)}, budget, p, weights, batch_size=quantum))
            segments, emitted, prefix = v5.index(len(base), {'extra': len(extra)}, budget, p, weights, quantum)
            families = {'v3_prefix': base[:prefix], 'v3_continue': base[prefix:], 'extra': extra}
            expanded = []
            for segment in segments:
                for rank in range(segment['family_start'], segment['family_start'] + segment['count']):
                    expanded.append((v5.batch.global_rank(segment, rank), segment['phase'], segment['family'],
                                     families[segment['family']][rank - 1]))
            expanded.sort()
            self.assertEqual([(phase, name, val) for _, phase, name, val in expanded], reference)
            self.assertEqual(emitted, len(reference))

    def test_real_small_prefix_matches_accepted_v3(self):
        raw, words, _ = v5.v3.load_words()
        config = v5.base_config(2350000)
        expected = list(itertools.islice(v5.v3.candidates_for_ssid('DemoCafe', config, raw, words), 1000))
        got = list(itertools.islice(v5.candidates({'ssid': 'DemoCafe'}, 235000, 10), 1000))
        self.assertEqual([value for _, value in expected], [value for _, _, value in got])

    def test_native_prince_matches_direct_binary_prefix_and_cleans_up(self):
        manifest = v5.check_prince()
        argv = [str(v5.ROOT / manifest['binary']), *manifest['argv'], '--limit=20', str(v5.ROOT / manifest['seed'])]
        direct = subprocess.run(argv, capture_output=True, check=True, timeout=20,
                                env=dict(v5.os.environ, LC_ALL='C')).stdout.splitlines()
        stream = v5.prince_stream()
        got = list(itertools.islice(stream, 20))
        stream.close()
        self.assertEqual([value.encode() for value in got], direct)
        self.assertTrue(all(8 <= len(value) <= 16 for value in direct))

    def test_modified_prince_seed_is_rejected(self):
        original = Path.read_bytes
        def changed(path, *args, **kwargs):
            data = original(path, *args, **kwargs)
            return data + b'changed\n' if path == v5.ROOT / 'prince-seeds.txt' else data
        with patch.object(Path, 'read_bytes', changed), self.assertRaises(ValueError):
            v5.check_prince()

    def test_modified_prince_source_is_rejected(self):
        original = Path.read_bytes
        def changed(path, *args, **kwargs):
            data = original(path, *args, **kwargs)
            return data + b'changed' if path.name == 'pp.c' else data
        with patch.object(Path, 'read_bytes', changed), self.assertRaises(ValueError):
            v5.check_prince()

    def test_cached_baseline_is_not_given_to_generator(self):
        self.assertNotIn('password', v5.candidates.__code__.co_varnames)


if __name__ == '__main__':
    unittest.main()
