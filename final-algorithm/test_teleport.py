import hashlib
import hmac
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


def verify(line, secret, raw_pmk=False):
    parts = line.split('*')
    if len(parts) != 9 or parts[0] != 'WPA':
        raise ValueError('Invalid WPA record')
    expected, ap, station, ssid = [bytes.fromhex(value) for value in parts[2:6]]
    pmk = bytes.fromhex(secret) if raw_pmk else hashlib.pbkdf2_hmac('sha1', secret.encode(), ssid, 4096, 32)
    if parts[1] == '01':
        calculated = hmac.new(pmk, b'PMK Name' + ap + station, hashlib.sha1).digest()[:16]
    elif parts[1] == '02':
        nonce = bytes.fromhex(parts[6])
        eapol = bytearray.fromhex(parts[7])
        key_version = int.from_bytes(eapol[5:7], 'big') & 7
        other_nonce = bytes(eapol[17:49])
        addresses = min(ap, station) + max(ap, station)
        nonces = min(nonce, other_nonce) + max(nonce, other_nonce)
        label = b'Pairwise key expansion\x00' + addresses + nonces
        ptk = b''.join(hmac.new(pmk, label + bytes([i]), hashlib.sha1).digest() for i in range(4))[:64]
        eapol[81:97] = b'\x00' * 16
        if key_version == 1:
            calculated = hmac.new(ptk[:16], eapol, hashlib.md5).digest()
        elif key_version == 2:
            calculated = hmac.new(ptk[:16], eapol, hashlib.sha1).digest()[:16]
        else:
            raise ValueError('Unsupported key version for independent audit')
    else:
        raise ValueError('Unknown WPA type')
    return hmac.compare_digest(expected, calculated)

@unittest.skipUnless(all(os.environ.get(key) for key in (
    'WFM_TELEPORT_PCAP', 'WFM_TELEPORT_HASH', 'WFM_TELEPORT_POTFILE')),
    'Set the three WFM_TELEPORT paths for the explicit local integration test')
class TeleportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pcap = Path(os.environ['WFM_TELEPORT_PCAP'])
        cls.line = Path(os.environ['WFM_TELEPORT_HASH']).read_text().strip()
        secret = Path(os.environ['WFM_TELEPORT_POTFILE']).read_bytes().strip().rsplit(b':', 1)[1]
        if secret.startswith(b'$HEX['):
            secret = bytes.fromhex(secret[5:-1].decode())
        cls.secret = secret.decode('utf-8')

    def test_existing_capture_reproduces_control_hash(self):
        self.assertEqual(hashlib.sha256(self.pcap.read_bytes()).hexdigest(),
                         'f311a707cbf60029e6747c1982f21ee03bfedf16fa5f10bd42f4c474ec4b1902')
        converter = shutil.which('hcxpcapngtool')
        self.assertIsNotNone(converter)
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / 'converted.22000'
            result = subprocess.run([converter, '-o', str(output), str(self.pcap)], capture_output=True, timeout=30)
            self.assertEqual(result.returncode, 0)
            self.assertTrue(self.line in output.read_text().splitlines())

    def test_known_answer_and_wrong_answer_with_independent_mic(self):
        self.assertTrue(verify(self.line, self.secret))
        self.assertFalse(verify(self.line, 'qa-wrong-unrelated-value'))


if __name__ == '__main__':
    unittest.main()
