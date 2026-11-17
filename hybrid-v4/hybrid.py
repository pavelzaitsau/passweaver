from collections import Counter, deque
from decimal import Decimal, InvalidOperation, ROUND_FLOOR, localcontext
import hashlib
import heapq
import itertools
import json
import os
from pathlib import Path
import sys
import time
import unicodedata

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent / 'final-algorithm'))
import audit
import engine as v3
import expanded_ssid
import rules

CHECKPOINTS = (10, 30, 120, 300, 600, 1800, 3600, 7200)
REVISION = 'v4.1-experimental'
PHASES = (
    (10, [('raw', 4), ('context', 4), ('simple', 2)]),
    (30, [('context_words', 3), ('simple', 2), ('mask2', 3), ('raw', 1), ('context', 1)]),
    (120, [('pairs', 4), ('mutations', 3), ('context_words', 2), ('mask2', 1)]),
    (300, [('pairs', 3), ('pair_digits', 3), ('mask3', 3), ('mutations', 1)]),
    (600, [('pairs', 3), ('mask4', 3), ('pair_digits', 2), ('context_words', 1), ('mutations', 1)]),
    (1800, [('mask4', 3), ('pairs', 3), ('triples', 2), ('numeric', 2)]),
    (3600, [('mask5', 4), ('triples', 3), ('pairs', 2), ('numeric', 1)]),
    (7200, [('mask6', 4), ('mask5', 2), ('triples', 2), ('pairs', 1), ('numeric', 1)]),
)
COUNTRIES = {**dict.fromkeys(('US', 'GB', 'IE', 'AU', 'NZ'), 'en'),
             **dict.fromkeys(('DE', 'AT'), 'de'), 'PL': 'pl', 'RU': 'ru',
             'FR': 'fr', 'ES': 'es', 'IT': 'it', 'PT': 'pt', 'BR': 'pt',
             'UA': 'uk', 'NL': 'nl', 'TR': 'tr', 'CZ': 'cs'}
TRANSLIT = dict(zip('абвгдеёжзийклмнопрстуфхцчшщъыьэюяіїєґ',
                    ('a', 'b', 'v', 'g', 'd', 'e', 'yo', 'zh', 'z', 'i', 'y', 'k', 'l',
                     'm', 'n', 'o', 'p', 'r', 's', 't', 'u', 'f', 'kh', 'ts', 'ch', 'sh',
                     'shch', '', 'y', '', 'e', 'yu', 'ya', 'i', 'yi', 'ye', 'g')))
METHOD_PATHS = [ROOT / 'hybrid.py', ROOT / 'batch.py', ROOT / 'oracles.py', ROOT / 'wordlists/manifest.json',
                ROOT.parent / 'final-algorithm/config.json',
                ROOT.parent / 'final-algorithm/wordlists/general-v2-manifest.json',
                *[ROOT.parent / 'final-algorithm' / name for name in
                  ('engine.py', 'audit.py', 'rules.py', 'expanded_ssid.py')]]
LOADED_METHOD_HASHES = {str(path.relative_to(ROOT.parent)): hashlib.sha256(path.read_bytes()).hexdigest()
                        for path in METHOD_PATHS}


def method_signature():
    current = {str(path.relative_to(ROOT.parent)): hashlib.sha256(path.read_bytes()).hexdigest()
               for path in METHOD_PATHS}
    if current != LOADED_METHOD_HASHES:
        raise ValueError('method_changed_during_run')
    return {'files_sha256': current, 'dedup_window': 200000, 'dedup_scope': 'per_family', 'scheduler_batch': 256,
            'active_time_model': 'floor(rate * cumulative_seconds)',
            'family_policy': 'prior families persist with minimum weight 1; explicit weights override'}


def plan(rate):
    if isinstance(rate, bool):
        raise ValueError('invalid_rate')
    try:
        speed = Decimal(str(rate))
    except InvalidOperation:
        raise ValueError('invalid_rate') from None
    if not speed.is_finite() or speed <= 0 or speed > 10 ** 12:
        raise ValueError('invalid_rate')
    result, previous, active = [], 0, {}
    for seconds, families in PHASES:
        active = {name: 1 for name in active}
        active.update(families)
        with localcontext() as context:
            context.prec = max(28, len(speed.as_tuple().digits) + 5)
            total = int((speed * seconds).to_integral_value(rounding=ROUND_FLOOR))
        result.append({'seconds': seconds, 'total_candidates': total,
                       'additional_candidates': total - previous, 'family_weights': list(active.items())})
        previous = total
    return result


