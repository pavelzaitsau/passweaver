import contextlib
import hashlib
import io
import json
from pathlib import Path
import random
import tempfile
import unittest
from unittest.mock import patch
import uuid

import audit
import engine


class PrivacyFixTests(unittest.TestCase):
    def run_fixture(self):
        raw = ['FixtureA1', 'FixtureB2', 'FixtureC3']
        data = (json.dumps({'ssid': 'ReviewFixture', 'password': raw[1]}) + '\n').encode()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / 'fixture.jsonl'
            source.write_bytes(data)
            with patch.object(engine, 'load_words', return_value=(raw, [], {})), contextlib.redirect_stdout(io.StringIO()) as output:
                status = engine.main(['--input', str(source), '--output', str(root / 'reports')])
            self.assertEqual(status, 0)
            report = json.loads(Path(json.loads(output.getvalue())['report']).read_text())
        return report, data

    def test_report_omits_answer_dependent_work_counters(self):
        report, _ = self.run_fixture()
        self.assertEqual(report['overall']['matched'], 1)
        self.assertNotIn('common_stage_generated_candidates', report)
        self.assertNotIn('results', report)

    def test_report_omits_unkeyed_secret_input_digest(self):
        report, data = self.run_fixture()
        self.assertNotIn('input_sha256', report)
        self.assertNotIn(hashlib.sha256(data).hexdigest(), json.dumps(report))

    def test_input_identifier_is_random_instead_of_content_derived(self):
        first, _ = self.run_fixture()
        second, _ = self.run_fixture()
        self.assertEqual(uuid.UUID(first['input_id']).version, 4)
        self.assertEqual(uuid.UUID(second['input_id']).version, 4)
        self.assertNotEqual(first['input_id'], second['input_id'])


class ValidatorEquivalenceTests(unittest.TestCase):
    def test_validation_matches_independent_byte_and_control_oracle(self):
        rng = random.Random(4087)
        alphabet = 'aA0 !é中🙂\0\r\n\ud800'
        values = [None, 4, b'Fixture42', '', 'a' * 7, 'a' * 8,
                  'a' * 63, 'a' * 64, 'é' * 4, 'é' * 32,
                  ' edge secret ', '$HEX[41424344]']
        values.extend(''.join(rng.choice(alphabet) for _ in range(rng.randrange(70)))
                      for _ in range(10000))
        for value in values:
            if not isinstance(value, str):
                expected = False
            else:
                try:
                    encoded = value.encode('utf-8')
                    expected = 8 <= len(encoded) <= 63 and not any(byte in (0, 10, 13) for byte in encoded)
                except UnicodeEncodeError:
                    expected = False
            self.assertEqual(audit.valid(value), expected)


if __name__ == '__main__':
    unittest.main()
