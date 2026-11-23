import unittest
from pathlib import Path

import extract


def _line(essid_hex, bssid='aabbccddeeff', typ='02'):
    return 'WPA*{}*deadbeef*{}*112233445566*{}*extra'.format(typ, bssid, essid_hex)


class ParseLineTests(unittest.TestCase):
    def test_decodes_ascii_essid(self):
        essid, bssid, reason = extract.parse_line(_line('436f66666565'))  # 'Coffee'
        self.assertEqual(essid, 'Coffee')
        self.assertEqual(bssid, 'aabbccddeeff')
        self.assertIsNone(reason)

    def test_hidden_essid(self):
        essid, _, reason = extract.parse_line(_line(''))
        self.assertIsNone(essid)
        self.assertEqual(reason, 'no ESSID (hidden)')

    def test_non_decodable_essid(self):
        essid, _, reason = extract.parse_line(_line('fffe'))
        self.assertIsNone(essid)
        self.assertEqual(reason, 'non-decodable ESSID')

    def test_malformed(self):
        essid, _, reason = extract.parse_line('garbage*line')
        self.assertIsNone(essid)
        self.assertEqual(reason, 'malformed line')

    def test_utf8_essid(self):
        essid, _, reason = extract.parse_line(_line('436166c3a9'))  # 'Café' in UTF-8
        self.assertEqual(essid, 'Café')
        self.assertIsNone(reason)


class CollectTests(unittest.TestCase):
    def test_merges_networks_across_captures(self):
        fake = {
            Path('one.pcap'): ([_line('436f66666565', bssid='aa0000000001')], None),  # Coffee
            Path('two.pcap'): ([_line('436f66666565', bssid='aa0000000002'),          # Coffee again
                                _line('486f6d65')], None),                             # Home
            Path('bad.pcap'): ([], 'no handshake found'),
        }
        original = extract.run_hcx
        extract.run_hcx = lambda hcx, cap, workdir, tag: fake[cap]
        try:
            networks, skipped = extract.collect('hcx', list(fake), jobs=1)
        finally:
            extract.run_hcx = original
        self.assertEqual(set(networks), {'Coffee', 'Home'})
        self.assertEqual(networks['Coffee'].sources, {'one.pcap', 'two.pcap'})
        self.assertEqual(len(networks['Coffee'].bssids), 2)
        self.assertEqual(len(networks['Coffee'].lines), 2)
        self.assertEqual(skipped, [(Path('bad.pcap'), 'no handshake found')])

    def test_capture_with_only_hidden_is_skipped(self):
        fake = {Path('hidden.pcap'): ([_line('')], None)}
        original = extract.run_hcx
        extract.run_hcx = lambda hcx, cap, workdir, tag: fake[cap]
        try:
            networks, skipped = extract.collect('hcx', list(fake), jobs=1)
        finally:
            extract.run_hcx = original
        self.assertEqual(networks, {})
        self.assertEqual(len(skipped), 1)
        self.assertEqual(skipped[0][1], 'no ESSID (hidden)')


if __name__ == '__main__':
    unittest.main()
