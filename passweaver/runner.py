"""Tie the stages together: discover, extract, plan, confirm, crack, report."""
import hashlib
import signal
import time
from pathlib import Path

from contextlib import closing

import deps
import discover
import v51engine as engine
import extract
import hashcat
import planning
import report


class RunError(Exception):
    """A run could not proceed; the message is shown to the user."""


def _default_outdir():
    return Path('passweaver-run-{}'.format(time.strftime('%Y%m%d-%H%M%S')))


def _check_writable(outdir):
    try:
        outdir.mkdir(parents=True, exist_ok=True)
        probe = outdir / '.write-test'
        probe.write_text('')
        probe.unlink()
    except OSError as exc:
        raise RunError('output directory not writable: {}'.format(exc))


def _context(essid, args):
    context = {'ssid': essid}
    if getattr(args, 'lang', None):
        context['country'] = engine.country_for(args.lang)
    for name in ('venue', 'address'):
        value = getattr(args, name, None)
        if value:
            context[name] = value
    return context


def run(args, out=print, ask=input):
    """Execute a full run. Returns a process exit code."""
    hcx = deps.find_hcx()

    captures, missing = discover.resolve(args.files)
    for pattern in missing:
        out('warning: no captures matched {!r}'.format(pattern))
    if not captures:
        raise RunError('no capture files found')
    out('captures: {}'.format(len(captures)))

    networks, skipped = extract_networks(hcx, captures, args.jobs, out)

    if args.list:
        _print_networks(networks, skipped, out)
        return 0
    if not networks:
        _print_networks(networks, skipped, out)
        raise RunError('no usable networks extracted')

    outdir = Path(args.outdir) if args.outdir else _default_outdir()
    _check_writable(outdir)
    potfile = outdir / 'passweaver.potfile'
    cracked_path = outdir / report.CRACKED_NAME
    report_path = outdir / report.REPORT_NAME

    resumed = {} if args.fresh else report.load_cracked(cracked_path)
    pending = [essid for essid in sorted(networks) if essid not in resumed]
    results = [report.Result(essid, 'cracked', psk=resumed[essid],
                             sources=networks[essid].sources, bssids=networks[essid].bssids)
               for essid in sorted(networks) if essid in resumed]
    if resumed:
        out('resuming: {} network(s) already cracked, skipped'.format(len(resumed)))

    until = planning.TIME_MODES[args.time]
    rate = _resolve_rate(args, potfile, out)
    budget = engine.budget_for(rate, until)
    max_total = planning.parse_duration(args.max_total) if args.max_total else None
    plan = planning.Plan(len(pending), args.time, until, rate, budget, max_total)

    out('')
    out(plan.render())

    if args.dry_run:
        out('dry run: no cracking performed')
        _finalize(report_path, cracked_path, args, rate, results,
                  [report.Result(e, 'skipped', reason='dry-run',
                                 sources=networks[e].sources) for e in pending], skipped)
        return 0
    if not pending:
        out('nothing to do: every network already cracked')
        _finalize(report_path, cracked_path, args, rate, results, [], skipped)
        return 0
    if not _confirm(args, out, ask):
        raise RunError('aborted by user')

    code = _crack_loop(args, networks, pending, rate, until, budget, max_total,
                       potfile, results, report_path, cracked_path, skipped, out)
    _finalize(report_path, cracked_path, args, rate, results, [], skipped)
    out(report.summary(results, skipped))
    out('output: {}'.format(outdir))
    return code


def extract_networks(hcx, captures, jobs, out):
    out('extracting handshakes ...')
    networks, skipped = extract.collect(hcx, captures, jobs=jobs)
    out('networks: {} · skipped captures: {}'.format(len(networks), len(skipped)))
    return networks, skipped


def _resolve_rate(args, potfile, out):
    if args.rate is not None:
        return int(args.rate)
    hashcat_bin = deps.find_hashcat()
    out('benchmarking hashcat (-m 22000) ...')
    cache = Path.home() / '.passweaver' / 'rate.json'
    cache.parent.mkdir(parents=True, exist_ok=True)
    return hashcat.benchmark(hashcat_bin, cache_path=cache)


def _confirm(args, out, ask):
    if args.yes:
        return True
    if not args.interactive:
        raise RunError('not a terminal: re-run with --yes to proceed non-interactively')
    answer = ask('Proceed? [y/N] ')
    return answer.strip().lower() in ('y', 'yes')


