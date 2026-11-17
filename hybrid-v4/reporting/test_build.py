import tempfile
from pathlib import Path
import unittest

import analyze
import build


class ReportTests(unittest.TestCase):
    def fixture(self):
        plans = [{'seconds': s, 'total_candidates': s} for s in (10, 30, 120, 300, 600, 1800, 3600, 7200)]
        outcomes = [{'hit': None, 'emitted': [p['total_candidates'] for p in plans]}]
        stats = analyze.calculate([{'ssid': 'fixture'}], ['p01'], outcomes, outcomes, plans, 1, repetitions=20)
        overall = [{**r} for r in stats['checkpoints']]
        result = {'total': 1, 'overall': overall, 'by_dataset': stats['by_dataset']}
        protocol = {'total': 1, 'checkpoints': plans, 'datasets': [{'dataset': 'p01', 'records': 1}]}
        return stats, result, protocol

    def test_missing_checkpoint_is_rejected(self):
        stats, result, protocol = self.fixture()
        result['overall'] = []
        with self.assertRaises(ValueError):
            build.verify_metrics(stats, result, protocol)

    def test_budget_mismatch_is_rejected(self):
        stats, result, protocol = self.fixture()
        result['overall'][0]['budget'] += 1
        with self.assertRaises(ValueError):
            build.verify_metrics(stats, result, protocol)

    def test_no_hits_does_not_break_graphs(self):
        stats, _, _ = self.fixture()
        with tempfile.TemporaryDirectory() as folder:
            paths = build.charts(stats, Path(folder))
            self.assertEqual(len(paths), 5)
            self.assertTrue(all((Path(folder) / (name + '.png')).exists() for name in paths))


if __name__ == '__main__':
    unittest.main()
