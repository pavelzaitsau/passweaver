"""Drive hashcat: benchmark the rate, and crack a network from stdin."""
import json
import platform
import subprocess
import tempfile
from pathlib import Path

MODE = '22000'


class HashcatError(Exception):
    """hashcat could not be run or failed in a way that is not 'not found'."""


def _parse_benchmark(text):
    """Sum the per-device speed from hashcat --machine-readable benchmark output.

    Lines look like '22000:1:0:SPEED:EXEC_MS:...'; the speed is the largest
    integer after the mode, summed across devices.
    """
    total = 0
    for line in text.splitlines():
        if not line.startswith(MODE + ':'):
            continue
        fields = line.split(':')
        ints = [int(f) for f in fields[1:] if f.lstrip('-').isdigit()]
        if ints:
            total += max(ints)
    return total


def _bench_key(hashcat):
    """A cache key that changes with the host, platform and hashcat version."""
    try:
        version = subprocess.run([hashcat, '--version'], stdout=subprocess.PIPE,
                                 stderr=subprocess.DEVNULL, text=True).stdout.strip()
    except OSError:
        version = 'unknown'
    return '{}|{}|{}'.format(platform.node(), platform.platform(), version)


def benchmark(hashcat, cache_path=None, extra_args=()):
    """Return the hashcat 22000 speed in H/s, caching the result per host.

    The cache is invalidated when the host, platform or hashcat version changes.
    """
    key = _bench_key(hashcat)
    if cache_path is not None:
        cache = Path(cache_path)
        if cache.exists():
            try:
                data = json.loads(cache.read_text())
                if data.get('key') == key and int(data['rate']) > 0:
                    return int(data['rate'])
            except (ValueError, KeyError, OSError):
                pass
    proc = subprocess.run(
        [hashcat, '-b', '-m', MODE, '--machine-readable', '--quiet', *extra_args],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    rate = _parse_benchmark(proc.stdout)
    if rate <= 0:
        detail = (proc.stderr or proc.stdout or '').strip().splitlines()
        raise HashcatError('could not read a benchmark rate: {}'.format(
            detail[-1] if detail else 'no output'))
    if cache_path is not None:
        try:
            Path(cache_path).write_text(json.dumps({'key': key, 'rate': rate}))
        except OSError:
            pass
    return rate


def _feed(proc, candidates):
    """Pump candidates into hashcat's stdin until it stops reading or we run dry."""
    try:
        for candidate in candidates:
            proc.stdin.write(candidate.encode('utf-8') + b'\n')
    except BrokenPipeError:
        pass          # hashcat exited early, typically because it cracked the key
    finally:
        try:
            proc.stdin.close()
        except BrokenPipeError:
            pass


def _recovered(hashcat, hashfile, potfile):
    """Read every passphrase hashcat has for this hash set, including pot hits.

    --show reads the potfile without attacking, so it reports keys a run found
    and keys already present from an earlier run. Distinct, order preserved.
    """
    with tempfile.NamedTemporaryFile('w+', suffix='.txt', delete=False) as handle:
        show_out = Path(handle.name)
    try:
        subprocess.run(
            [hashcat, '-m', MODE, '--show', '--quiet', '--potfile-path', str(potfile),
             '-o', str(show_out), '--outfile-format', '2', str(hashfile)],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        seen, keys = set(), []
        for line in show_out.read_text().splitlines():
            if line and line not in seen:
                seen.add(line)
                keys.append(line)
        return keys
    finally:
        show_out.unlink(missing_ok=True)


def crack(hashcat, hash_lines, candidates, potfile, workload=3, runtime=None, on_proc=None):
    """Crack one network by streaming candidates into hashcat.

    on_proc, when given, is called with the hashcat Popen so the caller can
    terminate it on an interrupt. Returns the list of recovered passphrases
    (empty if none). Raises HashcatError when hashcat fails to initialise.
    """
    with tempfile.TemporaryDirectory(prefix='passweaver-hc-') as workdir:
        hashfile = Path(workdir) / 'target.hc22000'
        outfile = Path(workdir) / 'cracked.txt'
        hashfile.write_text('\n'.join(hash_lines) + '\n')
        cmd = [hashcat, '-m', MODE, '--quiet', '-w', str(workload),
               '--potfile-path', str(potfile),
               '-o', str(outfile), '--outfile-format', '2', str(hashfile)]
        if runtime is not None:
            cmd += ['--runtime', str(max(1, int(runtime)))]
        try:
            proc = subprocess.Popen(cmd, stdin=subprocess.PIPE,
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError as exc:
            raise HashcatError('could not start hashcat: {}'.format(exc))
        if on_proc is not None:
            on_proc(proc)
        try:
            _feed(proc, candidates)
        finally:
            close = getattr(candidates, 'close', None)
            if close is not None:
                close()
        code = proc.wait()
        # Negative code means a crash/init failure (no device, driver). Positive
        # codes (0 cracked, 1 exhausted, 2/3/4 aborted) are normal outcomes;
        # read the pot to learn which hashes are actually recovered.
        if code < 0:
            raise HashcatError('hashcat exited with signal {}'.format(-code))
        return _recovered(hashcat, hashfile, potfile)