def _crack_loop(args, networks, pending, rate, until, budget, max_total,
                potfile, results, report_path, cracked_path, skipped, out):
    hashcat_bin = deps.find_hashcat()
    stop = {'now': False}
    current = {'proc': None}

    def _on_sigint(signum, frame):
        if not stop['now']:
            out('\ninterrupt: stopping current network, then exiting ...')
        stop['now'] = True
        proc = current['proc']
        if proc is not None and proc.poll() is None:
            try:
                proc.terminate()
            except (ProcessLookupError, OSError):
                pass

    previous = signal.signal(signal.SIGINT, _on_sigint)
    start = time.monotonic()
    processed = set()
    stop_reason = 'stopped'
    try:
        for index, essid in enumerate(pending, 1):
            if stop['now']:
                stop_reason = 'interrupted'
                break
            if max_total is not None and (time.monotonic() - start) >= max_total:
                out('time cap reached, stopping')
                stop_reason = 'time-cap'
                break
            runtime = None
            if max_total is not None:
                runtime = max_total - (time.monotonic() - start)
            network = networks[essid]
            out('[{}/{}] {} ({} handshake lines)'.format(
                index, len(pending), essid, len(network.lines)))
            result = _crack_one(hashcat_bin, args, network, rate, until,
                                potfile, runtime, out,
                                lambda p: current.__setitem__('proc', p))
            current['proc'] = None
            if stop['now'] and result.status == 'not-found':
                result = report.Result(network.essid, 'interrupted', reason='interrupted',
                                       sources=network.sources, bssids=network.bssids)
            results.append(result)
            processed.add(essid)
            report.write_cracked(cracked_path, results)
            report.write_report(report_path, _meta(args, rate), results, skipped)
    finally:
        signal.signal(signal.SIGINT, previous)
    for essid in pending:
        if essid not in processed:
            network = networks[essid]
            results.append(report.Result(essid, 'skipped', reason=stop_reason,
                                         sources=network.sources, bssids=network.bssids))
    return 1 if any(r.status == 'error' for r in results) else 0


def _safe_name(essid):
    base = ''.join(c if (c.isalnum() or c in '-_.') else '_' for c in essid) or 'network'
    return '{}-{}'.format(base, hashlib.sha1(essid.encode('utf-8')).hexdigest()[:8])


def _tee(candidates, path):
    """Yield candidates while also writing them to a file; closes both on stop."""
    with closing(candidates):
        with open(path, 'w', encoding='utf-8') as handle:
            for candidate in candidates:
                handle.write(candidate + '\n')
                yield candidate


def _crack_one(hashcat_bin, args, network, rate, until, potfile, runtime, out, on_proc):
    began = time.monotonic()
    candidates = engine.candidate_stream(_context(network.essid, args), rate, until)
    if args.keep:
        candidates = _tee(candidates, potfile.parent / ('cand-' + _safe_name(network.essid) + '.txt'))
    try:
        keys = hashcat.crack(hashcat_bin, network.lines, candidates, potfile,
                             workload=args.workload, runtime=runtime, on_proc=on_proc)
    except hashcat.HashcatError as exc:
        close = getattr(candidates, 'close', None)
        if close is not None:
            close()
        out('  error: {}'.format(exc))
        return report.Result(network.essid, 'error', reason=str(exc),
                             sources=network.sources, bssids=network.bssids)
    seconds = round(time.monotonic() - began, 1)
    if keys:
        reason = None
        if len(keys) > 1:
            reason = 'multiple keys for one ESSID: {}'.format(', '.join(keys[1:]))
            out('  cracked: {} (+{} more)'.format(keys[0], len(keys) - 1))
        else:
            out('  cracked: {}'.format(keys[0]))
        return report.Result(network.essid, 'cracked', psk=keys[0], reason=reason,
                             sources=network.sources, bssids=network.bssids, seconds=seconds)
    out('  not found')
    return report.Result(network.essid, 'not-found', sources=network.sources,
                         bssids=network.bssids, seconds=seconds)


def _meta(args, rate):
    return {'engine': engine.VERSION, 'mode': args.time,
            'until_seconds': planning.TIME_MODES[args.time], 'rate': rate}


def _finalize(report_path, cracked_path, args, rate, results, extra, skipped):
    combined = results + extra
    report.write_cracked(cracked_path, combined)
    report.write_report(report_path, _meta(args, rate), combined, skipped)


def _print_networks(networks, skipped, out):
    out('')
    out('networks ({}):'.format(len(networks)))
    for essid in sorted(networks):
        net = networks[essid]
        out('  {} · {} handshake line(s) · {} capture(s)'.format(
            essid, len(net.lines), len(net.sources)))
    if skipped:
        out('')
        out('skipped captures ({}):'.format(len(skipped)))
        for file, reason in skipped:
            out('  {}: {}'.format(getattr(file, 'name', file), reason))
