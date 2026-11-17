import contextlib
import io
import json
from pathlib import Path
import stat
import shutil
import tempfile
import unittest
from unittest.mock import patch

import engine
import generate


class CliTests(unittest.TestCase):
    def config(self):
        config = json.loads((engine.ROOT / 'config.json').read_text())
        config.update(budget_per_pair=8, raw_limit=8, ssid_rules_limit=0,
                      ssid_context_limit=0, word_rules_limit=0)
        return config

    def test_offline_cli_needs_no_historical_report_and_omits_private_ranks(self):
        sentinel = 'PRIVATE_SENTINEL_PASSWORD'
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / 'fixture.jsonl'
            source.write_text(json.dumps({'ssid': 'PRIVATE_NETWORK', 'password': sentinel}) + '\n')
            config = root / 'config.json'
            config.write_text(json.dumps(self.config()))
            output = io.StringIO()
            with patch.object(engine, 'load_words', return_value=([sentinel], [], {})), contextlib.redirect_stdout(output):
                code = engine.main(['--input', str(source), '--config', str(config), '--output', str(root / 'reports')])
            self.assertEqual(code, 0)
            response = json.loads(output.getvalue())
            report_path = Path(response['report'])
            report = report_path.read_text()
            self.assertNotIn(sentinel, report + output.getvalue())
            self.assertNotIn('PRIVATE_NETWORK', report + output.getvalue())
            self.assertNotIn('results', json.loads(report))
            self.assertEqual(json.loads(report)['overall']['matched'], 1)
            self.assertEqual(stat.S_IMODE(report_path.stat().st_mode), 0o600)
            self.assertEqual(stat.S_IMODE(report_path.parent.stat().st_mode), 0o700)

    def test_input_change_prevents_report(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / 'fixture.jsonl'
            source.write_text('{"ssid":"Fixture","password":"secret42"}\n')
            def mutate(*args):
                source.write_text('changed')
                return [], {}
            with patch.object(engine, 'evaluate', side_effect=mutate), contextlib.redirect_stdout(io.StringIO()) as output:
                code = engine.main(['--input', str(source), '--output', str(root / 'reports')])
            self.assertEqual(code, 1)
            self.assertEqual(json.loads(output.getvalue())['code'], 'input_changed')
            self.assertFalse((root / 'reports').exists())

    def test_bad_input_error_never_echoes_secret_or_traceback(self):
        sentinel = 'PRIVATE_SENTINEL_PASSWORD'
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / 'bad.jsonl'
            source.write_text('{"password": "' + sentinel)
            with contextlib.redirect_stdout(io.StringIO()) as output, contextlib.redirect_stderr(io.StringIO()) as errors:
                code = engine.main(['--input', str(source)])
            self.assertEqual(code, 1)
            self.assertNotIn(sentinel, output.getvalue() + errors.getvalue())
            self.assertNotIn('Traceback', output.getvalue() + errors.getvalue())

    def test_export_preserves_literal_bytes_and_refuses_overwrite(self):
        values = [' edge secret ', '$HEX[41424344]', 'é' * 4]
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'candidates.txt'
            info = generate.export_candidates(path, 'Fixture', self.config(), values, [], 3)
            self.assertEqual(path.read_bytes(), ''.join(value + '\n' for value in values).encode('utf-8'))
            self.assertEqual(info['candidates'], 3)
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
            with self.assertRaises(FileExistsError):
                generate.export_candidates(path, 'Fixture', self.config(), values, [], 3)

    def test_export_failure_removes_partial_file(self):
        def broken(*args):
            yield 'dictionary_raw', 'first042'
            raise OSError('failure')
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'candidates.txt'
            with patch.object(engine, 'candidates_for_ssid', side_effect=broken), self.assertRaises(OSError):
                generate.export_candidates(path, 'Fixture', self.config(), [], [], 3)
            self.assertFalse(path.exists())

    def test_export_rejects_symlink_and_preserves_existing_target(self):
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / 'target.txt'
            target.write_text('unchanged')
            link = Path(temporary) / 'link.txt'
            link.symlink_to(target)
            with self.assertRaises(FileExistsError):
                generate.export_candidates(link, 'Fixture', self.config(), ['first042'], [], 1)
            self.assertEqual(target.read_text(), 'unchanged')

    def test_wordlist_mutation_fails_checksum_before_evaluation(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            shutil.copytree(engine.ROOT / 'wordlists', root / 'wordlists')
            path = root / 'wordlists/ncsc-common-100k.txt'
            path.write_bytes(path.read_bytes() + b'changed42\n')
            with patch.object(engine, 'LAB', root), self.assertRaises(ValueError):
                engine.load_words()

    def test_unexpected_internal_error_is_redacted(self):
        sentinel = 'PRIVATE_SENTINEL_PASSWORD'
        with patch.object(engine, 'load_words', side_effect=RuntimeError(sentinel)), contextlib.redirect_stdout(io.StringIO()) as output:
            code = engine.main(['--input', 'unused.jsonl'])
        self.assertEqual(code, 1)
        self.assertNotIn(sentinel, output.getvalue())
        self.assertEqual(json.loads(output.getvalue())['code'], 'wordlist_invalid')


if __name__ == '__main__':
    unittest.main()
