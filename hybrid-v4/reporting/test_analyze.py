import unittest

import analyze


class AnalysisTests(unittest.TestCase):
    def test_cost_includes_failures_and_respects_phase(self):
        plans = [{'seconds': 10, 'total_candidates': 10}, {'seconds': 30, 'total_candidates': 30}]
        rows = [{'ssid': str(i)} for i in range(4)]
        left = [{'hit': (0, 1), 'emitted': [10, 30]}, {'hit': None, 'emitted': [10, 30]},
                {'hit': (0, 8), 'emitted': [10, 30]}, {'hit': (1, 2), 'emitted': [10, 30]}]
        right = [{'hit': (0, 2), 'emitted': [10, 30]}, {'hit': None, 'emitted': [10, 30]},
                 {'hit': (0, 7), 'emitted': [10, 30]}, {'hit': None, 'emitted': [10, 30]}]
        result = analyze.calculate(rows, ['a', 'a', 'b', 'b'], left, right, plans, 1, repetitions=50)
        first, second = result['checkpoints']
        self.assertEqual((first['v3'], first['v4']), (2, 2))
        self.assertEqual((first['sum_checks_v3'], first['sum_checks_v4']), (29, 29))
        self.assertEqual(first['cost_per_found_ratio_v4_v3'], 1)
        self.assertEqual((second['sum_checks_v3'], second['sum_checks_v4']), (41, 69))
        self.assertEqual((second['v3'], second['v4']), (3, 2))

    def test_cluster_bootstrap_preserves_a_constant_effect(self):
        rows = [{'ssid': 'same'}, {'ssid': 'same'}, {'ssid': 'other'}]
        plans = [{'seconds': 10, 'total_candidates': 10}]
        left = [{'hit': (0, 1), 'emitted': [10]} for _ in rows]
        right = [{'hit': None, 'emitted': [10]} for _ in rows]
        result = analyze.calculate(rows, ['a', 'a', 'b'], left, right, plans, 1, repetitions=100)
        point = result['checkpoints'][0]
        self.assertEqual(result['bootstrap']['clusters'], 2)
        self.assertEqual((point['net_pp_ci_low'], point['net_pp_ci_high']), (-100, -100))
        self.assertEqual(point['net_pp'], -100)


if __name__ == '__main__':
    unittest.main()
