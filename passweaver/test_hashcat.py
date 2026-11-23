import os
import stat
import tempfile
import textwrap
import unittest
from pathlib import Path

import hashcat


class BenchmarkParseTests(unittest.TestCase):
    def test_sums_device_speeds(self):
        text = '\n'.join([
            '22000:1:0:310000:12.5:...',
            '22000:2:0:290000:13.0:...',
            'something-else',
        ])
        self.assertEqual(hashcat._parse_benchmark(text), 600000)

    def test_zero_when_no_match(self):
        self.assertEqual(hashcat._parse_benchmark('no useful lines'), 0)


def _fake_hashcat(tmp, target):
    """A stand-in hashcat: records a stdin hit in the potfile, replays it on --show."""
    script = Path(tmp) / 'hashcat'
    script.write_text(textwrap.dedent('''\
        #!/usr/bin/env python3
        import sys
        args = sys.argv[1:]
        out = pot = None
        for i, a in enumerate(args):
            if a == "-o":
                out = args[i + 1]
            elif a == "--potfile-path":
                pot = args[i + 1]
        target = {target!r}
        if "--show" in args:
            try:
                data = open(pot).read() if pot else ""
            except FileNotFoundError:
                data = ""
            if out:
                open(out, "w").write(data)
            sys.exit(0)
        hit = None
        for line in sys.stdin:
            if line.rstrip("\\n") == target:
                hit = target
                break
        if hit and pot:
            with open(pot, "a") as fh:
                fh.write(hit + "\\n")
        sys.exit(0 if hit else 1)
    ''').format(target=target))
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    return str(script)


class CrackTests(unittest.TestCase):
    def test_returns_passphrase_when_found(self):
        with tempfile.TemporaryDirectory() as tmp:
            fake = _fake_hashcat(tmp, 'secretpass123')
            pot = Path(tmp) / 'pot'
            keys = hashcat.crack(fake, ['WPA*02*...'],
                                 iter(['a', 'b', 'secretpass123', 'c']), pot)
            self.assertEqual(keys, ['secretpass123'])

    def test_reads_key_already_in_potfile(self):
        with tempfile.TemporaryDirectory() as tmp:
            fake = _fake_hashcat(tmp, 'unused')
            pot = Path(tmp) / 'pot'
            pot.write_text('already-cracked\n')          # pot hit, no stdin match
            keys = hashcat.crack(fake, ['WPA*02*...'], iter(['x']), pot)
            self.assertEqual(keys, ['already-cracked'])

    def test_returns_empty_when_not_found(self):
        with tempfile.TemporaryDirectory() as tmp:
            fake = _fake_hashcat(tmp, 'never-sent')
            pot = Path(tmp) / 'pot'
            keys = hashcat.crack(fake, ['WPA*02*...'], iter(['a', 'b', 'c']), pot)
            self.assertEqual(keys, [])

    def test_missing_binary_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(hashcat.HashcatError):
                hashcat.crack(str(Path(tmp) / 'nope'), ['x'], iter(['a']), Path(tmp) / 'pot')


if __name__ == '__main__':
    unittest.main()
