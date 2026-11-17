import argparse
from collections import Counter, defaultdict
import hashlib
import itertools
import json
import os
from pathlib import Path
import re
import time
import sys
import tempfile
import uuid

import audit
import expanded_ssid
import rules


ROOT = Path(__file__).resolve().parent
LAB = ROOT


def validate_config(config):
    if not isinstance(config, dict):
        raise ValueError('Invalid configuration')
    positive = ('budget_per_pair', 'assumed_checks_per_second')
    nonnegative = ('raw_limit', 'ssid_rules_limit', 'ssid_expanded_limit',
                   'ssid_context_limit', 'context_word_limit', 'broad_word_limit',
                   'word_rules_limit', 'pair_word_limit', 'family_batch')
    if set(config) != set(positive + nonnegative + ('version', 'pair_ordering')):
        raise ValueError('Invalid configuration fields')
    if not isinstance(config['version'], str) or not re.fullmatch(r'[a-z0-9][a-z0-9._-]{0,63}', config['version']):
        raise ValueError('Invalid configuration version')
    for key in positive + nonnegative:
        value = config.get(key)
        if type(value) is not int or value < (1 if key in positive else 0):
            raise ValueError('Invalid configuration: ' + key)
    if config.get('pair_ordering') not in ('sum', 'product'):
        raise ValueError('Invalid configuration: pair_ordering')


def valid_ssid(ssid):
    if not isinstance(ssid, str) or any(char in ssid for char in '\0\r\n'):
        return False
    try:
        return 1 <= len(ssid.encode('utf-8')) <= 32
    except UnicodeEncodeError:
        return False


def parse_input(data, input_format):
    if input_format not in ('jsonl', 'text', 'legacy-text'):
        raise ValueError('Invalid input format')
    rows = []
    for number, line in enumerate(data.decode('utf-8-sig').split('\n'), 1):
        if line.endswith('\r'):
            line = line[:-1]
        if not line.strip():
            continue
        if input_format == 'jsonl':
            record = json.loads(line)
            if not isinstance(record, dict) or set(record) - {'ssid', 'password', 'group'}:
                raise ValueError('Invalid record on line ' + str(number))
        else:
            if line.count('/') != 1:
                raise ValueError('Ambiguous separator on line ' + str(number))
            ssid, password = line.split('/')
            if input_format == 'legacy-text':
                ssid, password = ssid.strip(), password.strip()
            record = {'ssid': ssid, 'password': password}
        ssid, password = record.get('ssid'), record.get('password')
        group = record.get('group', 'unclassified')
        if not valid_ssid(ssid) or not audit.valid(password) or group not in ('previous', 'new', 'unclassified'):
            raise ValueError('Invalid record on line ' + str(number))
        rows.append({'line': number, 'ssid': ssid, 'password': password, 'group': group})
    if not rows:
        raise ValueError('Empty input')
    return rows


def consume(results, passwords, candidates, cap, budget, stage):
    indexes = [i for i, row in enumerate(results) if not row['matched'] and row['attempts'] < budget]
    if not indexes:
        return 0
    offsets = {i:results[i]['attempts'] for i in indexes}
    pending = defaultdict(list)
    for i in indexes:
        pending[passwords[i]].append(i)
    limit = max(min(cap, budget - offsets[i]) for i in indexes)
    position = 0
    for position, candidate in enumerate(itertools.islice(candidates, limit), 1):
        for i in pending.pop(candidate, ()):
            count = offsets[i] + position
            if count <= budget:
                results[i].update(matched=True, stage=stage, attempts=count)
        if not pending:
            break
    for i in indexes:
        if not results[i]['matched']:
            results[i]['attempts'] = min(budget, offsets[i] + position)
    return position


