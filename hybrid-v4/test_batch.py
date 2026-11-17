import itertools
import random
import unittest
import json
from pathlib import Path
from unittest.mock import patch
from types import SimpleNamespace

import hybrid
import batch
import oracles


class BatchIndexTests(unittest.TestCase):
    def test_invalid_v3_config_is_rejected_before_comparison(self):
        config_path = hybrid.v3.ROOT / 'config.json'
        original = Path.read_text
        def read(path, *args, **kwargs):
            text = original(path, *args, **kwargs)
            if path == config_path:
                value = json.loads(text)
                value['pair_ordering'] = 'invalid-order'
                return json.dumps(value)
            return text
        with patch.object(Path, 'read_text', read), \
             patch.object(hybrid.v3, 'load_words', return_value=(['secret42'], [], {})), \
             self.assertRaises(ValueError):
            batch.evaluate_version([{'ssid': 'Demo', 'password': 'secret42'}], 'v3', 1, 10, workers=1)

    def test_v3_config_array_of_pairs_is_not_coerced_to_object(self):
        config_path = hybrid.v3.ROOT / 'config.json'
        original = Path.read_text
        def read(path, *args, **kwargs):
            value = original(path, *args, **kwargs)
            return json.dumps(list(json.loads(value).items())) if path == config_path else value
        with patch.object(Path, 'read_text', read), \
             patch.object(hybrid.v3, 'load_words', return_value=(['secret42'], [], {})), \
             self.assertRaises(ValueError):
            batch.evaluate_version([{'ssid': 'Demo', 'password': 'secret42'}], 'v3', 1, 10, workers=1)

    def test_worker_startup_failure_cleans_previously_started_children(self):
        context = batch.mp.get_context('fork')
        started = []
        def process(*args, **kwargs):
            if started:
                raise OSError('startup failed')
            child = context.Process(*args, **kwargs)
            started.append(child)
            return child
        proxy = SimpleNamespace(Pool=context.Pool, Pipe=context.Pipe, Process=process)
        sources = {'raw': ['secret42'], 'words': [], 'provenance': []}
        try:
            with patch.object(batch.mp, 'get_context', return_value=proxy), \
                 patch.object(hybrid, 'load_sources', return_value=sources), self.assertRaises(OSError):
                batch.evaluate_version([{'ssid': '!', 'password': 'secret42'}], 'v4', 1, 10, workers=2)
            self.assertFalse(any(child.is_alive() for child in started))
        finally:
            for child in started:
                if child.is_alive():
                    child.terminate()
                    child.join()

    def test_batch_completion_matches_reference_for_empty_early_phases(self):
        sources = {'raw': [], 'words': [], 'provenance': []}
        rows = [{'ssid': '!', 'password': '00000000'}, {'ssid': 'DemoCafe', 'password': 'DemoCafe1'}]
        reference = hybrid.evaluate(rows, '0.01', 7200, loader=lambda language: sources)
        with patch.object(hybrid, 'load_sources', return_value=sources):
            report, _ = batch.evaluate_version(rows, 'v4', '0.01', 7200, workers=1)
        for got, wanted in zip(report['curve'], reference['curve']):
            self.assertEqual({k: got[k] for k in wanted}, wanted)
    def test_analytic_masks_match_every_reference_candidate(self):
        words = ['the', 'maple', 'harbor', 'ab', 'watermelon']
        values = list(hybrid.rules.filtered(hybrid.word_masks(words, 2)))
        targets = {value: i for i, value in enumerate(values)}
        result = oracles.mask_oracle(words, 2, targets)
        self.assertEqual(result['length'], len(values))
        self.assertEqual(result['hits'], {i: i + 1 for i in range(len(values))})

    def test_mask_oracle_falls_back_on_collisions(self):
        self.assertIsNone(oracles.mask_oracle(['ss', 'ß'], 6, {}))

    def test_batch_matches_reference_for_both_versions(self):
        sources = {'raw': ['password123'], 'words': ['maple', 'harbor'], 'provenance': []}
        config = json.loads((hybrid.v3.ROOT / 'config.json').read_text())
        config.update(raw_limit=2, ssid_rules_limit=4, ssid_context_limit=5,
                      word_rules_limit=6, pair_word_limit=2, budget_per_pair=7200)
        original = Path.read_text
        def read(path, *args, **kwargs):
            return json.dumps(config) if path == hybrid.v3.ROOT / 'config.json' else original(path, *args, **kwargs)
        for version in ('v3', 'v4'):
            if version == 'v4':
                sequence = list(hybrid.candidates({'ssid': 'DemoCafe'}, sources, '1', 7200))
                answers = [sequence[i][2] for i in (0, 10, 50)] + ['unknown-secret42']
            else:
                sequence = list(hybrid.v3.candidates_for_ssid('DemoCafe', config, sources['raw'], sources['words']))
                answers = [sequence[i][1] for i in (0, 10, 50)] + ['unknown-secret42']
            rows = [{'ssid': 'DemoCafe', 'password': value} for value in answers]
            with patch.object(hybrid, 'load_sources', return_value=sources), \
                 patch.object(hybrid.v3, 'load_words', return_value=(sources['raw'], sources['words'], {})), \
                 patch.object(Path, 'read_text', read):
                report, outcomes = batch.evaluate_version(rows, version, '1', 7200, workers=1)
            for phase, p in enumerate(hybrid.plan('1')):
                expected = 0
                for answer in answers:
                    if version == 'v4':
                        expected += any(candidate == answer and index < p['total_candidates'] and stage <= phase
                                        for index, (stage, _, candidate) in enumerate(sequence))
                    else:
                        expected += any(candidate == answer for _, candidate in sequence[:p['total_candidates']])
                self.assertEqual(report['curve'][phase]['matched'], expected, (version, phase))
    def test_index_expansion_matches_reference_with_exhaustion_and_duplicates(self):
        rng = random.Random(84491)
        for _ in range(1000):
            raw = {name: [f'candidate{rng.randrange(30):03}' for _ in range(rng.randrange(50))]
                   for name in ('a', 'b', 'c', 'd')}
            filtered = {name: list(hybrid.rules.filtered(values, window=7)) for name, values in raw.items()}
            ceilings = sorted(rng.sample(range(0, 150), 3))
            phases = [(ceiling, [(name, rng.randrange(1, 5)) for name in raw]) for ceiling in ceilings]
            quantum = rng.randrange(1, 8)
            reference = list(hybrid.schedule({k: iter(v) for k, v in raw.items()}, phases,
                                             batch=quantum, window=7))
            segments, completion, counts = batch.schedule_index({k: len(v) for k, v in filtered.items()},
                                                                phases, batch=quantum)
            expanded = []
            for segment in segments:
                for offset in range(segment['count']):
                    rank = segment['family_start'] + offset
                    expanded.append((batch.global_rank(segment, rank), segment['phase'],
                                     segment['family'], filtered[segment['family']][rank - 1]))
            expanded.sort()
            self.assertEqual([(p, f, v) for _, p, f, v in expanded], reference)
            self.assertEqual(sum(counts.values()), len(reference))
            for phase, state in enumerate(completion):
                self.assertEqual(state['emitted'], sum(p <= phase for p, _, _ in reference))

    def test_first_hit_is_minimum_across_families(self):
        stages = [(12, [('a', 1), ('b', 1)])]
        segments, _, _ = batch.schedule_index({'a': 10, 'b': 10}, stages, batch=1)
        self.assertEqual(batch.first_hit(segments, {'a': 6, 'b': 1}), (0, 2))

    def test_unknown_lengths_fixed_point_matches_known_lengths(self):
        rng = random.Random(4292)
        for _ in range(300):
            truth = {name: rng.randrange(100) for name in ('a', 'b', 'context')}
            known = {'a': None, 'b': None, 'context': truth['context']}
            stages = [(10, [('a', 2), ('context', 1)]),
                      (90, [('a', 1), ('b', 3), ('context', 1)])]
            for iteration in range(4):
                _, _, needed = batch.schedule_index(known, stages, batch=3)
                changes = [name for name in known if known[name] is None and truth[name] < needed[name]]
                if not changes:
                    break
                for name in changes:
                    known[name] = truth[name]
            actual = batch.schedule_index(known, stages, batch=3)
            expected = batch.schedule_index(truth, stages, batch=3)
            self.assertEqual(actual, expected)

    def test_scan_records_only_first_hit_and_detects_short_stream(self):
        scanner = batch.Scanner(iter(['first042', 'target42', 'target42']), {'target42': 0})
        first = scanner.scan(2)
        self.assertEqual(first['hits'], {0: 2})
        self.assertIsNone(first['length'])
        second = scanner.scan(5)
        self.assertEqual(second['length'], 3)
        self.assertEqual(second['hits'], {0: 2})

    def test_v3_serial_index_matches_export_with_small_budget(self):
        config = dict(hybrid.v3.json.loads((hybrid.v3.ROOT / 'config.json').read_text()))
        config.update(budget_per_pair=40, raw_limit=3, ssid_rules_limit=4,
                      ssid_context_limit=5, word_rules_limit=6, pair_word_limit=2)
        raw, words = ['first042', 'second42'], ['maple', 'harbor']
        raw_values, raw_set = hybrid.v3.prepare_raw(raw, config)
        family_values = {name: list(itertools.islice(hybrid.v3.stage_source(name, 'DemoCafe', config,
                                          raw_values, raw_set, words), cap))
                         for name, cap, _ in hybrid.v3.stage_plan(config)}
        lengths = {name: len(values) for name, values in family_values.items()}
        segments, _, _ = batch.serial_index(lengths, hybrid.v3.stage_plan(config), 40)
        expanded = []
        for segment in segments:
            expanded.extend((batch.global_rank(segment, i + 1), segment['family'], value)
                            for i, value in enumerate(family_values[segment['family']][:segment['count']]))
        expanded.sort()
        self.assertEqual([(family, value) for _, family, value in expanded],
                         list(hybrid.v3.candidates_for_ssid('DemoCafe', config, raw, words)))


if __name__ == '__main__':
    unittest.main()
