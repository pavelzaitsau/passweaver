import argparse
from collections import Counter
import hashlib
import hmac
import json
import multiprocessing as mp
import os
from pathlib import Path
import signal
import sys
import time

import batch
import hybrid


def paired_metrics(left, right, plans):
    if len(left) != len(right):
        raise ValueError('comparison_record_count_mismatch')
    result = []
    for phase, plan in enumerate(plans):
        flags = []
        for outcomes in (left, right):
            flags.append([r['hit'] is not None and r['hit'][0] <= phase and
                          r['hit'][1] <= plan['total_candidates'] for r in outcomes])
        a, b = flags
        common = sum(x and y for x, y in zip(a, b))
        gained = sum(not x and y for x, y in zip(a, b))
        lost = sum(x and not y for x, y in zip(a, b))
        result.append(dict(seconds=plan['seconds'], budget=plan['total_candidates'],
                           total=len(left), v3=sum(a), v4=sum(b), common=common,
                           gained=gained, lost=lost, net=gained - lost,
                           neither=sum(not x and not y for x, y in zip(a, b))))
    return result


def production_check():
    root = hybrid.v3.ROOT
    manifest = json.loads((root / 'release-manifest.json').read_text())
    bad = [name for name, checksum in manifest['files_sha256'].items()
           if hashlib.sha256((root / name).read_bytes()).hexdigest() != checksum]
    if bad:
        raise ValueError('accepted_v3_manifest_mismatch')
    return len(manifest['files_sha256'])


def _version_worker(version, rows, rate, destination, workers):
    log = destination / (version + '-progress.jsonl')
    started = time.monotonic()
    try:
        os.setsid()
        with log.open('x', encoding='utf-8') as stream:
            def progress(value):
                stream.write(json.dumps(dict(value, wall_seconds=time.monotonic() - started)) + '\n')
                stream.flush()
            report, outcomes = batch.evaluate_version(rows, version, rate, 7200, workers=workers, progress=progress)
        report['analysis_wall_seconds'] = time.monotonic() - started
        hybrid.write_json_exclusive(destination / (version + '-report.json'), report)
        hybrid.write_json_exclusive(destination / 'private-inputs' / (version + '-outcomes.json'), outcomes)
    except BaseException:
        hybrid.write_json_exclusive(destination / (version + '-failure.json'), {'status': 'failed', 'version': version})
        raise SystemExit(1)


def cleanup_processes(processes):
    started = [process for process in processes if process.pid is not None]
    for process in started:
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        if process.is_alive():
            process.terminate()
    for process in started:
        process.join(timeout=2)
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        if process.is_alive():
            process.kill()
            process.join(timeout=5)


