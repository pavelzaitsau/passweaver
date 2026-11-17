import itertools
import re

import audit


LIMIT = 2_000_000
GENERIC = {'hotel', 'hostel', 'apart', 'apartments', 'cafe', 'coffee', 'coffe',
           'restaurant', 'wifi', 'guest', 'free', '2g', '5g'}
SYMBOLS = ('!', '@', '#', '$', '*', '_', '-', '.')


def numeric_affixes():
    values = list(audit.SUFFIXES)
    values.extend(str(digit) * length for length in range(2, 7) for digit in range(10))
    for sequence in ('01234567890123456789', '98765432109876543210'):
        values.extend(sequence[start:start + length] for length in range(2, 9) for start in range(10))
    values.extend(str(year) for year in range(1990, 2031))
    values.extend(str(left) + str(right) for left in range(10) for right in range(10))
    values.extend((str(left) + str(right)) * 2 for left in range(10) for right in range(10))
    return tuple(dict.fromkeys(value for value in values if value.isdigit()))


NUMBERS = numeric_affixes()


def bases(ssid):
    split = re.sub(r'(?<=[a-z])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])', ' ', ssid)
    tokens = re.findall(r'[^\W_]+', split, flags=re.UNICODE)
    names = [token for token in tokens if token.casefold() not in GENERIC]
    groups = [tokens, names, list(reversed(names))]
    values = [ssid] + [token for token in tokens if len(token) >= 3]
    values.extend(separator.join(group) for group in groups if group for separator in ('', '-', '_', ' '))
    if names:
        name = ''.join(names)
        for word in ('wifi', 'guest', 'internet', 'welcome', 'password'):
            values.extend((name + word, word + name, name.capitalize() + word.capitalize()))
    return tuple(dict.fromkeys(values))


def raw_candidates(ssid):
    yield from audit.ssid_candidates(ssid)
    seeds = tuple(dict.fromkeys(value for base in bases(ssid) for value in audit.variants(base)))
    for base in bases(ssid):
        yield from audit.transforms(base)
    for seed in seeds:
        for number in NUMBERS:
            yield seed + number
            yield number + seed
    for seed in seeds:
        for number, symbol in itertools.product(NUMBERS, SYMBOLS):
            yield seed + symbol + number
            yield seed + number + symbol
            yield symbol + seed + number
            yield number + symbol + seed


def candidates(ssid, limit=LIMIT):
    seen = set()
    if limit <= 0:
        return
    for candidate in raw_candidates(ssid):
        if not audit.valid(candidate) or candidate in seen:
            continue
        seen.add(candidate)
        yield candidate
        if len(seen) >= limit:
            return