def validate_context(value):
    if not isinstance(value, dict) or set(value) - {'ssid', 'venue', 'address', 'country'}:
        raise ValueError('invalid_context')
    if not v3.valid_ssid(value.get('ssid')):
        raise ValueError('invalid_ssid')
    result = dict(value)
    for name in ('venue', 'address'):
        text = value.get(name, '')
        if not isinstance(text, str) or len(text) > 256 or any(c in text for c in '\0\r\n'):
            raise ValueError('invalid_context')
        try:
            text.encode('utf-8')
        except UnicodeEncodeError:
            raise ValueError('invalid_context') from None
    country = value.get('country')
    if country is not None and (not isinstance(country, str) or country not in COUNTRIES):
        raise ValueError('unsupported_country')
    result['language'] = COUNTRIES[country] if country else 'en'
    return result


def interleave(pools):
    active = deque(iter(pool) for pool in pools)
    while active:
        source = active.popleft()
        try:
            yield next(source)
            active.append(source)
        except StopIteration:
            pass


def load_sources(language):
    manifest = json.loads((ROOT / 'wordlists/manifest.json').read_text())
    ids = [source['id'] for source in manifest['sources']]
    if len(ids) != len(set(ids)):
        raise ValueError('duplicate_source_id')
    raw_pools, lexical_pools, provenance = [], [], []
    required = {'ncsc-common-100k', 'seclists-10k', 'symspell-english-80k',
                'english-frequency-10k', 'frequencywords-en', 'frequencywords-' + language}
    for source in manifest['sources']:
        if source['id'] not in required:
            continue
        filename = source['filename']
        if Path(filename).name != filename:
            raise ValueError('invalid_wordlist_path')
        data = (ROOT / 'wordlists' / filename).read_bytes()
        if hashlib.sha256(data).hexdigest() != source['sha256']:
            raise ValueError('wordlist_checksum_mismatch')
        values = data.decode('utf-8').splitlines()
        raw_pools.append(values)
        lexical_pools.append(list(dict.fromkeys(x.lower() for x in values if x.isalpha())))
        provenance.append(source)
    if {s['id'] for s in provenance} != required:
        raise ValueError('missing_language_source')
    return {'raw': list(dict.fromkeys(interleave(raw_pools))),
            'words': list(dict.fromkeys(interleave(lexical_pools))), 'provenance': provenance}


def forms(word):
    transliterated = ''.join(TRANSLIT.get(c, c) for c in word.lower())
    folded = ''.join(c for c in unicodedata.normalize('NFKD', word) if not unicodedata.combining(c))
    return tuple(dict.fromkeys((word, word.lower(), word.capitalize(), word.upper(),
                               folded.lower(), transliterated)))


def context_seeds(context):
    fields = []
    for name in ('ssid', 'venue', 'address'):
        text = context.get(name, '')
        if text:
            fields.append(tuple(dict.fromkeys(v for seed in expanded_ssid.bases(text)
                                               for v in (seed, *forms(seed)))))
    return tuple(dict.fromkeys(interleave(fields)))[:256]


def simple_words(words):
    for word in words:
        for form in forms(word):
            yield form
            for suffix in tuple(str(n) for n in range(10)) + ('123', '1234', '!', '2024', '2025', '2026'):
                yield form + suffix
                yield suffix + form


def pair_stream(words, digits=False):
    for left, right in rules.ordered_pairs(words[:50000], 'product'):
        for a, b in itertools.product(forms(left)[:3], forms(right)[:3]):
            yield a + b
            if digits:
                for n in range(10):
                    yield str(n) + a + b
                    yield a + b + str(n)
                    yield a + str(n) + b
            else:
                for sep in ('-', '_', ' '):
                    yield a + sep + b


def word_masks(words, width):
    pool = words[:30000]
    for wi, ni in ranked_indices(len(pool), 10 ** width):
        value = str(ni).zfill(width)
        for form in forms(pool[wi])[:3]:
            yield form + value
            yield value + form