def run(input_dir, destination, rate=235000, workers=6,
        expected_datasets=('p01', 'p02', 'p03', 'p04', 'p05', 'p06', 'p07')):
    os.umask(0o077)
    if type(workers) is not int or workers < 1:
        raise ValueError('invalid_worker_count')
    plans = hybrid.plan(rate)
    inputs = sorted(Path(input_dir).glob('wifox_ssid_password-p*.txt'))
    observed = [path.stem.rsplit('-', 1)[-1] for path in inputs]
    if sorted(observed) != sorted(expected_datasets):
        raise ValueError('comparison_dataset_inventory_mismatch')
    production_files = production_check()
    signature = hybrid.method_signature()
    method_paths = [hybrid.ROOT / 'compare.py', *hybrid.ROOT.glob('test_*.py')]
    frozen = {str(p.relative_to(hybrid.ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in method_paths}
    destination = Path(destination)
    destination.mkdir(mode=0o700, parents=True, exist_ok=False)
    private = destination / 'private-inputs'
    private.mkdir(mode=0o700)
    rows, labels, snapshot_bytes, inventory = [], [], {}, []
    for path in inputs:
        data = path.read_bytes()
        if path.read_bytes() != data:
            raise ValueError('input_changed_during_snapshot')
        parsed = hybrid.v3.parse_input(data, 'legacy-text')
        saved = private / path.name
        with saved.open('xb') as stream:
            os.fchmod(stream.fileno(), 0o400)
            stream.write(data)
        snapshot_bytes[path.name] = data
        label = path.stem.rsplit('-', 1)[-1]
        inventory.append(dict(dataset=label, records=len(parsed)))
        for row in parsed:
            rows.append({'ssid': row['ssid'], 'password': row['password']})
            labels.append(label)
    if not rows:
        raise ValueError('empty_comparison_snapshot')
    canonical = json.dumps(rows, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
    key = os.urandom(32)
    with (private / 'attestation.key').open('xb') as stream:
        os.fchmod(stream.fileno(), 0o600)
        stream.write(key)
    attestation = hmac.new(key, canonical, hashlib.sha256).hexdigest()
    protocol = dict(status='frozen_before_measurement', revision=hybrid.REVISION, method=signature,
                    comparison_and_tests_sha256=frozen, rate=str(rate), checkpoints=plans,
                    datasets=inventory, total=len(rows),
                    duplicate_pairs=len(rows) - len({(r['ssid'], r['password']) for r in rows}),
                    snapshot_attestation_hmac_sha256=attestation,
                    privacy='key_and_inputs_and_success_ranks_remain_private',
                    context='SSID only; no country, venue or address inferred',
                    data_independence='previously used regression data; not an unseen holdout',
                    v3='accepted rules and order with budget extended to identical checkpoints',
                    v4='new family-local-dedup revision; not the pre-review V4 sequence',
                    measurement='offline exact candidate rank; not GPU throughput benchmark',
                    production_files_verified=production_files)
    hybrid.write_json_exclusive(destination / 'protocol.json', protocol)
    print(json.dumps({'status': 'frozen', 'records': len(rows), 'datasets': inventory,
                      'destination': str(destination.resolve())}), flush=True)
    context = mp.get_context('fork')
    processes = {}
    try:
        for version in ('v3', 'v4'):
            child = context.Process(target=_version_worker, args=(version, rows, rate, destination, workers))
            processes[version] = child
            child.start()
        while any(process.is_alive() for process in processes.values()):
            for process in processes.values():
                if process.exitcode not in (None, 0):
                    raise ValueError('comparison_worker_failed')
            time.sleep(2)
        if any(process.exitcode != 0 for process in processes.values()):
            raise ValueError('comparison_worker_failed')
    finally:
        cleanup_processes(processes.values())
    hybrid.method_signature()
    for name, expected in frozen.items():
        if hashlib.sha256((hybrid.ROOT / name).read_bytes()).hexdigest() != expected:
            raise ValueError('comparison_method_changed')
    for name, data in snapshot_bytes.items():
        if (private / name).read_bytes() != data:
            raise ValueError('comparison_snapshot_changed')
    production_check()
    left = json.loads((private / 'v3-outcomes.json').read_text())
    right = json.loads((private / 'v4-outcomes.json').read_text())
    if len(left) != len(rows) or len(right) != len(rows):
        raise ValueError('comparison_result_count_mismatch')
    results = dict(status='completed', rate=str(rate), total=len(rows),
                   overall=paired_metrics(left, right, plans), by_dataset={},
                   snapshot_attestation_hmac_sha256=attestation,
                   protocol='protocol.json', data_independence=protocol['data_independence'])
    for label in sorted(set(labels)):
        selected = [i for i, value in enumerate(labels) if value == label]
        results['by_dataset'][label] = paired_metrics([left[i] for i in selected], [right[i] for i in selected], plans)
    for version in ('v3', 'v4'):
        report = json.loads((destination / (version + '-report.json')).read_text())
        if len(report['curve']) != len(plans) or any(
                report['curve'][i]['matched'] != result[version] for i, result in enumerate(results['overall'])):
            raise ValueError('paired_summary_mismatch')
    hybrid.write_json_exclusive(destination / 'results.json', results)
    print(json.dumps(results['overall']), flush=True)
    return results


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--input-dir', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--rate', default='235000')
    parser.add_argument('--workers', type=int, default=6)
    parser.add_argument('--expected-datasets', default='p01,p02,p03,p04,p05,p06,p07')
    args = parser.parse_args()
    try:
        run(args.input_dir, args.output, args.rate, args.workers, args.expected_datasets.split(','))
        return 0
    except KeyboardInterrupt:
        print(json.dumps({'status': 'cancelled'}))
        return 130
    except Exception:
        print(json.dumps({'status': 'failed', 'code': 'comparison_failed'}))
        return 1


if __name__ == '__main__':
    sys.exit(main())
