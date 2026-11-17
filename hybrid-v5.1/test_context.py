import itertools
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import v5


class ContextTests(unittest.TestCase):
    def test_cli_passes_country_venue_and_address(self):
        with tempfile.TemporaryDirectory() as folder:
            argv = ['v5.py', '--ssid', 'DemoCafe', '--country', 'PL', '--venue', 'HarborCafe',
                    '--address', 'Maple Street', '--rate', '1', '--until', '10',
                    '--output', str(Path(folder) / 'out.txt')]
            with patch.object(v5.sys, 'argv', argv), patch.object(v5, 'candidates', return_value=(x for x in ())) as generate:
                self.assertEqual(v5.main(), 0)
            self.assertEqual(generate.call_args.args[0],
                             dict(ssid='DemoCafe', country='PL', venue='HarborCafe', address='Maple Street'))

    def test_country_selects_local_dictionary_only_after_prefix(self):
        def base(*args):
            return ((None, 'BaseValue%05d' % i) for i in range(3000))
        with patch.object(v5.v3, 'load_words', return_value=([], [], {})), \
             patch.object(v5.v3, 'candidates_for_ssid', side_effect=base), \
             patch.object(v5.hybrid, 'load_sources', return_value={'words': [], 'raw': []}) as load, \
             patch.object(v5, 'prince_stream', return_value=iter(())):
            early = list(v5.candidates(dict(ssid='DemoCafe', country='PL'), 1, 600))
            load.assert_not_called()
            late = list(v5.candidates(dict(ssid='DemoCafe', country='PL'), 1, 1800))
            load.assert_called_once_with('pl')
        self.assertEqual(early, late[:600])

    def test_venue_and_address_change_late_candidates_preserve_prefix(self):
        def run(context):
            with patch.object(v5.v3, 'load_words', return_value=([], [], {})), \
                 patch.object(v5.v3, 'candidates_for_ssid', side_effect=lambda *args:
                              ((None, 'BaseValue%05d' % i) for i in range(3000))), \
                 patch.object(v5.hybrid, 'load_sources', return_value={'words': ['garden'], 'raw': []}), \
                 patch.object(v5, 'prince_stream', return_value=iter(())):
                return list(v5.candidates(context, 1, 1800))
        plain = run(dict(ssid='DemoCafe'))
        venue = run(dict(ssid='DemoCafe', venue='HarborCafe'))
        address = run(dict(ssid='DemoCafe', address='MapleStreet'))
        self.assertEqual(plain[:600], venue[:600])
        self.assertEqual(plain[:600], address[:600])
        self.assertTrue(plain[600:] != venue[600:])
        self.assertTrue(plain[600:] != address[600:])
        self.assertTrue(any('HarborCafe' in value for _, _, value in venue[600:]))
        self.assertTrue(any('MapleStreet' in value for _, _, value in address[600:]))


if __name__ == '__main__':
    unittest.main()
