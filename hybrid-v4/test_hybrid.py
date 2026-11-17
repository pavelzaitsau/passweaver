import contextlib
from decimal import Decimal
import io
import itertools
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import hybrid


class HybridTests(unittest.TestCase):
    def test_eight_cumulative_budgets_and_increments(self):
        plan = hybrid.plan(235000)
        self.assertEqual([x['total_candidates'] for x in plan],
                         [2350000, 7050000, 28200000, 70500000, 141000000,
                          423000000, 846000000, 1692000000])
        self.assertEqual(sum(x['additional_candidates'] for x in plan), 1692000000)

    def test_fractional_rate_is_floored_without_rounding_up(self):
        self.assertEqual(hybrid.plan('0.15')[0]['total_candidates'], 1)
        for value in (0, -1, True, 'NaN', 'Infinity', 'bad'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                hybrid.plan(value)

    def test_scheduler_continues_stream_and_activates_new_family(self):
        streams = {'a': iter(['Fixture%02d' % n for n in range(10)]),
                   'b': iter(['Harbor%03d' % n for n in range(10)])}
        stages = [(2, [('a', 1)]), (6, [('a', 1), ('b', 1)])]
        got = list(hybrid.schedule(streams, stages, batch=1))
        self.assertEqual([x[2] for x in got],
                         ['Fixture00', 'Fixture01', 'Fixture02', 'Harbor000', 'Fixture03', 'Harbor001'])
        self.assertEqual([x[0] for x in got], [0, 0, 1, 1, 1, 1])

    def test_exhaustion_redistributes_budget_and_short_stream_stops(self):
        stages = [(5, [('a', 2), ('b', 1)])]
        got = list(hybrid.schedule({'a': iter(['short']),
                                   'b': iter(['Fixture00', 'Fixture01'])}, stages, batch=1))
        self.assertEqual(len(got), 2)

    def test_family_dedup_persists_and_cross_family_repeats_count(self):
        stages = [(1, [('a', 1)]), (4, [('a', 1), ('b', 1)])]
        streams = {'a': iter(['Fixture00', 'Fixture00', 'Fixture01']),
                   'b': iter(['Fixture00', 'Harbor000'])}
        got = list(hybrid.schedule(streams, stages, batch=1))
        self.assertEqual(len(got), 4)
        self.assertEqual(len({x[2] for x in got}), 3)

    def test_source_interleaving_keeps_late_source_visible(self):
        self.assertEqual(list(hybrid.interleave([['a', 'b', 'c'], ['x', 'y']])),
                         ['a', 'x', 'b', 'y', 'c'])

    def test_context_is_allowlisted_and_country_selects_language(self):
        self.assertEqual(hybrid.validate_context({'ssid': 'DemoCafe', 'country': 'PL'})['language'], 'pl')
        self.assertEqual(hybrid.validate_context({'ssid': 'DemoCafe'})['language'], 'en')
        for extra in ({'password': 'secret42'}, {'country': 'ZZ'}, {'ssid': 'x' * 33}, {'venue': 42}):
            with self.subTest(extra=extra), self.assertRaises(ValueError):
                hybrid.validate_context(dict({'ssid': 'DemoCafe'}, **extra))

    def test_transliteration_and_context_fields_reach_seeds(self):
        context = hybrid.validate_context({'ssid': 'DemoCafe', 'venue': 'Кафе', 'address': 'Maple 42'})
        seeds = hybrid.context_seeds(context)
        self.assertIn('kafe', seeds)
        self.assertIn('Maple42', seeds)

    def test_pairs_have_independent_case_and_complete_single_digits(self):
        values = set(itertools.islice(hybrid.pair_stream(['maple', 'harbor'], digits=True), 2000))
        self.assertIn('mapleHarbor', values)
        for n in range(10):
            self.assertIn(str(n) + 'mapleharbor', values)
            self.assertIn('mapleharbor' + str(n), values)

    def test_numeric_masks_preserve_width_and_both_directions(self):
        values = list(itertools.islice(hybrid.word_masks(['maple'], 3), 4))
        self.assertEqual(values, ['maple000', '000maple', 'Maple000', '000Maple'])

    def test_rectangular_ranked_grid_is_complete_and_sorted(self):
        expected = sorted(itertools.product(range(3), range(7)),
                          key=lambda p: ((p[0] + 1) * (p[1] + 1), p[0], p[1]))
        self.assertEqual(list(hybrid.ranked_indices(3, 7)), expected)
        self.assertEqual(list(hybrid.ranked_indices(0, 7)), [])

    def test_late_phases_are_finite_and_respect_all_checkpoints(self):
        context = hybrid.validate_context({'ssid': 'DemoCafe'})
        sources = {'raw': ['password123'], 'words': ['maple', 'harbor'], 'provenance': []}
        got = list(hybrid.candidates(context, sources, '0.1', 7200))
        self.assertEqual(len(got), 720)
        for index, seconds in enumerate(hybrid.CHECKPOINTS):
            prefix = [x for x in got if x[0] <= index]
            self.assertEqual(len(prefix), int(Decimal(str(seconds)) * Decimal('0.1')))

    def test_invalid_export_fails_before_creating_file(self):
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / 'out.txt'
            with patch.object(Path, 'open', side_effect=AssertionError('must not open')):
                with self.assertRaises(ValueError):
                    hybrid.export(output, {'ssid': 'DemoCafe'}, {}, 0, 10)

    def test_longer_checkpoint_preserves_exact_prefix(self):
        sources = {'raw': ['password123'], 'words': ['maple', 'harbor'], 'provenance': []}
        context = hybrid.validate_context({'ssid': 'DemoCafe'})
        short = list(hybrid.candidates(context, sources, 1, 10))
        long = list(hybrid.candidates(context, sources, 1, 30))
        self.assertEqual(short, long[:len(short)])
        self.assertEqual(len(short), 10)
        self.assertEqual(len(long), 30)

    def test_all_stages_add_a_new_family(self):
        seen = set()
        for _, families in hybrid.PHASES:
            names = {name for name, _ in families}
            self.assertTrue(names - seen)
            seen.update(names)

    def test_original_context_case_is_preserved(self):
        self.assertIn('DemoCafe2026', set(hybrid.simple_words(['DemoCafe'])))

    def test_each_context_field_is_present_in_early_combination_seeds(self):
        context = hybrid.validate_context({'ssid': 'AmberRiverCafeGuestWiFi',
                                          'venue': 'Long Name ' * 20, 'address': 'Maple 42'})
        self.assertIn('Maple 42', hybrid.context_seeds(context)[:48])

    def test_prior_families_remain_in_later_plans(self):
        seen = set()
        for phase in hybrid.plan(235000):
            names = {name for name, _ in phase['family_weights']}
            self.assertTrue(seen <= names)
            seen.update(names)

    def test_small_budget_is_shared_between_equal_weight_families(self):
        got = list(hybrid.schedule({'a': iter(['Fixture00', 'Fixture01']),
                                    'b': iter(['Harbor000', 'Harbor001'])},
                                   [(2, [('a', 4), ('b', 4)])]))
        self.assertEqual([family for _, family, _ in got], ['a', 'b'])

    def test_report_records_method_and_rejects_changed_code(self):
        sources = {'raw': ['secret42'], 'words': [], 'provenance': []}
        report = hybrid.evaluate([{'ssid': 'DemoCafe', 'password': 'secret42'}],
                                 1, 10, loader=lambda language: sources)
        self.assertIn('method', report)
        original = Path.read_bytes
        def changed(path, *args, **kwargs):
            data = original(path, *args, **kwargs)
            return data + b'\n' if path == hybrid.ROOT / 'hybrid.py' else data
        with patch.object(Path, 'read_bytes', changed), self.assertRaises(ValueError):
            hybrid.evaluate([{'ssid': 'DemoCafe', 'password': 'secret42'}],
                            1, 10, loader=lambda language: sources)

    def test_real_sources_checksum_and_local_language_are_used(self):
        sources = hybrid.load_sources('pl')
        ids = {x['id'] for x in sources['provenance']}
        self.assertEqual(len(ids), 6)
        self.assertIn('frequencywords-pl', ids)
        self.assertIn('frequencywords-en', ids)
        self.assertTrue(any(not x.isascii() for x in sources['words'][:1000]))
        original = Path.read_bytes
        def changed(path, *args, **kwargs):
            data = original(path, *args, **kwargs)
            return data + b'changed\n' if path.name == 'frequencywords-pl.txt' else data
        with patch.object(Path, 'read_bytes', changed), self.assertRaises(ValueError):
            hybrid.load_sources('pl')

    def test_export_is_private_and_does_not_overwrite(self):
        sources = {'raw': ['password123'], 'words': ['maple'], 'provenance': []}
        context = hybrid.validate_context({'ssid': 'DemoCafe'})
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / 'out.txt'
            result = hybrid.export(output, context, sources, 1, 10, 4)
            self.assertEqual(result['candidates'], 4)
            self.assertEqual(output.stat().st_mode & 0o777, 0o600)
            before = output.read_bytes()
            with self.assertRaises(FileExistsError):
                hybrid.export(output, context, sources, 1, 10, 4)
            self.assertEqual(output.read_bytes(), before)

    def test_evaluation_and_export_share_ranks_without_reporting_secrets(self):
        sources = {'raw': ['PRIVATE_SENTINEL'], 'words': ['maple'], 'provenance': []}
        rows = [{'ssid': 'PRIVATE_SSID', 'password': 'PRIVATE_SENTINEL'}]
        report = hybrid.evaluate(rows, 1, 10, loader=lambda language: sources)
        self.assertEqual(report['overall']['matched'], 1)
        text = json.dumps(report)
        self.assertNotIn('PRIVATE_SENTINEL', text)
        self.assertNotIn('PRIVATE_SSID', text)
        self.assertNotIn('attempts', text)


if __name__ == '__main__':
    unittest.main()
