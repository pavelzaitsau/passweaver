import json
import contextlib
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import hybrid


class IndependentReviewTests(unittest.TestCase):
    def test_floor_uses_exact_decimal_product(self):
        self.assertEqual(hybrid.plan('0.099999999999999999999999999999')[0]['total_candidates'], 0)
    def test_jsonl_unicode_line_separator_is_not_a_record_separator(self):
        with tempfile.TemporaryDirectory() as folder:
            source, output = Path(folder) / 'input.jsonl', Path(folder) / 'report.json'
            source.write_text(json.dumps({'ssid': 'Demo\u2028Cafe', 'password': 'secret42'}, ensure_ascii=False) + '\n')
            sources = {'raw': ['secret42'], 'words': [], 'provenance': []}
            with patch.object(hybrid, 'load_sources', return_value=sources), contextlib.redirect_stdout(io.StringIO()):
                code = hybrid.main(['evaluate', '--input', str(source), '--output', str(output),
                                    '--rate', '1', '--until', '10'])
            self.assertEqual(code, 0)
    def test_empty_early_stream_reports_exhaustion(self):
        sources = {'raw': [], 'words': [], 'provenance': []}
        result = hybrid.evaluate([{'ssid': '!', 'password': 'secret42'}], 1, 10,
                                 loader=lambda language: sources)
        self.assertEqual(result['curve'][0]['source_exhausted'], 1)
        self.assertEqual(result['curve'][0]['budget_reached'], 0)

    def test_late_family_hit_is_not_counted_at_earlier_empty_checkpoint(self):
        sources = {'raw': [], 'words': [], 'provenance': []}
        result = hybrid.evaluate([{'ssid': '!', 'password': '00000000'}], 1, 7200,
                                 loader=lambda language: sources)
        self.assertEqual([x['matched'] for x in result['curve']], [0, 0, 0, 0, 0, 1, 1, 1])

    def test_export_chmod_failure_removes_new_file(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'out.txt'
            with patch.object(hybrid.os, 'fchmod', side_effect=OSError('chmod failed')):
                with self.assertRaises(OSError):
                    hybrid.export(path, {'ssid': 'DemoCafe'},
                                  {'raw': ['password123'], 'words': [], 'provenance': []}, 1, 10, 1)
            self.assertFalse(path.exists())

    def test_export_close_failure_removes_new_file(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'out.txt'
            original = Path.open
            class BadClose:
                def __init__(self, stream):
                    self.stream = stream
                def __enter__(self):
                    return self.stream
                def __exit__(self, *args):
                    self.stream.close()
                    raise OSError('close failed')
            def opened(target, *args, **kwargs):
                stream = original(target, *args, **kwargs)
                return BadClose(stream) if target == path else stream
            with patch.object(Path, 'open', opened), self.assertRaises(OSError):
                hybrid.export(path, {'ssid': 'DemoCafe'},
                              {'raw': ['password123'], 'words': [], 'provenance': []}, 1, 10, 1)
            self.assertFalse(path.exists())

    def test_json_failure_cleans_partial_without_overwriting_existing(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'report.json'
            with patch.object(hybrid.os, 'fchmod', side_effect=OSError('chmod failed')):
                with self.assertRaises(OSError):
                    hybrid.write_json_exclusive(path, {'ok': True})
            self.assertFalse(path.exists())
            path.write_bytes(b'preserve')
            with self.assertRaises(FileExistsError):
                hybrid.write_json_exclusive(path, {'ok': True})
            self.assertEqual(path.read_bytes(), b'preserve')

    def test_duplicate_source_id_is_rejected(self):
        original = Path.read_text
        manifest_path = hybrid.ROOT / 'wordlists/manifest.json'
        def read(path, *args, **kwargs):
            value = original(path, *args, **kwargs)
            if path == manifest_path:
                data = json.loads(value)
                data['sources'].append(data['sources'][0])
                return json.dumps(data)
            return value
        with patch.object(Path, 'read_text', read), self.assertRaises(ValueError):
            hybrid.load_sources('en')
