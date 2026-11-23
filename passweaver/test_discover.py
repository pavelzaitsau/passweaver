import tempfile
import unittest
from pathlib import Path

import discover


class DiscoverTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        for name in ('a.pcap', 'b.PCAPNG', 'c.cap', 'd.txt'):
            (self.root / name).write_text('x')
        (self.root / 'sub').mkdir()
        (self.root / 'sub' / 'e.pcap').write_text('x')

    def tearDown(self):
        self._tmp.cleanup()

    def test_directory_walked_recursively_and_filtered(self):
        paths, missing = discover.resolve([str(self.root)])
        names = sorted(p.name for p in paths)
        self.assertEqual(names, ['a.pcap', 'b.PCAPNG', 'c.cap', 'e.pcap'])
        self.assertEqual(missing, [])

    def test_glob_string(self):
        paths, missing = discover.resolve([str(self.root / '*.pcap')])
        self.assertEqual([p.name for p in paths], ['a.pcap'])
        self.assertEqual(missing, [])

    def test_explicit_file_takes_any_suffix(self):
        paths, _ = discover.resolve([str(self.root / 'd.txt')])
        self.assertEqual([p.name for p in paths], ['d.txt'])

    def test_missing_pattern_reported(self):
        paths, missing = discover.resolve([str(self.root / 'none-*.pcap')])
        self.assertEqual(paths, [])
        self.assertEqual(missing, [str(self.root / 'none-*.pcap')])

    def test_dedupes_overlapping_inputs(self):
        paths, _ = discover.resolve([str(self.root), str(self.root / 'a.pcap')])
        self.assertEqual(sum(p.name == 'a.pcap' for p in paths), 1)


if __name__ == '__main__':
    unittest.main()