def ranked_indices(rows, columns):
    queue = [(i + 1, i, 0) for i in range(rows)] if columns else []
    heapq.heapify(queue)
    while queue:
        _, left, right = heapq.heappop(queue)
        yield left, right
        if right + 1 < columns:
            heapq.heappush(queue, ((left + 1) * (right + 2), left, right + 1))


def triple_stream(words):
    pool = words[:128]
    for n in range(len(pool)):
        indexes = itertools.chain(((n, i, j) for i in range(n + 1) for j in range(n + 1)),
                                  ((i, n, j) for i in range(n) for j in range(n + 1)),
                                  ((i, j, n) for i in range(n) for j in range(n)))
        for indexes3 in indexes:
            values = [pool[i] for i in indexes3]
            for sep in ('', '-', '_', ' '):
                yield sep.join(values)
                yield sep.join(x.capitalize() for x in values)


def numeric_stream():
    for width in (8, 9, 10):
        for n in range(10 ** width):
            yield str(n).zfill(width)


def family_streams(context, sources):
    seeds, words = context_seeds(context), sources['words']
    return {'raw': iter(sources['raw']), 'context': simple_words(seeds),
            'simple': simple_words(words),
            'context_words': (a + sep + b for word in words[:5000] for seed in seeds[:48]
                              for a, b in ((seed, word), (word, seed)) for sep in ('', '-', '_', ' ')),
            'pairs': pair_stream(words), 'pair_digits': pair_stream(words, True),
            'mutations': rules.mix(rules.word_families(words, 30000), 10000),
            'triples': triple_stream(words), 'numeric': numeric_stream(),
            **{'mask' + str(n): word_masks(words, n) for n in range(2, 7)}}


