import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

from test_teleport import verify


@unittest.skipUnless(all(os.environ.get(key) for key in (
    'WFM_SD_CAPTURE_MANIFEST', 'WFM_TELEPORT_HASH', 'WFM_TELEPORT_POTFILE')),
    'Set local SD manifest and TELEPORT control paths for capture regression tests')
class SdCaptureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = json.loads(Path(os.environ['WFM_SD_CAPTURE_MANIFEST']).read_text())
        cls.captures = cls.manifest['captures']
        line = Path(os.environ['WFM_TELEPORT_HASH']).read_text().strip()
        cls.ssid = bytes.fromhex(line.split('*')[5])
        secret = Path(os.environ['WFM_TELEPORT_POTFILE']).read_bytes().strip().rsplit(b':', 1)[1]
        if secret.startswith(b'$HEX['):
            secret = bytes.fromhex(secret[5:-1].decode())
        cls.secret = secret

    def test_copied_capture_integrity_and_readability(self):
        self.assertTrue(self.captures)
        for row in self.captures:
            with self.subTest(file=row['filename']):
                path = Path(row['copied_to'])
                self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), row['sha256'])
                process = subprocess.run(['capinfos', '-c', str(path)], capture_output=True, timeout=30)
                self.assertEqual(process.returncode, 0)

    def test_eapol_and_conversion_positive_and_negative_cases(self):
        for row in self.captures:
            with self.subTest(file=row['filename']), tempfile.TemporaryDirectory() as temporary:
                path = Path(row['copied_to'])
                frames = subprocess.run(['tshark', '-r', str(path), '-Y', 'eapol',
                                         '-T', 'fields', '-e', 'frame.number'], capture_output=True, timeout=30)
                self.assertEqual(frames.returncode, 0)
                self.assertEqual(len(frames.stdout.splitlines()), row['eapol_frames'])
                output = Path(temporary) / 'converted.22000'
                process = subprocess.run(['hcxpcapngtool', '-o', str(output), str(path)],
                                         capture_output=True, timeout=30)
                self.assertEqual(process.returncode, 0)
                lines = output.read_text().splitlines() if output.exists() else []
                self.assertEqual(len(lines), row['converted_hash_records'])
                teleport = [line for line in lines if bytes.fromhex(line.split('*')[5]) == self.ssid]
                self.assertEqual(len(teleport), row['teleport_hash_records'])

    def test_eligible_teleport_records_accept_known_answer_and_reject_wrong_answer(self):
        eligible = [row for row in self.captures if row.get('eligible_for_teleport_regression')]
        self.assertTrue(eligible)
        for row in eligible:
            path = Path(row['teleport_hash_file'])
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), row['teleport_hash_file_sha256'])
            for line in path.read_text().splitlines():
                with self.subTest(file=row['filename']):
                    self.assertTrue(verify(line, self.secret.decode()))
                    self.assertFalse(verify(line, 'qa-wrong-unrelated-value'))
                    for password, expected in ((self.secret, True), (b'qa-wrong-unrelated-value', False)):
                        process = subprocess.run(['hcxpmktool', '-l', line, '-p', '-'],
                                                 input=password + b'\n', capture_output=True, timeout=30)
                        self.assertEqual(b'(confirmed)' in process.stdout, expected)

    def test_declared_complete_exchange_has_matching_client_and_replay_counters(self):
        complete = [row for row in self.captures
                    if all(row.get('first_frame_per_message', {}).get(str(n)) for n in range(1, 5))]
        if not complete:
            self.skipTest('This historical manifest declares no complete M1-M4 exchange')
        for capture in complete:
            with self.subTest(file=capture['copied_to']):
                args = ['tshark', '-r', capture['copied_to'], '-Y', 'eapol', '-T', 'fields']
                for field in ('frame.number', 'wlan_rsna_eapol.keydes.msgnr',
                              'eapol.keydes.replay_counter', 'wlan.ta', 'wlan.ra'):
                    args.extend(['-e', field])
                process = subprocess.run(args, capture_output=True, text=True, timeout=30)
                self.assertEqual(process.returncode, 0)
                rows = {int(row[0]): row for row in
                        (line.split('\t') for line in process.stdout.splitlines())}
                exchange = {n: rows[capture['first_frame_per_message'][str(n)]] for n in range(1, 5)}
                self.assertEqual([exchange[n][1] for n in range(1, 5)], ['1', '2', '3', '4'])
                ap, client = exchange[1][3:5]
                for n in (1, 3):
                    self.assertTrue(exchange[n][3:5] == [ap, client])
                for n in (2, 4):
                    self.assertTrue(exchange[n][3:5] == [client, ap])
                self.assertTrue(exchange[1][2] == exchange[2][2])
                self.assertTrue(exchange[3][2] == exchange[4][2])


if __name__ == '__main__':
    unittest.main()
