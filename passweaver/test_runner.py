import json
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path
from unittest import mock

import deps
import discover
import extract
import hashcat
import runner
import v51engine


def make_network(essid):
    net = extract.Network(essid)
    net.add('LINE:' + essid, 'aabbccddeeff', essid.lower() + '.pcap')
    return net


def make_args(outdir, **over):
    base = dict(files=['x'], time='std', version='v5.1', rate=50000, lang=None,
                venue=None, address=None, jobs=1, outdir=str(outdir), max_total=None,
                workload=3, keep=False, fresh=False, list=False, dry_run=False,
                yes=True, interactive=True)
    base.update(over)
    return Namespace(**base)


def _candidates(*_a, **_k):
    return (c for c in ['a', 'b', 'c'])


def _crack(_bin, lines, candidates, _pot, workload=3, runtime=None, on_proc=None):
    close = getattr(candidates, 'close', None)
    if close:
        close()
    essid = lines[0].split(':', 1)[1]
    return ['homepass123'] if essid == 'Home' else []


class RunnerTests(unittest.TestCase):
    def setUp(self):
        self.networks = {'Home': make_network('Home'), 'Guest': make_network('Guest')}
        self.out = []
        self._patchers = [
            mock.patch.object(deps, 'find_hcx', lambda: 'hcx'),
            mock.patch.object(deps, 'find_hashcat', lambda: 'hashcat'),
            mock.patch.object(discover, 'resolve', lambda files: ([Path('cap.pcap')], [])),
            mock.patch.object(extract, 'collect', lambda *a, **k: (self.networks, [])),
            mock.patch.object(v51engine, 'budget_for', lambda rate, until: 180000),
            mock.patch.object(v51engine, 'candidate_stream', _candidates),
            mock.patch.object(hashcat, 'crack', _crack),
            mock.patch.object(hashcat, 'benchmark', lambda *a, **k: 50000),
        ]
        for patcher in self._patchers:
            patcher.start()

    def tearDown(self):
        for patcher in self._patchers:
            patcher.stop()

    def _run(self, outdir, **over):
        return runner.run(make_args(outdir, **over), out=self.out.append, ask=lambda _p: 'y')

    def test_full_run_cracks_and_reports(self):
        with tempfile.TemporaryDirectory() as tmp:
            code = self._run(tmp)
            self.assertEqual(code, 0)
            cracked = (Path(tmp) / 'cracked.txt').read_text()
            self.assertIn('Home\thomepass123', cracked)
            doc = json.loads((Path(tmp) / 'report.json').read_text())
            by = {n['essid']: n for n in doc['networks']}
            self.assertEqual(by['Home']['status'], 'cracked')
            self.assertEqual(by['Guest']['status'], 'not-found')

    def test_resume_skips_already_cracked(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / 'cracked.txt').write_text('Home\talready-known\n')
            seen = []
            with mock.patch.object(
                    hashcat, 'crack',
                    lambda _b, lines, c, _p, workload=3, runtime=None, on_proc=None:
                    seen.append(lines[0]) or []):
                self._run(tmp)
            self.assertTrue(all('Home' not in s for s in seen))
            self.assertTrue(any('Guest' in s for s in seen))

    def test_fresh_ignores_resume(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / 'cracked.txt').write_text('Home\talready-known\n')
            self._run(tmp, fresh=True)
            doc = json.loads((Path(tmp) / 'report.json').read_text())
            home = next(n for n in doc['networks'] if n['essid'] == 'Home')
            self.assertEqual(home['psk'], 'homepass123')

    def test_dry_run_skips_cracking(self):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(hashcat, 'crack',
                                   side_effect=AssertionError('must not crack')):
                code = self._run(tmp, dry_run=True)
            self.assertEqual(code, 0)
            self.assertTrue(any('dry run' in line for line in self.out))

    def test_list_mode(self):
        with tempfile.TemporaryDirectory() as tmp:
            code = self._run(tmp, list=True)
            self.assertEqual(code, 0)
            self.assertTrue(any('networks (2)' in line for line in self.out))

    def test_non_interactive_without_yes_aborts(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(runner.RunError):
                self._run(tmp, yes=False, interactive=False)

    def test_context_maps_lang_to_country(self):
        context = runner._context('Home', make_args('/tmp', lang='pl'))
        self.assertEqual(context['country'], 'PL')
        self.assertEqual(context['ssid'], 'Home')

    def test_no_networks_errors(self):
        self.networks.clear()
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(runner.RunError):
                self._run(tmp)

    def test_hashcat_error_reports_and_exits_nonzero(self):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(hashcat, 'crack',
                                   side_effect=hashcat.HashcatError('no device')):
                code = self._run(tmp)
            self.assertEqual(code, 1)
            doc = json.loads((Path(tmp) / 'report.json').read_text())
            self.assertTrue(all(n['status'] == 'error' for n in doc['networks']))

    def test_multiple_keys_recorded(self):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(
                    hashcat, 'crack',
                    lambda _b, lines, c, _p, workload=3, runtime=None, on_proc=None:
                    (c.close() or ['one', 'two']) if lines[0].endswith('Home') else []):
                self._run(tmp)
            doc = json.loads((Path(tmp) / 'report.json').read_text())
            home = next(n for n in doc['networks'] if n['essid'] == 'Home')
            self.assertEqual(home['psk'], 'one')
            self.assertIn('two', home['reason'])


if __name__ == '__main__':
    unittest.main()
