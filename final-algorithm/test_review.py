import contextlib
import io
import hashlib
import json
import random
import unittest
from unittest.mock import patch

import audit
import engine


class RegressionTests(unittest.TestCase):
    def config(self, **updates):
        config = json.loads((engine.ROOT / 'config.json').read_text())
        config.update(updates)
        return config

    def test_unchecked_raw_value_can_match_in_later_stage(self):
        config = self.config(budget_per_pair=5, raw_limit=1, ssid_rules_limit=0,
                             ssid_context_limit=0, word_rules_limit=4)
        rows = [{'line': 1, 'ssid': 'Fixture', 'group': 'new', 'password': 'target42'}]
        with patch.object(engine.rules, 'word_families', return_value=iter([iter(['target42'])])), contextlib.redirect_stdout(io.StringIO()):
            result, _ = engine.evaluate(rows, config, ['first042', 'target42'], [])
        self.assertTrue(result[0]['matched'])
        self.assertEqual(result[0]['attempts'], 2)

    def test_line_candidates_reject_record_breaks_and_null(self):
        for value in ('null\0value', 'line\nvalue', 'line\rvalue'):
            with self.subTest(value=repr(value)):
                self.assertFalse(audit.valid(value))
        self.assertTrue(audit.valid(' edge secret '))
        self.assertTrue(audit.valid('é' * 4))
        self.assertFalse(audit.valid('é' * 32))

    def test_jsonl_preserves_spaces_slashes_and_case(self):
        record = {'ssid': ' /Fixture ', 'password': ' edge/secret ', 'group': 'new'}
        rows = engine.parse_input((json.dumps(record) + '\n').encode(), 'jsonl')
        self.assertEqual(rows[0]['ssid'], record['ssid'])
        self.assertEqual(rows[0]['password'], record['password'])

    def test_invalid_jsonl_records_are_rejected(self):
        records = [[], {'ssid': 'é' * 17, 'password': 'secret42'},
                   {'ssid': 'Fixture', 'password': 'bad\nsecret'},
                   {'ssid': 'Fixture', 'password': 'secret42', 'group': 'unexpected'},
                   {'ssid': 'Fixture', 'password': 'secret42', 'answer_hint': 'secret42'}]
        for record in records:
            with self.subTest(record=record), self.assertRaises(ValueError):
                engine.parse_input(json.dumps(record).encode(), 'jsonl')

    def test_empty_finite_generators_do_not_charge_full_budget(self):
        config = self.config(raw_limit=0, ssid_rules_limit=0, ssid_context_limit=0, word_rules_limit=0)
        rows = [{'line': 1, 'ssid': 'Fixture', 'group': 'new', 'password': 'secret42'}]
        results, _ = engine.evaluate(rows, config, [], [])
        self.assertEqual(results[0]['attempts'], 0)
        self.assertFalse(results[0]['matched'])

    def test_legacy_text_preserves_spaces_and_rejects_ambiguous_separator(self):
        rows = engine.parse_input(b' Fixture / edge secret \n', 'text')
        self.assertEqual(rows[0]['ssid'], ' Fixture ')
        self.assertEqual(rows[0]['password'], ' edge secret ')
        with self.assertRaises(ValueError):
            engine.parse_input(b'Fixture/part/secret42\n', 'text')

    def test_legacy_display_separators_require_explicit_lossy_format(self):
        row = engine.parse_input(b'Fixture / secret42\n', 'legacy-text')[0]
        self.assertEqual((row['ssid'], row['password']), ('Fixture', 'secret42'))
        row = engine.parse_input(b'Fixture / secret42\n', 'text')[0]
        self.assertEqual((row['ssid'], row['password']), ('Fixture ', ' secret42'))

    def test_invalid_configuration_fails_before_generation(self):
        for updates in ({'budget_per_pair': -1}, {'raw_limit': -1},
                        {'assumed_checks_per_second': 0}, {'family_batch': -1},
                        {'pair_ordering': 'typo'}, {'raw_limit': True},
                        {'version': '../../elsewhere'}, {'unexpected': 'value'}):
            with self.subTest(updates=updates), self.assertRaises(ValueError):
                engine.validate_config(self.config(**updates))

    def test_default_is_accepted_v3_and_rollback_retains_v2_order(self):
        config = self.config()
        self.assertEqual((config['version'], config['family_batch'], config['pair_word_limit'], config['pair_ordering']),
                         ('v3-reviewed', 10000, 50000, 'product'))
        self.assertEqual((config['budget_per_pair'], config['assumed_checks_per_second']), (71400000, 235000))
        rollback = json.loads((engine.ROOT / 'profiles/v2-rollback.json').read_text())
        engine.validate_config(rollback)
        self.assertEqual((rollback['family_batch'], rollback['pair_word_limit'], rollback['pair_ordering']),
                         (0, 10000, 'sum'))

    def test_reviewed_stream_matches_independent_archived_golden_sequences(self):
        fixture = json.loads((engine.ROOT / 'fixtures/legacy-golden.json').read_text())
        for case in fixture['cases']:
            with self.subTest(profile=case['original_profile'], ssid=case['ssid']):
                h = hashlib.sha256()
                count = 0
                for stage, candidate in engine.candidates_for_ssid(case['ssid'], case['config'], fixture['raw'], fixture['words']):
                    h.update((stage + '\0' + candidate + '\n').encode())
                    count += 1
                self.assertEqual(count, case['count'])
                self.assertEqual(h.hexdigest(), case['stage_and_candidate_sha256'])

    def test_small_export_has_same_ranks_as_evaluation(self):
        config = self.config(budget_per_pair=12, raw_limit=3, ssid_rules_limit=3,
                             ssid_context_limit=2, context_word_limit=1,
                             word_rules_limit=2, pair_word_limit=1)
        raw, words = ['first042', 'second42', 'third042'], ['harbor']
        candidates = list(engine.candidates_for_ssid('Fixture42', config, raw, words))
        self.assertEqual(len(candidates), 12)
        for rank, (_, candidate) in enumerate(candidates, 1):
            rows = [{'line': 1, 'ssid': 'Fixture42', 'group': 'new', 'password': candidate}]
            with contextlib.redirect_stdout(io.StringIO()):
                result, _ = engine.evaluate(rows, config, raw, words)
            expected = next(i for i, (_, value) in enumerate(candidates, 1) if value == candidate)
            self.assertTrue(result[0]['matched'], rank)
            self.assertEqual(result[0]['attempts'], expected)

    def test_shared_consumer_matches_independent_oracle(self):
        rng = random.Random(9321)
        pool = ['Fixture' + str(i) for i in range(8)]
        for _ in range(150):
            budget, cap = rng.randrange(1, 12), rng.randrange(0, 12)
            offsets = [rng.randrange(budget + 1) for _ in range(4)]
            passwords = rng.choices(pool, k=4)
            stream = rng.choices(pool, k=rng.randrange(15))
            rows = [{'matched': False, 'attempts': value} for value in offsets]
            engine.consume(rows, passwords, iter(stream), cap, budget, 'dictionary_raw')
            for row, offset, password in zip(rows, offsets, passwords):
                allowed = stream[:min(cap, budget - offset)]
                match = password in allowed
                attempts = offset + (allowed.index(password) + 1 if match else len(allowed))
                self.assertEqual((row['matched'], row['attempts']), (match, attempts))


if __name__ == '__main__':
    unittest.main()
