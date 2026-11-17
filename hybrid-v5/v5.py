import argparse
from contextlib import ExitStack
import hashlib
import itertools
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent / 'hybrid-v4'))
import hybrid
import batch
import oracles

v3 = hybrid.v3
REVISION = 'v5-protected-v3'
WEIGHTS = [('v3_continue', 4), ('v4_pairs', 2), ('v4_masks', 1), ('prince', 1)]
WITHOUT_PRINCE = [('v3_continue', 5), ('v4_pairs', 2), ('v4_masks', 1)]


def base_config(budget):
    value = json.loads((v3.ROOT / 'config.json').read_text())
    v3.validate_config(value)
    return dict(value, budget_per_pair=max(1, budget))


def protected_budget(rate):
    return next(p['total_candidates'] for p in hybrid.plan(rate) if p['seconds'] == 600)


def schedule_valid(streams, stages, batch_size=256):
    emitted, exhausted = 0, set()
    for phase, (budget, weights) in enumerate(stages):
        active = [(name, weight) for name, weight in weights if name not in exhausted]
        while active and emitted < budget:
            total = sum(weight for _, weight in active)
            cycle = min(budget - emitted, batch_size * total)
            quotas = [cycle * weight // total for _, weight in active]
            order = sorted(range(len(active)), key=lambda i: (-(cycle * active[i][1] % total), i))
            for i in order[:cycle - sum(quotas)]:
                quotas[i] += 1
            for (name, weight), quota in zip(active[:], quotas):
                for _ in range(quota):
                    try:
                        value = next(streams[name])
                    except StopIteration:
                        exhausted.add(name)
                        active.remove((name, weight))
                        break
                    emitted += 1
                    yield phase + 5, name, value


def compose(base, extensions, budget, protected, weights=WEIGHTS, batch_size=256, boundaries=None):
    prefix = 0
    with ExitStack() as cleanup:
        for stream in [base, *extensions.values()]:
            close = getattr(stream, 'close', None)
            if close is not None:
                cleanup.callback(close)
        for value in itertools.islice(base, min(protected, budget)):
            prefix += 1
            yield 0, 'v3_prefix', value
        if budget <= protected:
            return
        streams = dict(extensions, v3_continue=base)
        stages = [(ceiling - prefix, weights) for ceiling in (boundaries or [budget]) if protected < ceiling <= budget]
        yield from schedule_valid(streams, stages, batch_size)


def index(base_length, extension_lengths, budget, protected, weights=WEIGHTS, batch_size=256, boundaries=None):
    prefix = min(base_length, budget, protected)
    segments = []
    if prefix:
        segments.append(dict(phase=0, family='v3_prefix', family_start=1, count=prefix,
                             global_start=1, chunk=prefix, stride=prefix))
    emitted = prefix
    if budget > protected:
        lengths = dict(extension_lengths, v3_continue=max(0, base_length - prefix))
        stages = [(ceiling - prefix, weights) for ceiling in (boundaries or [budget]) if protected < ceiling <= budget]
        late, complete, _ = batch.schedule_index(lengths, stages, batch=batch_size)
        for segment in late:
            segment['phase'] += 5
            segment['global_start'] += prefix
        segments.extend(late)
        emitted += complete[-1]['emitted']
    return segments, emitted, prefix


def check_prince():
    manifest = json.loads((ROOT / 'prince-manifest.json').read_text())
    for key, digest in [('binary', 'binary_sha256'), ('seed', 'seed_sha256')]:
        path = (ROOT / manifest[key]).resolve()
        if ROOT not in path.parents or hashlib.sha256(path.read_bytes()).hexdigest() != manifest[digest]:
            raise ValueError('prince_integrity_failed')
    if hashlib.sha256((ROOT / 'vendor/princeprocessor/src/pp.c').read_bytes()).hexdigest() != manifest['source_sha256']:
        raise ValueError('prince_source_changed')
    for name, digest in manifest['source_files_sha256'].items():
        path = (ROOT / name).resolve()
        if ROOT not in path.parents or hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise ValueError('prince_source_changed')
    if manifest['argv'] != ['--pw-min=8', '--pw-max=16', '--elem-cnt-min=2', '--elem-cnt-max=3',
                            '--dupe-check-disable', '--save-pos-disable']:
        raise ValueError('prince_arguments_changed')
    return manifest


def prince_stream():
    manifest = check_prince()
    with tempfile.TemporaryDirectory(prefix='wfm-prince-') as directory, tempfile.TemporaryFile() as errors:
        process = subprocess.Popen([str(ROOT / manifest['binary']), *manifest['argv'], str(ROOT / manifest['seed'])],
                                   stdout=subprocess.PIPE, stderr=errors, cwd=directory,
                                   env=dict(os.environ, LC_ALL='C'))
        try:
            for line in process.stdout:
                if not line.endswith(b'\n'):
                    raise ValueError('prince_incomplete_record')
                yield line[:-1].decode('ascii')
            if process.wait(timeout=10) != 0:
                raise ValueError('prince_generation_failed')
        finally:
            process.stdout.close()
            if process.poll() is None:
                try:
                    process.terminate()
                except ProcessLookupError:
                    pass
                try:
                    process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=3)


def filtered_closing(source):
    try:
        yield from hybrid.rules.filtered(source)
    finally:
        close = getattr(source, 'close', None)
        if close is not None:
            close()


def extension_streams(sources):
    words = sources['words']
    masks = (hybrid.rules.filtered(hybrid.word_masks(words, width)) for width in (3, 4))
    return {'v4_pairs': hybrid.rules.filtered(hybrid.pair_stream(words)),
            'v4_masks': hybrid.rules.mix(masks, 256),
            'prince': filtered_closing(prince_stream())}


def candidates(context, rate, until):
    context = hybrid.validate_context({k: value for k, value in context.items() if k != 'language'})
    plans = hybrid.plan(rate)
    if until not in hybrid.CHECKPOINTS:
        raise ValueError('invalid_checkpoint')
    budget = next(p['total_candidates'] for p in plans if p['seconds'] == until)
    config = base_config(budget)
    raw, words, _ = v3.load_words()
    base = (value for _, value in v3.candidates_for_ssid(context['ssid'], config, raw, words))
    extensions = {} if budget <= protected_budget(rate) else extension_streams(hybrid.load_sources(context['language']))
    yield from compose(base, extensions, budget, protected_budget(rate),
                       boundaries=[p['total_candidates'] for p in plans if p['seconds'] <= until])


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser()
    parser.add_argument('--ssid', required=True)
    parser.add_argument('--rate', required=True)
    parser.add_argument('--until', type=int, choices=hybrid.CHECKPOINTS, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--max-candidates', type=int)
    args = parser.parse_args()
    try:
        if args.max_candidates is not None and args.max_candidates <= 0:
            raise ValueError('invalid_limit')
        source = candidates({'ssid': args.ssid}, args.rate, args.until)
        stream = args.output.open('xb')
        count, digest = 0, hashlib.sha256()
        try:
            try:
                with stream:
                    os.fchmod(stream.fileno(), 0o600)
                    for _, _, value in itertools.islice(source, args.max_candidates):
                        data = value.encode('utf-8') + b'\n'
                        stream.write(data)
                        count += 1
                        digest.update(data)
            finally:
                source.close()
        except BaseException:
            args.output.unlink(missing_ok=True)
            raise
        print(json.dumps(dict(status='completed', candidates=count, sha256=digest.hexdigest())))
        return 0
    except KeyboardInterrupt:
        return 130
    except Exception:
        print(json.dumps(dict(status='failed')))
        return 1


if __name__ == '__main__':
    sys.exit(main())
