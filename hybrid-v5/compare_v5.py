import hashlib
import hmac
import importlib.util
import itertools
import json
import multiprocessing as mp
from multiprocessing.connection import wait
import os
import signal
from pathlib import Path
import sys
import time

import v5

ROOT = v5.ROOT
V4 = ROOT.parent / 'hybrid-v4'
CACHE = V4 / 'results/comparison-20261116-full'
EVIDENCE = ROOT / 'results/verified-baseline'
spec = importlib.util.spec_from_file_location('verified_v4_compare', V4 / 'compare.py')
legacy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(legacy)


def named_pairs(rows, right='v5'):
    return [{(right if key == 'v4' else key): value for key, value in row.items()} for row in rows]


def validate_outcomes(values, plans):
    for row in values:
        if not isinstance(row, dict) or set(row) != {'hit', 'emitted'} or len(row['emitted']) != len(plans):
            raise ValueError('cache_outcome_invalid')
        previous = 0
        for emitted, plan in zip(row['emitted'], plans):
            if type(emitted) is not int or not previous <= emitted <= plan['total_candidates']:
                raise ValueError('cache_outcome_invalid')
            previous = emitted
        hit = row['hit']
        if hit is not None and (not isinstance(hit, list) or len(hit) != 2 or hit[0] != 0 or
                                type(hit[1]) is not int or not 1 <= hit[1] <= previous):
            raise ValueError('cache_hit_outside_verified_range')


