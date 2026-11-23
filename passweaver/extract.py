"""Turn capture files into per-network hashcat 22000 hash lines.

One capture may hold handshakes for several networks, and one network may
appear across several captures. Networks are keyed by ESSID and merged
globally so each distinct network is cracked once.
"""
import subprocess
import tempfile
from pathlib import Path


class Network:
    """A single Wi-Fi network and every 22000 hash line seen for it."""

    def __init__(self, essid):
        self.essid = essid
        self.lines = []            # hashcat 22000 lines, de-duplicated
        self.bssids = set()
        self.sources = set()       # capture file names the network was seen in

    def add(self, line, bssid, source):
        if line not in self.lines:
            self.lines.append(line)
        if bssid:
            self.bssids.add(bssid)
        self.sources.add(source)


def _decode_essid(field):
    """Decode the hex ESSID field of a 22000 line to text, or None if it can't."""
    try:
        raw = bytes.fromhex(field)
    except ValueError:
        return None
    if not raw:
        return None
    try:
        return raw.decode('utf-8')
    except UnicodeDecodeError:
        return None


def parse_line(line):
    """Return (essid, bssid, reason). essid is None when the line is unusable.

    A 22000 line is 'WPA*<type>*<hash>*<mac_ap>*<mac_sta>*<essid_hex>*...'.
    """
    parts = line.split('*')
    if len(parts) < 6 or parts[0] != 'WPA':
        return None, None, 'malformed line'
    essid = _decode_essid(parts[5])
    if essid is None:
        if parts[5] == '':
            return None, None, 'no ESSID (hidden)'
        return None, None, 'non-decodable ESSID'
    bssid = parts[3].lower()
    return essid, bssid, None


def run_hcx(hcx, capture, workdir, tag):
    """Extract one capture to a 22000 file. Return (lines, reason).

    tag makes the output name unique, so captures that share a basename across
    directories do not overwrite each other under parallel extraction.
    reason is set when the capture yielded nothing usable.
    """
    out = Path(workdir) / ('cap-{}.hc22000'.format(tag))
    try:
        proc = subprocess.run(
            [hcx, '-o', str(out), str(capture)],
            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
    except OSError as exc:
        return [], 'hcxpcapngtool failed: {}'.format(exc)
    if proc.returncode != 0:
        detail = (proc.stderr or '').strip().splitlines()
        return [], 'hcxpcapngtool exit {}: {}'.format(
            proc.returncode, detail[-1] if detail else 'no detail')
    if not out.exists():
        return [], 'no handshake found'
    lines = [ln for ln in out.read_text().splitlines() if ln.strip()]
    if not lines:
        return [], 'no handshake found'
    return lines, None


def collect(hcx, captures, jobs=1):
    """Extract every capture and merge networks by ESSID.

    Returns (networks, skipped) where networks maps ESSID -> Network and
    skipped is a list of (capture_path, reason).
    """
    networks = {}
    skipped = []
    with tempfile.TemporaryDirectory(prefix='passweaver-hcx-') as workdir:
        results = _extract_all(hcx, captures, workdir, jobs)
    for capture, lines, reason in results:
        if reason:
            skipped.append((capture, reason))
            continue
        usable = 0
        reasons = []
        for line in lines:
            essid, bssid, line_reason = parse_line(line)
            if essid is None:
                if line_reason:
                    reasons.append(line_reason)
                continue
            networks.setdefault(essid, Network(essid)).add(line, bssid, capture.name)
            usable += 1
        if usable == 0:
            skipped.append((capture, reasons[0] if reasons else 'no usable handshake'))
    return networks, skipped


def _extract_all(hcx, captures, workdir, jobs):
    """Run hcx over the captures, optionally in parallel. Order is not kept.

    Each capture gets a unique output tag so a shared basename cannot collide.
    """
    if jobs <= 1 or len(captures) <= 1:
        return [(cap, *run_hcx(hcx, cap, workdir, tag)) for tag, cap in enumerate(captures)]
    from concurrent.futures import ThreadPoolExecutor
    results = []
    with ThreadPoolExecutor(max_workers=jobs) as pool:
        futures = {pool.submit(run_hcx, hcx, cap, workdir, tag): cap
                   for tag, cap in enumerate(captures)}
        for future in futures:
            cap = futures[future]
            lines, reason = future.result()
            results.append((cap, lines, reason))
    return results
