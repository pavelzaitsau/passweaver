import unittest

import planning


class DurationTests(unittest.TestCase):
    def test_simple_units(self):
        self.assertEqual(planning.parse_duration('90s'), 90)
        self.assertEqual(planning.parse_duration('20m'), 1200)
        self.assertEqual(planning.parse_duration('2h'), 7200)

    def test_combined(self):
        self.assertEqual(planning.parse_duration('1h30m'), 5400)

    def test_rejects_garbage(self):
        for bad in ('', '20', 'abc', '20x', '1h30'):
            with self.assertRaises(ValueError):
                planning.parse_duration(bad)

    def test_rejects_zero(self):
        with self.assertRaises(ValueError):
            planning.parse_duration('0s')


class RenderTests(unittest.TestCase):
    def test_human_duration(self):
        self.assertEqual(planning.human_duration(45), '45s')
        self.assertEqual(planning.human_duration(1800), '30m')
        self.assertEqual(planning.human_duration(5400), '1h30m')

    def test_human_count(self):
        self.assertEqual(planning.human_count(2_200_000_000), '2.2G')
        self.assertEqual(planning.human_count(48_000), '48.0k')
        self.assertEqual(planning.human_count(42), '42')

    def test_time_modes_cover_checkpoints(self):
        self.assertEqual(planning.TIME_MODES['std'], 3600)
        self.assertEqual(planning.TIME_MODES['test'], 120)

    def test_plan_estimate_and_cap(self):
        plan = planning.Plan(10, 'std', 3600, 620000, 180000, max_total=7200)
        self.assertEqual(plan.est_seconds, 7200)
        text = plan.render()
        self.assertIn('10 networks', text)
        self.assertIn('capped', text)

    def test_plan_singular(self):
        plan = planning.Plan(1, 'test', 120, 50000, 6000, None)
        self.assertIn('1 network ', plan.render())


if __name__ == '__main__':
    unittest.main()
