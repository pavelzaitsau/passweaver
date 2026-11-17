import unittest
from unittest.mock import patch
from pathlib import Path
import tempfile

import compare
import hybrid


class PairedComparisonTests(unittest.TestCase):
    def test_cleanup_targets_group_even_when_leader_has_exited(self):
        class Exited:
            pid = 123456789
            def is_alive(self):
                return False
            def join(self, timeout=None):
                pass
        with patch.object(compare.os, 'killpg') as kill:
            compare.cleanup_processes([Exited()])
        self.assertTrue(kill.called)
        self.assertEqual(kill.call_args_list[0].args[0], Exited.pid)

    def test_cleanup_handles_session_startup_race(self):
        class Alive:
            pid = 123456789
            alive = True
            def is_alive(self):
                return self.alive
            def terminate(self):
                self.alive = False
            def join(self, timeout=None):
                pass
            def kill(self):
                self.alive = False
        child = Alive()
        with patch.object(compare.os, 'killpg', side_effect=ProcessLookupError):
            compare.cleanup_processes([child])
        self.assertFalse(child.is_alive())

    def test_missing_dataset_is_rejected_before_freezing_or_workers(self):
        with tempfile.TemporaryDirectory() as folder:
            source, output = Path(folder) / 'inputs', Path(folder) / 'output'
            source.mkdir()
            (source / 'wifox_ssid_password-p01.txt').write_text('DemoCafe/password123\n')
            with patch.object(compare, 'production_check', return_value=87), \
                 patch.object(compare.mp, 'get_context', side_effect=AssertionError('must not start workers')), \
                 self.assertRaises(ValueError):
                compare.run(source, output)
            self.assertFalse(output.exists())

    def test_gains_losses_and_late_phase_eligibility(self):
        plans = hybrid.plan(1)
        left = [{'hit': (0, 1)}, {'hit': (0, 20)}, {'hit': None}, {'hit': (0, 5)}]
        right = [{'hit': (0, 1)}, {'hit': None}, {'hit': (0, 25)}, {'hit': (5, 1)}]
        result = compare.paired_metrics(left, right, plans)
        self.assertEqual({k: result[0][k] for k in ('v3', 'v4', 'common', 'gained', 'lost')},
                         {'v3': 2, 'v4': 1, 'common': 1, 'gained': 0, 'lost': 1})
        self.assertEqual({k: result[1][k] for k in ('v3', 'v4', 'common', 'gained', 'lost')},
                         {'v3': 3, 'v4': 2, 'common': 1, 'gained': 1, 'lost': 2})
        self.assertEqual(result[5]['lost'], 1)
        for row in result:
            self.assertEqual(row['v4'] - row['v3'], row['gained'] - row['lost'])

    def test_mismatched_record_counts_are_rejected(self):
        with self.assertRaises(ValueError):
            compare.paired_metrics([], [{'hit': None}], hybrid.plan(1))