def read_source(path=CACHE):
    path = Path(path)
    protocol = json.loads((path / 'protocol.json').read_text())
    if protocol['status'] != 'frozen_before_measurement' or protocol['rate'] != '235000':
        raise ValueError('unsupported_baseline_protocol')
    if [d['dataset'] for d in protocol['datasets']] != ['p01','p02','p03','p04','p05','p06','p07']:
        raise ValueError('cache_dataset_inventory_mismatch')
    for name, checksum in protocol['method']['files_sha256'].items():
        file = (ROOT.parent / name).resolve()
        if ROOT.parent not in file.parents or hashlib.sha256(file.read_bytes()).hexdigest() != checksum:
            raise ValueError('cached_method_changed')
    for name, checksum in protocol['comparison_and_tests_sha256'].items():
        file = (V4 / name).resolve()
        if V4 not in file.parents or hashlib.sha256(file.read_bytes()).hexdigest() != checksum:
            raise ValueError('cached_comparison_changed')
    legacy.production_check()
    v5.v3.load_words()
    rows, labels = [], []
    private = path / 'private-inputs'
    for dataset in protocol['datasets']:
        parsed = v5.v3.parse_input((private / ('wifox_ssid_password-' + dataset['dataset'] + '.txt')).read_bytes(), 'legacy-text')
        if len(parsed) != dataset['records']:
            raise ValueError('cache_record_count_mismatch')
        rows.extend({'ssid': r['ssid'], 'password': r['password']} for r in parsed)
        labels.extend([dataset['dataset']] * len(parsed))
    canonical = json.dumps(rows, ensure_ascii=False, separators=(',', ':')).encode()
    digest = hmac.new((private / 'attestation.key').read_bytes(), canonical, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(digest, protocol['snapshot_attestation_hmac_sha256']):
        raise ValueError('cache_input_attestation_failed')
    if len(rows) != protocol['total']:
        raise ValueError('cache_result_count_mismatch')
    return dict(rows=rows, labels=labels, protocol=protocol, canonical=canonical)


def read_cache(path=CACHE, evidence=EVIDENCE):
    source = read_source(path)
    rows, labels, protocol = source['rows'], source['labels'], source['protocol']
    evidence = Path(evidence)
    if not (evidence / 'certificate.json').is_file():
        raise ValueError('attested_reference_required')
    certificate = json.loads((evidence / 'certificate.json').read_text())
    binding = certificate['binding']
    expected_config = v5.base_config(protocol['checkpoints'][-1]['total_candidates'])
    expected_binding = dict(records=len(rows), rate=235000, checkpoints=protocol['checkpoints'],
        datasets=protocol['datasets'], input_attestation=protocol['snapshot_attestation_hmac_sha256'],
        source_files_sha256=protocol['method']['files_sha256'],
        producer_sha256=hashlib.sha256((ROOT / 'refresh_baseline.py').read_bytes()).hexdigest(),
        config=expected_config, creation='fresh exact reference evaluation, not adopted old outcomes')
    if binding != expected_binding:
        raise ValueError('reference_binding_invalid')
    private = evidence / 'private-inputs'
    outcome_bytes = (private / 'v3-outcomes.json').read_bytes()
    key = (private / 'cache.key').read_bytes()
    signed = json.dumps(binding, sort_keys=True, separators=(',', ':')).encode()
    signature = hmac.new(key, signed + b'\0' + outcome_bytes + b'\0' + source['canonical'], hashlib.sha256).hexdigest()
    if len(key) != 32 or not hmac.compare_digest(signature, certificate['hmac_sha256']):
        raise ValueError('reference_output_attestation_failed')
    baseline = json.loads(outcome_bytes)
    if len(baseline) != len(rows):
        raise ValueError('cache_result_count_mismatch')
    validate_outcomes(baseline, protocol['checkpoints'])
    report = json.loads((evidence / 'v3-report.json').read_text())
    if report['v3_effective_config'] != expected_config or report['method'] != protocol['method']:
        raise ValueError('cache_effective_configuration_mismatch')
    paired = legacy.paired_metrics(baseline, baseline, protocol['checkpoints'])
    if any(p['v3'] != r['matched'] for p, r in zip(paired, report['curve'])) or len(report['curve']) != 8:
        raise ValueError('cache_baseline_summary_mismatch')
    return dict(rows=rows, labels=labels, baseline=baseline, protocol=protocol,
                private_digest=hashlib.sha256(outcome_bytes).hexdigest(), reference_certificate=certificate)


def cleanup_workers(processes):
    started = [process for process in processes if process.pid is not None]
    for process in started:
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            pass
        if process.is_alive():
            process.terminate()
    for process in started:
        process.join(timeout=10)
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass
        if process.is_alive():
            process.kill()
            process.join(timeout=3)


def mask_state(sources, targets, limit):
    states = [v5.oracles.mask_oracle(sources['words'], width, targets) for width in (3, 4)]
    if any(state is None for state in states):
        return None
    lengths = {'a': states[0]['length'], 'b': states[1]['length']}
    total = sum(lengths.values())
    segments, _, _ = v5.batch.schedule_index(lengths, [(total + 512, [('a', 1), ('b', 1)])])
    hits = {}
    for target in targets.values():
        ranks = {name: state['hits'][target] for name, state in zip(('a', 'b'), states) if target in state['hits']}
        hit = v5.batch.first_hit(segments, ranks)
        if hit:
            hits[target] = hit[1]
    return dict(length=total, scanned=total, hits=hits, exact_analytic=True)


def _worker(connection, family, sources, targets):
    try:
        def stop(signum, frame):
            raise SystemExit(0)
        signal.signal(signal.SIGTERM, stop)
        os.setsid()
        stream = v5.extension_streams(sources)[family]
        scanner = v5.batch.Scanner(stream, targets)
        try:
            while True:
                limit = connection.recv()
                if limit is None:
                    break
                state = scanner.scan(limit, lambda n: connection.send(dict(kind='progress', scanned=n)))
                connection.send(dict(kind='result', **state))
        finally:
            stream.close()
    except BaseException:
        try:
            connection.send(dict(kind='error'))
        except (EOFError, BrokenPipeError):
            pass
    finally:
        connection.close()


def run(destination=ROOT / 'results/comparison-v5'):
    os.umask(0o077)
    cache = read_cache()
    rate = 235000
    plans = v5.hybrid.plan(rate)
    budget, protected = plans[-1]['total_candidates'], v5.protected_budget(rate)
    boundaries = [p['total_candidates'] for p in plans]
    v5.check_prince()
    sources = v5.hybrid.load_sources('en')
    method_files = [*ROOT.glob('*.py'), ROOT / 'SPEC.md', ROOT / 'prince-manifest.json', ROOT / 'prince-seeds.txt',
                    *[p for p in (ROOT / 'vendor/princeprocessor').rglob('*') if p.is_file()]]
    frozen = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in method_files}
    destination = Path(destination)
    destination.mkdir(mode=0o700, exist_ok=False)
    private = destination / 'private-inputs'
    private.mkdir(mode=0o700)
    v5.hybrid.write_json_exclusive(private / 'baseline-cache-digest.json', {'sha256': cache['private_digest']})
    protocol = dict(revision=v5.REVISION, status='frozen_before_measurement', rate=rate,
                    checkpoints=plans, protected_prefix_candidates=protected, late_weights=v5.WEIGHTS,
                    prince_control_weights=v5.WITHOUT_PRINCE,
                    method_files_sha256=frozen, reused_baseline=str(EVIDENCE),
                    reference_certificate=cache['reference_certificate'],
                    input_attestation=cache['protocol']['snapshot_attestation_hmac_sha256'],
                    cache_policy='verified exact V3 ranks reused only by checker, inside verified budget',
                    snapshot='same 852 records and order as V3/V4 comparison; English SSID-only profile',
                    data_independence='previously used regression data; no unseen holdout',
                    sources=sources['provenance'])
    v5.hybrid.write_json_exclusive(destination / 'protocol.json', protocol)
    targets = {row['password']: i for i, row in enumerate(cache['rows'])}
    lengths = {'v4_pairs': None, 'v4_masks': None, 'prince': None}
    states, pipes, processes, child_pipes = {}, {}, {}, {}
    started = time.monotonic()
    print(json.dumps(dict(status='frozen', records=len(cache['rows']), protected=protected, weights=v5.WEIGHTS)), flush=True)
    try:
        context = mp.get_context('fork')
        for family in lengths:
            if family == 'v4_masks':
                state = mask_state(sources, targets, budget)
                if state is not None:
                    states[family] = state
                    lengths[family] = state['length']
                    continue
            parent, child = context.Pipe()
            pipes[family], child_pipes[family] = parent, child
            process = context.Process(target=_worker, args=(child, family, sources, targets))
            processes[family] = process
            process.start()
            child.close()
            states[family] = dict(scanned=0, length=None, hits={})
        for iteration in range(5):
            needs = dict.fromkeys(lengths, 0)
            indexes = {}
            for profile, weights in [('v5', v5.WEIGHTS), ('without_prince', v5.WITHOUT_PRINCE)]:
                for base_length in {row['emitted'][-1] for row in cache['baseline']}:
                    indexed = v5.index(base_length, lengths, budget, protected, weights=weights, boundaries=boundaries)
                    indexes[(profile, base_length)] = indexed
                    for segment in indexed[0]:
                        if segment['family'] in needs:
                            needs[segment['family']] = max(needs[segment['family']], segment['family_start'] + segment['count'] - 1)
            pending = {}
            for family, need in needs.items():
                if lengths[family] is None and states[family]['scanned'] < need:
                    pipes[family].send(need)
                    pending[pipes[family]] = family
            if not pending:
                break
            while pending:
                for pipe in wait(list(pending), timeout=5):
                    message = pipe.recv()
                    family = pending[pipe]
                    if message['kind'] == 'progress':
                        print(json.dumps(dict(message, family=family, wall_seconds=time.monotonic() - started)), flush=True)
                    elif message['kind'] == 'result':
                        states[family] = message
                        lengths[family] = message['length']
                        del pending[pipe]
                    else:
                        raise ValueError('extension_generation_failed')
        else:
            raise ValueError('extension_fixed_point_failed')
    finally:
        for child in child_pipes.values():
            child.close()
        for family, pipe in pipes.items():
            if family in processes and processes[family].pid is not None and processes[family].is_alive():
                try:
                    pipe.send(None)
                except (EOFError, BrokenPipeError):
                    pass
        for process in processes.values():
            if process.pid is not None:
                process.join(timeout=5)
        try:
            cleanup_workers(processes.values())
        finally:
            for pipe in pipes.values():
                pipe.close()
    all_outcomes = {}
    for profile, weights in [('v5', v5.WEIGHTS), ('without_prince', v5.WITHOUT_PRINCE)]:
        values = []
        for row, base in zip(cache['rows'], cache['baseline']):
            target = targets[row['password']]
            base_length = base['emitted'][-1]
            segments, _, prefix = indexes[(profile, base_length)]
            ranks = {family: state['hits'][target] for family, state in states.items() if target in state['hits']}
            if base['hit'] is not None:
                rank = base['hit'][1]
                ranks['v3_prefix' if rank <= prefix else 'v3_continue'] = rank if rank <= prefix else rank - prefix
            hit = v5.batch.first_hit(segments, ranks)
            emitted = [v5.index(base_length, lengths, p['total_candidates'], protected, weights=weights,
                               boundaries=boundaries[:i + 1])[1] for i, p in enumerate(plans)]
            values.append(dict(hit=hit, emitted=emitted))
        all_outcomes[profile] = values
    outcomes = all_outcomes['v5']
    paired = legacy.paired_metrics(cache['baseline'], outcomes, plans)
    if any(row['lost'] != 0 or row['gained'] != 0 for row in paired[:5]):
        raise ValueError('protected_prefix_regressed')
    for name, checksum in frozen.items():
        if hashlib.sha256((ROOT / name).read_bytes()).hexdigest() != checksum:
            raise ValueError('v5_method_changed')
    checked = read_cache()
    if checked['private_digest'] != cache['private_digest']:
        raise ValueError('baseline_outcomes_changed')
    result = dict(status='completed', total=len(outcomes), rate=rate, overall=named_pairs(paired), by_dataset={},
                  protected_prefix=protected, elapsed_seconds=time.monotonic() - started,
                  same_inputs_as_v4=True, v3_cache_reused=True, data_independence=protocol['data_independence'])
    result['without_prince_vs_v3'] = named_pairs(legacy.paired_metrics(cache['baseline'], all_outcomes['without_prince'], plans), 'without_prince')
    result['prince_ablation_definition'] = 'Effect of allocating one weight unit to PRINCE instead of V3 continuation; not direct candidate-source attribution'
    result['prince_ablation'] = [dict(seconds=row['seconds'], budget=row['budget'], without_prince=row['v3'],
        with_prince=row['v4'], gained_by_prince=row['gained'], lost_to_prince=row['lost'], net=row['net'])
        for row in legacy.paired_metrics(all_outcomes['without_prince'], outcomes, plans)]
    for label in sorted(set(cache['labels'])):
        ids = [i for i, value in enumerate(cache['labels']) if value == label]
        result['by_dataset'][label] = named_pairs(legacy.paired_metrics([cache['baseline'][i] for i in ids], [outcomes[i] for i in ids], plans))
    v5.hybrid.write_json_exclusive(private / 'v5-outcomes.json', outcomes)
    v5.hybrid.write_json_exclusive(private / 'v5-without-prince-outcomes.json', all_outcomes['without_prince'])
    output_key = os.urandom(32)
    with (private / 'outcome-attestation.key').open('xb') as stream:
        os.fchmod(stream.fileno(), 0o400)
        stream.write(output_key)
    payload = (json.dumps(protocol, sort_keys=True, separators=(',', ':')).encode() + b'\0' +
               (private / 'v5-outcomes.json').read_bytes() + b'\0' +
               (private / 'v5-without-prince-outcomes.json').read_bytes() + b'\0' +
               json.dumps(cache['rows'], ensure_ascii=False, separators=(',', ':')).encode())
    v5.hybrid.write_json_exclusive(destination / 'outcome-attestation.json',
        dict(algorithm='HMAC-SHA256', scope='protocol+v5outcomes+controloutcomes+orderedinputs',
             hmac_sha256=hmac.new(output_key, payload, hashlib.sha256).hexdigest()))
    v5.hybrid.write_json_exclusive(destination / 'results.json', result)
    print(json.dumps(result['overall']), flush=True)
    return result


if __name__ == '__main__':
    try:
        run()
    except KeyboardInterrupt:
        raise SystemExit(130)
    except Exception:
        print(json.dumps(dict(status='failed', code='comparison_failed')))
        raise SystemExit(1)