def load_words():
    manifest = json.loads((LAB / 'wordlists/general-v2-manifest.json').read_text())
    sources = {}
    for source in manifest['sources']:
        path = LAB / 'wordlists' / source['filename']
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != source['prepared_sha256']:
            raise ValueError('Wordlist checksum mismatch')
        sources[source['id']] = raw.decode('utf-8').splitlines()
    old = []
    for name, expected in audit.WORDLISTS:
        raw_bytes = (LAB / 'wordlists' / name).read_bytes()
        if hashlib.sha256(raw_bytes).hexdigest() != expected:
            raise ValueError('Original wordlist checksum mismatch')
        old.append(list(dict.fromkeys(raw_bytes.decode('utf-8').splitlines())))
    raw = list(dict.fromkeys(itertools.chain(sources['ncsc-common-100k'], old[0],
                                             sources['symspell-english-80k'], old[1])))
    lexical = list(dict.fromkeys(word.lower() for word in itertools.chain(
        sources['symspell-english-80k'], old[1], old[0]) if word.isascii() and word.isalpha()))
    return raw, lexical, manifest


def ssid_stream(ssid, config):
    seeds = list(expanded_ssid.bases(ssid))
    extensions = itertools.chain.from_iterable(rules.word_families(seeds))
    common = itertools.chain(audit.ssid_candidates(ssid), extensions,
                             expanded_ssid.candidates(ssid, limit=config['ssid_expanded_limit']))
    yield from itertools.islice(rules.filtered(common), config['ssid_rules_limit'])


def aggregate(selected):
    hits = [row for row in selected if row['matched']]
    return {'total':len(selected), 'matched':len(hits),
            'matched_percent':100 * len(hits) / len(selected) if selected else None,
            'by_stage':dict(Counter(row['stage'] for row in hits)),
            'curve':[{'modeled_seconds':seconds,
                      'matched':sum(row['modeled_seconds'] <= seconds for row in hits)}
                     for seconds in (1, 10, 60, 300)]}


def stage_plan(config):
    return (
        ('dictionary_raw', config['raw_limit'], False),
        ('ssid_rules', config['ssid_rules_limit'], True),
        ('ssid_context', config['ssid_context_limit'], True),
        ('dictionary_rules', config['word_rules_limit'], False),
        ('word_pairs', config['budget_per_pair'], False),
    )


def stage_source(stage, ssid, config, raw_values, raw_set, words):
    if stage == 'dictionary_raw':
        return iter(raw_values)
    if stage == 'ssid_rules':
        return ssid_stream(ssid, config)
    if stage == 'ssid_context':
        context_words = list(dict.fromkeys(['wifi', 'guest', 'free', 'internet', 'welcome',
                                           'password', 'hotel', 'cafe'] + words))
        return rules.filtered(rules.context_candidates(ssid, context_words,
                              config['context_word_limit']), excluded=raw_set)
    if stage == 'dictionary_rules':
        families = rules.word_families(words, config['broad_word_limit'])
        source = rules.mix(families, config['family_batch']) if config['family_batch'] else itertools.chain.from_iterable(families)
    elif stage == 'word_pairs':
        source = rules.pair_candidates(words[:config['pair_word_limit']], config['pair_ordering'])
    else:
        raise ValueError('Unknown stage')
    return rules.filtered(source, excluded=raw_set)


def prepare_raw(raw, config):
    values = tuple(rules.filtered(raw))
    attempted = frozenset(values[:min(config['raw_limit'], config['budget_per_pair'])])
    return values, attempted


def candidates_for_ssid(ssid, config, raw, words):
    validate_config(config)
    if not valid_ssid(ssid):
        raise ValueError('Invalid SSID')
    raw_values, raw_set = prepare_raw(raw, config)
    remaining = config['budget_per_pair']
    for stage, cap, _ in stage_plan(config):
        if remaining <= 0:
            return
        source = stage_source(stage, ssid, config, raw_values, raw_set, words)
        for candidate in itertools.islice(source, min(cap, remaining)):
            remaining -= 1
            yield stage, candidate


