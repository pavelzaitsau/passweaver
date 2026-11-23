import json
import tempfile
import unittest
from pathlib import Path

import report


class ResultTests(unittest.TestCase):
    def test_as_dict_omits_empties(self):
        result = report.Result('Net', 'not-found', sources={'a.pcap'}, seconds=12.0)
        data = result.as_dict()
        self.assertEqual(data['status'], 'not-found')
        self.assertEqual(data['sources'], ['a.pcap'])
        self.assertNotIn('psk', data)
        self.assertEqual(data['seconds'], 12.0)


class CrackedRoundTripTests(unittest.TestCase):
    def test_write_then_load(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'cracked.txt'
            results = [
                report.Result('Home', 'cracked', psk='hunter2hunter'),
                report.Result('Empty', 'not-found'),
            ]
            report.write_cracked(path, results)
            loaded = report.load_cracked(path)
            self.assertEqual(loaded, {'Home': 'hunter2hunter'})

    def test_load_missing_file(self):
        self.assertEqual(report.load_cracked('/no/such/file'), {})


class ReportFileTests(unittest.TestCase):
    def test_write_report_structure(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'report.json'
            report.write_report(
                path, {'engine': 'v5.1'},
                [report.Result('Home', 'cracked', psk='pw', sources={'a.pcap'})],
                [(Path('bad.pcap'), 'no handshake found')])
            doc = json.loads(path.read_text())
            self.assertEqual(doc['meta']['engine'], 'v5.1')
            self.assertEqual(doc['networks'][0]['psk'], 'pw')
            self.assertEqual(doc['skipped_files'][0]['reason'], 'no handshake found')


class SummaryTests(unittest.TestCase):
    def test_counts_and_lists_cracked(self):
        results = [
            report.Result('Home', 'cracked', psk='pw'),
            report.Result('Guest', 'not-found'),
        ]
        text = report.summary(results, [(Path('bad.pcap'), 'no handshake found')])
        self.assertIn('1 cracked', text)
        self.assertIn('Home\tpw', text)
        self.assertIn('bad.pcap', text)


if __name__ == '__main__':
    unittest.main()
