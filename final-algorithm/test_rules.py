import itertools
import unittest

import rules


class RulesTests(unittest.TestCase):
    def test_shared_rules_include_word_affixes_and_internal_changes(self):
        families = rules.word_families(['harbor'], broad_limit=1)
        values = set(itertools.chain.from_iterable(families))
        self.assertTrue({'harbor42', 'Harbor2001', 'har3bor'} <= values)
        self.assertTrue({'h1a2r3b4o5r6', '1h2a3r4b5o6r'} <= values)

    def test_ssid_context_combines_name_and_independent_dictionary(self):
        values = set(rules.context_candidates('HarborHotel', ['sunset']))
        self.assertIn('HarborSunset', values)

    def test_product_pair_ranking_reaches_frequent_rare_pairs_early(self):
        words = [str(i) for i in range(100)]
        early = list(itertools.islice(rules.ordered_pairs(words, 'product'), 800))
        self.assertIn(('0', '99'), early)

    def test_round_robin_prevents_first_family_from_starving_others(self):
        output = list(itertools.islice(rules.mix([iter(range(100)), iter([999])], 2), 4))
        self.assertEqual(output, [0, 1, 999, 2])

    def test_bounded_filter_rejects_invalid_and_nearby_duplicates(self):
        output = list(rules.filtered(['short', 'harbor42', 'harbor42', 'sunset42'], window=10))
        self.assertEqual(output, ['harbor42', 'sunset42'])


if __name__ == '__main__':
    unittest.main()