def schedule(streams, stages, batch=256, window=200000):
    if type(batch) is not int or batch <= 0 or type(window) is not int or window <= 0:
        raise ValueError('invalid_scheduler_limits')
    streams = {name: iter(rules.filtered(source, window=window)) for name, source in streams.items()}
    exhausted, emitted = set(), 0
    for phase, (ceiling, families) in enumerate(stages):
        active = [(name, weight) for name, weight in families if name not in exhausted]
        while emitted < ceiling and active:
            cycle = min(ceiling - emitted, batch * sum(weight for _, weight in active))
            total_weight = sum(weight for _, weight in active)
            quotas = [cycle * weight // total_weight for _, weight in active]
            remainders = sorted(range(len(active)),
                                key=lambda i: (-(cycle * active[i][1] % total_weight), i))
            for i in remainders[:cycle - sum(quotas)]:
                quotas[i] += 1
            for (name, weight), quota in zip(active[:], quotas):
                accepted = 0
                while accepted < quota and emitted < ceiling:
                    try:
                        value = next(streams[name])
                    except StopIteration:
                        exhausted.add(name)
                        active.remove((name, weight))
                        break
                    emitted += 1
                    accepted += 1
                    yield phase, name, value


def candidates(context, sources, rate, until):
    if until not in CHECKPOINTS:
        raise ValueError('invalid_checkpoint')
    context = validate_context({k: v for k, v in context.items() if k != 'language'})
    stages = [(p['total_candidates'], p['family_weights']) for p in plan(rate) if p['seconds'] <= until]
    yield from schedule(family_streams(context, sources), stages)


def export(path, context, sources, rate, until, maximum=None):
    if maximum is not None and (type(maximum) is not int or maximum <= 0):
        raise ValueError('invalid_candidate_limit')
    plan(rate)
    if until not in CHECKPOINTS:
        raise ValueError('invalid_checkpoint')
    context = validate_context({k: v for k, v in context.items() if k != 'language'})
    signature = method_signature()
    source = candidates(context, sources, rate, until)
    if maximum is not None:
        source = itertools.islice(source, maximum)
    count, digest, by_family = 0, hashlib.sha256(), Counter()
    output = Path(path)
    stream = output.open('xb')
    try:
        with stream:
            os.fchmod(stream.fileno(), 0o600)
            for _, family, value in source:
                data = (value + '\n').encode('utf-8')
                stream.write(data)
                digest.update(data)
                count += 1
                by_family[family] += 1
            method_signature()
    except BaseException:
        output.unlink(missing_ok=True)
        raise
    return {'candidates': count, 'by_family': dict(by_family), 'sha256': digest.hexdigest(),
            'method': signature,
            'modeled_active_seconds': str(Decimal(count) / Decimal(str(rate))),
            'wordlist_autohex_disable_required': True}


def evaluate(rows, rate, until, loader=load_sources):
    signature = method_signature()
    if not isinstance(rows, list) or not rows:
        raise ValueError('empty_input')
    plan_rows = [p for p in plan(rate) if p['seconds'] <= until]
    if until not in CHECKPOINTS:
        raise ValueError('invalid_checkpoint')
    validated = []
    for row in rows:
        if not isinstance(row, dict) or set(row) - {'ssid', 'venue', 'address', 'country', 'password'}:
            raise ValueError('invalid_record')
        if not audit.valid(row.get('password')):
            raise ValueError('invalid_answer')
        context = validate_context({key: val for key, val in row.items() if key != 'password'})
        validated.append((context, row['password']))
    counts, reached, exhausted, matched, cache = Counter(), Counter(), Counter(), 0, {}
    for context, password in validated:
        language = context['language']
        if language not in cache:
            cache[language] = loader(language)
        hit, phase_counts = None, {}
        for position, (phase, _, candidate) in enumerate(candidates(context, cache[language], rate, until), 1):
            phase_counts[phase] = position
            if candidate == password:
                matched += 1
                hit = (phase, position)
                break
        emitted = 0
        for phase, p in enumerate(plan_rows):
            emitted = phase_counts.get(phase, emitted)
            if hit is not None and hit[0] <= phase and hit[1] <= p['total_candidates']:
                counts[p['seconds']] += 1
            elif emitted == p['total_candidates']:
                reached[p['seconds']] += 1
            else:
                exhausted[p['seconds']] += 1
    method_signature()
    return {'version': REVISION, 'mode': 'offline_known_answer_simulation', 'method': signature,
            'rate': str(rate), 'until_seconds': until,
            'overall': {'total': len(rows), 'matched': matched},
            'curve': [{'seconds': p['seconds'], 'matched': counts[p['seconds']],
                       'budget_reached': reached[p['seconds']], 'source_exhausted': exhausted[p['seconds']]}
                      for p in plan_rows],
            'sources': {language: sources['provenance'] for language, sources in cache.items()},
            'privacy': 'aggregate_only_no_input_digest_or_success_ranks',
            'not_a_gpu_benchmark': True}


def write_json_exclusive(path, value):
    data = (json.dumps(value, ensure_ascii=False, indent=2) + '\n').encode('utf-8')
    path = Path(path)
    stream = path.open('xb')
    try:
        with stream:
            os.fchmod(stream.fileno(), 0o600)
            stream.write(data)
    except BaseException:
        path.unlink(missing_ok=True)
        raise


def main(argv=None):
    os.umask(0o077)
    started = time.monotonic()
    try:
        parser = v3.SafeParser(description='Experimental cumulative offline hybrid V4.')
        parser.add_argument('command', choices=('plan', 'generate', 'evaluate'))
        parser.add_argument('--rate', required=True)
        parser.add_argument('--until', type=int, choices=CHECKPOINTS, default=7200)
        parser.add_argument('--context', type=Path)
        parser.add_argument('--input', type=Path)
        parser.add_argument('--output', type=Path)
        parser.add_argument('--max-candidates', type=int)
        args = parser.parse_args(argv)
        plan(args.rate)
        if args.command == 'plan':
            result = {'version': REVISION, 'rate': args.rate, 'checkpoints': plan(args.rate)}
        elif args.command == 'generate':
            context = validate_context(json.loads(args.context.read_text()))
            sources = load_sources(context['language'])
            result = export(args.output, context, sources, args.rate, args.until, args.max_candidates)
            result['sources'] = sources['provenance']
        else:
            data = args.input.read_bytes()
            rows = [json.loads(line) for line in data.decode('utf-8-sig').split('\n') if line.strip()]
            result = evaluate(rows, args.rate, args.until)
            if args.input.read_bytes() != data:
                raise ValueError('input_changed')
            result['wall_seconds'] = time.monotonic() - started
            write_json_exclusive(args.output, result)
        print(json.dumps({'status': 'completed', **result}, ensure_ascii=False))
        return 0
    except KeyboardInterrupt:
        print(json.dumps({'status': 'cancelled'}))
        return 130
    except Exception:
        print(json.dumps({'status': 'failed', 'code': 'invalid_input_or_operation_failed'}))
        return 1


if __name__ == '__main__':
    sys.exit(main())
