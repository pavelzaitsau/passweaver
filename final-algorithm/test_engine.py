import json
import unittest
from unittest.mock import patch

import engine


class EvaluationTests(unittest.TestCase):
    def test_version_snapshot_resolves_wordlists_from_lab_root(self):
        raw, words, manifest = engine.load_words()
        self.assertGreater(len(raw), 100000)
        self.assertGreater(len(words), 50000)
        self.assertEqual(len(manifest['sources']), 2)

    def test_shared_stage_counts_each_network_against_its_remaining_budget(self):
        results = [{'matched':False, 'attempts':3}, {'matched':False, 'attempts':1}]
        engine.consume(results, ['harbor42', 'harbor42'], iter(['sunset42', 'harbor42']), 10, 4, 'words')
        self.assertFalse(results[0]['matched'])
        self.assertEqual(results[0]['attempts'], 4)
        self.assertTrue(results[1]['matched'])
        self.assertEqual(results[1]['attempts'], 3)

    def test_report_rows_do_not_contain_passwords(self):
        results = [{'matched':False, 'attempts':0}]
        secret = 'SENTINEL_secret_42'
        engine.consume(results, [secret], iter([secret]), 1, 1, 'words')
        self.assertTrue(results[0]['matched'])
        self.assertNotIn(secret, json.dumps(results))

    def test_finite_stream_charges_only_attempts_actually_generated(self):
        results = [{'matched':False, 'attempts':2}]
        engine.consume(results, ['unmatched42'], iter(['harbor42']), 20, 20, 'words')
        self.assertEqual(results[0]['attempts'], 3)

    def test_combined_stages_share_one_budget(self):
        config = {'version':'fixture', 'budget_per_pair':4, 'raw_limit':1, 'ssid_rules_limit':1,
                  'ssid_context_limit':1, 'context_word_limit':1, 'ssid_expanded_limit':1,
                  'broad_word_limit':1, 'family_batch':0, 'word_rules_limit':5,
                  'pair_word_limit':1, 'pair_ordering':'sum', 'assumed_checks_per_second':1}
        rows = [{'line':1, 'ssid':'fixture', 'group':'new', 'password':'target42'}]
        with patch.object(engine, 'ssid_stream', return_value=iter(['second42'])), \
             patch.object(engine.rules, 'context_candidates', return_value=iter(['third042'])), \
             patch.object(engine.rules, 'word_families', return_value=iter([iter(['fourth42','target42'])])):
            results, work = engine.evaluate(rows, config, ['first042'], ['fixture'])
        self.assertFalse(results[0]['matched'])
        self.assertEqual(results[0]['attempts'], 4)
        self.assertEqual(work['word_pairs'], 0)


if __name__ == '__main__':
    unittest.main()
