from collections import deque
import itertools
import multiprocessing as mp
from multiprocessing.connection import wait
import time

import hybrid
import oracles


LOCAL = {'v4': ('context', 'context_words'), 'v3': ('ssid_rules', 'ssid_context')}
_LOCAL_STATE = None


def schedule_index(lengths, stages, batch=256):
    consumed = dict.fromkeys(lengths, 0)
    exhausted, emitted, segments, completion = set(), 0, [], []
    for phase, (ceiling, families) in enumerate(stages):
        active = [(name, weight) for name, weight in families if name not in exhausted]
        while emitted < ceiling and active:
            stride = batch * sum(weight for _, weight in active)
            jumps = [(ceiling - emitted) // stride]
            for name, weight in active:
                if lengths[name] is not None:
                    if consumed[name] > lengths[name]:
                        raise ValueError('invalid_family_length')
                    jumps.append((lengths[name] - consumed[name]) // (batch * weight))
            cycles = min(jumps)
            if cycles:
                prefix = 0
                for name, weight in active:
                    chunk = batch * weight
                    segments.append(dict(phase=phase, family=name,
                        family_start=consumed[name] + 1, count=cycles * chunk,
                        global_start=emitted + prefix + 1, stride=stride, chunk=chunk))
                    consumed[name] += cycles * chunk
                    prefix += chunk
                emitted += cycles * stride
                continue
            cycle = min(ceiling - emitted, stride)
            total_weight = sum(weight for _, weight in active)
            quotas = [cycle * weight // total_weight for _, weight in active]
            order = sorted(range(len(active)), key=lambda i: (-(cycle * active[i][1] % total_weight), i))
            for i in order[:cycle - sum(quotas)]:
                quotas[i] += 1
            for (name, weight), quota in zip(active[:], quotas):
                available = quota if lengths[name] is None else lengths[name] - consumed[name]
                take = min(quota, available)
                if take:
                    segments.append(dict(phase=phase, family=name,
                        family_start=consumed[name] + 1, count=take,
                        global_start=emitted + 1, stride=take, chunk=take))
                    consumed[name] += take
                    emitted += take
                if take < quota:
                    exhausted.add(name)
                    active.remove((name, weight))
        completion.append(dict(phase=phase, ceiling=ceiling, emitted=emitted,
                               complete=emitted == ceiling, consumed=dict(consumed)))
    return segments, completion, consumed


def serial_index(lengths, stages, budget):
    emitted, segments, consumed = 0, [], dict.fromkeys(lengths, 0)
    for name, cap, _ in stages:
        count = min(cap, budget - emitted)
        if lengths[name] is not None:
            count = min(count, lengths[name])
        if count:
            segments.append(dict(phase=0, family=name, family_start=1, count=count,
                                 global_start=emitted + 1, stride=count, chunk=count))
        consumed[name] = count
        emitted += count
    return segments, [dict(emitted=emitted, ceiling=budget)], consumed


def global_rank(segment, local_rank):
    offset = local_rank - segment['family_start']
    if not 0 <= offset < segment['count']:
        raise ValueError('rank_outside_segment')
    return (segment['global_start'] + (offset // segment['chunk']) * segment['stride']
            + offset % segment['chunk'])


def first_hit(segments, ranks):
    hits = [(s['phase'], global_rank(s, ranks[s['family']])) for s in segments
            if s['family'] in ranks and s['family_start'] <= ranks[s['family']] < s['family_start'] + s['count']]
    return min(hits) if hits else None


class Scanner:
    def __init__(self, stream, targets):
        self.stream = iter(stream)
        self.pending = dict(targets)
        self.count, self.length, self.hits = 0, None, {}

    def scan(self, limit, progress=None):
        if limit < 0:
            raise ValueError('invalid_scan_limit')
        while self.length is None and self.count < limit:
            try:
                value = next(self.stream)
            except StopIteration:
                self.length = self.count
                break
            self.count += 1
            if value in self.pending:
                self.hits[self.pending.pop(value)] = self.count
            if progress is not None and self.count % 10000000 == 0:
                progress(self.count)
        return dict(scanned=self.count, length=self.length, hits=dict(self.hits))


def streams_for(version, context, sources, config):
    if version == 'v4':
        return {name: hybrid.rules.filtered(stream) for name, stream in
                hybrid.family_streams(context, sources).items()}
    raw_values, raw_set = hybrid.v3.prepare_raw(sources['raw'], config)
    return {name: itertools.islice(hybrid.v3.stage_source(name, context['ssid'], config,
                                   raw_values, raw_set, sources['words']), cap)
            for name, cap, _ in hybrid.v3.stage_plan(config)}


def _local_worker(job):
    index, context = job
    version, source_cache, config, targets, budget = _LOCAL_STATE
    streams = streams_for(version, context, source_cache[context['language']], config)
    result = {name: Scanner(streams[name], targets).scan(budget) for name in LOCAL[version]}
    return index, result


def _shared_worker(connection, version, sources, config, targets):
    try:
        context = hybrid.validate_context({'ssid': 'IndependentFixture'})
        scanners = {}
        while True:
            request = connection.recv()
            if request is None:
                break
            key, limit = request
            language, family = key
            if key not in scanners:
                scanners[key] = Scanner(streams_for(version, context, sources[language], config)[family], targets)
            scanner = scanners[key]
            result = scanner.scan(limit, lambda n: connection.send({'kind': 'progress', 'scanned': n}))
            connection.send({'kind': 'result', **result})
    except BaseException:
        try:
            connection.send({'kind': 'error', 'code': 'family_worker_failed'})
        except (BrokenPipeError, EOFError):
            pass
    finally:
        connection.close()


def evaluate_version(rows, version, rate, until, workers=6, progress=None):
    global _LOCAL_STATE
    if version not in ('v3', 'v4') or until not in hybrid.CHECKPOINTS or type(workers) is not int or workers < 1:
        raise ValueError('invalid_comparison_profile')
    signature = hybrid.method_signature()
    plans = [p for p in hybrid.plan(rate) if p['seconds'] <= until]
    budget = plans[-1]['total_candidates']
    contexts, context_ids, row_contexts, row_targets, targets = [], {}, [], [], {}
    for row in rows:
        if not isinstance(row, dict) or set(row) - {'ssid', 'venue', 'address', 'country', 'password'}:
            raise ValueError('invalid_record')
        if not hybrid.audit.valid(row.get('password')):
            raise ValueError('invalid_answer')
        context = hybrid.validate_context({k: v for k, v in row.items() if k != 'password'})
        key = tuple(sorted(context.items()))
        if key not in context_ids:
            context_ids[key] = len(contexts)
            contexts.append(context)
        row_contexts.append(context_ids[key])
        if row['password'] not in targets:
            targets[row['password']] = len(targets)
        row_targets.append(targets[row['password']])
    if not rows:
        raise ValueError('empty_input')
    source_cache = {}
    for context in contexts:
        language = context['language']
        if language not in source_cache:
            if version == 'v4':
                source_cache[language] = hybrid.load_sources(language)
            else:
                raw, words, manifest = hybrid.v3.load_words()
                source_cache[language] = dict(raw=raw, words=words, provenance=manifest)
    config = None
    if version == 'v3':
        config = hybrid.v3.json.loads((hybrid.v3.ROOT / 'config.json').read_text())
        hybrid.v3.validate_config(config)
        config = dict(config, budget_per_pair=budget)
    stages = [(p['total_candidates'], p['family_weights']) for p in plans]
    names = [name for name, _ in plans[-1]['family_weights']] if version == 'v4' else [
        name for name, _, _ in hybrid.v3.stage_plan(config)]
    common_names = [name for name in names if name not in LOCAL[version]]
    context_results = {}
    _LOCAL_STATE = (version, source_cache, config, targets, budget)
    process_context = mp.get_context('fork')
    with process_context.Pool(processes=workers) as pool:
        for index, result in pool.imap_unordered(_local_worker, enumerate(contexts), chunksize=1):
            context_results[index] = result
            if progress is not None:
                progress(dict(kind='contexts', version=version, completed=len(context_results), total=len(contexts)))
    shared, processes, pipes, child_pipes = {}, {}, {}, {}
    indexes = {}
    try:
        tasks = []
        for language in source_cache:
            for name in common_names:
                key = (language, name)
                analytic = None
                if version == 'v4' and name == 'numeric':
                    analytic = oracles.numeric_oracle(targets)
                elif version == 'v4' and name.startswith('mask'):
                    analytic = oracles.mask_oracle(source_cache[language]['words'], int(name[4:]), targets)
                shared[key] = analytic or dict(length=None, hits={}, scanned=0)
                if analytic is not None:
                    continue
                tasks.append(key)
        assignments = {key: index % min(workers, len(tasks)) for index, key in enumerate(tasks)}
        for worker in range(min(workers, len(tasks))):
                parent, child = process_context.Pipe()
                pipes[worker], child_pipes[worker] = parent, child
                process = process_context.Process(target=_shared_worker,
                    args=(child, version, source_cache, config, targets))
                processes[worker] = process
                process.start()
                child.close()
        for iteration in range(len(common_names) * len(source_cache) + 2):
            needed = dict.fromkeys(shared, 0)
            for index, context in enumerate(contexts):
                language = context['language']
                lengths = {name: shared[(language, name)]['length'] for name in common_names}
                lengths.update({name: context_results[index][name]['length'] for name in LOCAL[version]})
                if version == 'v4':
                    indexed = schedule_index(lengths, stages)
                else:
                    indexed = serial_index(lengths, hybrid.v3.stage_plan(config), budget)
                indexes[index] = indexed
                for name in common_names:
                    needed[(language, name)] = max(needed[(language, name)], indexed[2][name])
            pending, queues = {}, {pipe: deque() for pipe in pipes.values()}
            for key, limit in needed.items():
                if shared[key]['length'] is None and shared[key]['scanned'] < limit:
                    queues[pipes[assignments[key]]].append((key, limit))
            for pipe, queue in queues.items():
                if queue:
                    key, limit = queue.popleft()
                    pipe.send((key, limit))
                    pending[pipe] = key
            if not pending:
                break
            while pending:
                ready = wait(list(pending), timeout=5)
                for pipe in ready:
                    message = pipe.recv()
                    key = pending[pipe]
                    if message['kind'] == 'progress':
                        if progress is not None:
                            progress(dict(message, version=version, family=key[1], language=key[0]))
                    elif message['kind'] == 'result':
                        shared[key] = message
                        if queues[pipe]:
                            key, limit = queues[pipe].popleft()
                            pipe.send((key, limit))
                            pending[pipe] = key
                        else:
                            del pending[pipe]
                    else:
                        raise ValueError('shared_evaluation_failed')
        else:
            raise ValueError('family_length_fixed_point_failed')
    finally:
        for pipe in child_pipes.values():
            pipe.close()
        for key, pipe in pipes.items():
            if key in processes and processes[key].pid is not None and processes[key].is_alive():
                try:
                    pipe.send(None)
                except (BrokenPipeError, EOFError):
                    pass
        for key, process in processes.items():
            if process.pid is None:
                continue
            process.join(timeout=5)
            if process.is_alive():
                process.terminate()
                process.join(timeout=5)
        for pipe in pipes.values():
            pipe.close()
    outcomes = []
    for context_index, target in zip(row_contexts, row_targets):
        language = contexts[context_index]['language']
        ranks = {name: state['hits'][target] for (lang, name), state in shared.items()
                 if lang == language and target in state['hits']}
        ranks.update({name: state['hits'][target] for name, state in context_results[context_index].items()
                      if target in state['hits']})
        segments, completion, _ = indexes[context_index]
        hit = first_hit(segments, ranks)
        emitted = [c['emitted'] for c in completion] if version == 'v4' else [
            min(completion[0]['emitted'], p['total_candidates']) for p in plans]
        outcomes.append(dict(hit=hit, emitted=emitted))
    curve = []
    for phase, p in enumerate(plans):
        matched = sum(bool(r['hit'] is not None and r['hit'][0] <= phase and
                           r['hit'][1] <= p['total_candidates']) for r in outcomes)
        exhausted = sum(r['emitted'][phase] < p['total_candidates'] and not (
            r['hit'] is not None and r['hit'][0] <= phase and r['hit'][1] <= p['total_candidates']) for r in outcomes)
        curve.append(dict(seconds=p['seconds'], budget=p['total_candidates'], matched=matched,
                          source_exhausted=exhausted, budget_reached=len(rows) - matched - exhausted))
    hybrid.method_signature()
    report = dict(version=version, revision=hybrid.REVISION if version == 'v4' else 'v3-budget-extended',
                  total=len(rows), unique_contexts=len(contexts), rate=str(rate), curve=curve,
                  method=signature, evaluator='exact_family_ranks_and_indexed_reference_schedule',
                  v3_rules_unchanged_only_budget_overridden=version == 'v3',
                  v3_effective_config=config if version == 'v3' else None,
                  sources={language: source['provenance'] for language, source in source_cache.items()})
    return report, outcomes
