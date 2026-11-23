"""Collect results and write the run's outputs."""
import json
from pathlib import Path

CRACKED_NAME = 'cracked.txt'
REPORT_NAME = 'report.json'


class Result:
    def __init__(self, essid, status, psk=None, sources=None, bssids=None,
                 reason=None, seconds=None):
        self.essid = essid
        self.status = status           # 'cracked' | 'not-found' | 'skipped' | 'error'
        self.psk = psk
        self.sources = sorted(sources or [])
        self.bssids = sorted(bssids or [])
        self.reason = reason
        self.seconds = seconds

    def as_dict(self):
        data = {'essid': self.essid, 'status': self.status}
        for key in ('psk', 'reason', 'seconds'):
            value = getattr(self, key)
            if value is not None:
                data[key] = value
        if self.sources:
            data['sources'] = self.sources
        if self.bssids:
            data['bssids'] = self.bssids
        return data


def load_cracked(path):
    """Read a cracked.txt from an earlier run into {essid: psk} for resume."""
    cracked = {}
    file = Path(path)
    if not file.exists():
        return cracked
    for line in file.read_text().splitlines():
        if '\t' in line:
            essid, psk = line.split('\t', 1)
            cracked[essid] = psk
    return cracked


def write_cracked(path, results):
    lines = ['{}\t{}'.format(r.essid, r.psk) for r in results if r.status == 'cracked' and r.psk]
    Path(path).write_text(''.join(line + '\n' for line in lines))


def write_report(path, meta, results, skipped_files):
    document = {
        'meta': meta,
        'networks': [r.as_dict() for r in results],
        'skipped_files': [{'file': str(f), 'reason': reason} for f, reason in skipped_files],
    }
    Path(path).write_text(json.dumps(document, indent=2, ensure_ascii=False) + '\n')


def summary(results, skipped_files):
    """Return the human end-of-run summary as a string."""
    cracked = [r for r in results if r.status == 'cracked']
    not_found = [r for r in results if r.status == 'not-found']
    errored = [r for r in results if r.status == 'error']
    lines = ['', '=== passweaver summary ===']
    lines.append('networks: {} total · {} cracked · {} not found · {} error'.format(
        len(results), len(cracked), len(not_found), len(errored)))
    lines.append('captures skipped: {}'.format(len(skipped_files)))
    if cracked:
        lines.append('')
        lines.append('cracked:')
        for r in cracked:
            lines.append('  {}\t{}'.format(r.essid, r.psk))
    if skipped_files:
        lines.append('')
        lines.append('skipped captures:')
        for file, reason in skipped_files:
            lines.append('  {}: {}'.format(getattr(file, 'name', file), reason))
    return '\n'.join(lines)
