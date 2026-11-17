from collections import deque
import heapq
import itertools

import audit
import expanded_ssid


def forms(word):
    return tuple(audit.variants(word))


def word_families(words, broad_limit=30000):
    broad = words[:broad_limit]
    short = words[:3000]
    variants = lambda pool: (value for word in pool for value in forms(word))
    yield variants(words)
    yield (value + affix for value in variants(broad) for affix in audit.SUFFIXES)
    yield (candidate for value in variants(broad) for n in range(100)
           for candidate in (value + f'{n:02d}', f'{n:02d}' + value))
    yield (candidate for value in variants(words[:2000]) for year in range(1800, 2031)
           for candidate in (value + str(year), str(year) + value))
    yield (value[:position] + char + value[position:]
           for value in variants(short) for position in range(len(value) + 1)
           for char in '0123456789!@#_-')
    yield (value[:position] + replacement + value[position + 1:]
           for value in variants(short) for position, char in enumerate(value)
           for replacement in {'a':'@4', 'e':'3', 'i':'1', 'l':'1', 'o':'0', 's':'$5', 't':'7'}.get(char.lower(), ''))
    yield (candidate for value in variants(words[:5000])
           for sequence in ('0123456789' * 7, '1234567890' * 7)
           for candidate in (''.join(a + b for a, b in zip(value, sequence)),
                             ''.join(b + a for a, b in zip(value, sequence))))


def context_candidates(ssid, words, word_limit=2000):
    seeds = tuple(dict.fromkeys(value for base in expanded_ssid.bases(ssid)
                               for value in forms(base)))[:48]
    for word in words[:word_limit]:
        for base, value, separator in itertools.product(seeds, forms(word), ('', '-', '_', ' ')):
            yield base + separator + value
            yield value + separator + base


def ordered_pairs(words, ordering):
    def score(left, right):
        return (left + 1) * (right + 1) if ordering == 'product' else left + right
    queue = [(score(index, 0), index, 0) for index in range(len(words))]
    heapq.heapify(queue)
    while queue:
        _, left, right = heapq.heappop(queue)
        yield words[left], words[right]
        if right + 1 < len(words):
            heapq.heappush(queue, (score(left, right + 1), left, right + 1))


def pair_candidates(words, ordering):
    for left, right in ordered_pairs(words, ordering):
        for base in (left + right, left.capitalize() + right.capitalize(), left + '-' + right, left + '_' + right):
            yield from audit.transforms(base)
        for digit in '0123456789':
            yield left + digit + right
            yield left.capitalize() + digit + right.capitalize()


def mix(generators, batch):
    active = deque(iter(generator) for generator in generators)
    while active:
        generator = active.popleft()
        count = 0
        for value in itertools.islice(generator, batch):
            count += 1
            yield value
        if count == batch:
            active.append(generator)


def filtered(source, window=200000, excluded=frozenset()):
    seen = set()
    for candidate in source:
        if not audit.valid(candidate) or candidate in excluded or candidate in seen:
            continue
        if len(seen) >= window:
            seen.clear()
        seen.add(candidate)
        yield candidate