def evaluate(rows, config, raw, words):
    validate_config(config)
    budget = config['budget_per_pair']
    results = [{k: row[k] for k in ('line', 'ssid', 'group')} for row in rows]
    for result in results:
        result.update(matched=False, stage=None, attempts=0)
    passwords = [row['password'] for row in rows]
    raw_values, raw_set = prepare_raw(raw, config)
    work = {}
    for stage, cap, per_ssid in stage_plan(config):
        if per_ssid:
            for i, row in enumerate(results):
                if row['matched'] or row['attempts'] >= budget:
                    continue
                source = stage_source(stage, row['ssid'], config, raw_values, raw_set, words)
                consume([row], [passwords[i]], source, cap, budget, stage)
        else:
            source = stage_source(stage, None, config, raw_values, raw_set, words)
            work[stage] = consume(results, passwords, source, cap, budget, stage)
    for row in results:
        row['modeled_seconds'] = row['attempts'] / config['assumed_checks_per_second']
        assert row['attempts'] <= budget
    return results, work


class SafeParser(argparse.ArgumentParser):
    def error(self, message):
        raise ValueError('invalid_arguments')


def main(argv=None):
    os.umask(0o077)
    phase = 'invalid_arguments'
    started_total = time.monotonic()
    try:
        parser = SafeParser(description='Offline candidate-rank evaluation on supplied test answers.')
        parser.add_argument('--input', type=Path, required=True)
        parser.add_argument('--format', choices=('jsonl', 'text', 'legacy-text'), default='jsonl')
        parser.add_argument('--config', type=Path, default=ROOT / 'config.json')
        parser.add_argument('--output', type=Path, default=ROOT / 'results')
        args = parser.parse_args(argv)
        phase = 'configuration_invalid'
        config_bytes = args.config.read_bytes()
        config = json.loads(config_bytes)
        validate_config(config)
        phase = 'wordlist_invalid'
        raw, words, manifest = load_words()
        phase = 'input_invalid'
        input_bytes = args.input.read_bytes()
        rows = parse_input(input_bytes, args.format)
        phase = 'evaluation_failed'
        started = time.monotonic()
        results, _ = evaluate(rows, config, raw, words)
        analysis_seconds = time.monotonic() - started
        phase = 'input_changed'
        if args.input.read_bytes() != input_bytes:
            raise ValueError('input_changed')
        report = {
            'version': config['version'],
            'mode': 'offline_known_password_candidate_rank_simulation',
            'input_id': str(uuid.uuid4()),
            'input_format': args.format,
            'config_sha256': hashlib.sha256(config_bytes).hexdigest(),
            'config': config,
            'source_sha256': {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                              for p in sorted(ROOT.glob('*.py'))},
            'wordlist_manifest': manifest,
            'candidate_counting': 'Valid attempts; bounded block deduplication; cross-stage and cross-block repeats may remain',
            'overall': aggregate(results),
            'groups': {group: aggregate([row for row in results if row['group'] == group])
                       for group in ('previous', 'new', 'unclassified')},
            'groups_are_user_supplied_not_proof_of_independence': True,
            'duplicate_input_pairs': len(rows) - len({(row['ssid'], row['password']) for row in rows}),
            'privacy': {'per_network_details': False, 'exact_success_ranks': False,
                        'input_fingerprint': False, 'answer_dependent_work_counts': False},
            'actual_analysis_wall_seconds': analysis_seconds,
            'actual_pre_report_wall_seconds': time.monotonic() - started_total,
        }
        phase = 'output_unavailable'
        args.output.mkdir(mode=0o700, parents=True, exist_ok=True)
        destination = Path(tempfile.mkdtemp(prefix=config['version'] + '-', dir=args.output))
        output = destination / 'summary-without-passwords.json'
        with output.open('x', encoding='utf-8') as stream:
            os.fchmod(stream.fileno(), 0o600)
            stream.write(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
        print(json.dumps({'status': 'completed', 'overall': report['overall'],
                          'report': str(output.resolve())}, ensure_ascii=False))
        return 0
    except KeyboardInterrupt:
        print(json.dumps({'status': 'cancelled'}))
        return 130
    except Exception:
        print(json.dumps({'status': 'failed', 'code': phase}))
        return 1


if __name__ == '__main__':
    sys.exit(main())
