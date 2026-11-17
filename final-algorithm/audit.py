import re
import unicodedata


WORDLISTS = (
    ('seclists-10k.txt', '68782d6a4a19a4768d5f15dd66bd534e7a33055cc755411e33f16d18c50fdcce'),
    ('english-frequency-10k.txt', 'd6b3e04f1ac30be6525d41474166c0bff28486ecd8c48dcb0ab9c7c9cc05ed86'),
)


SUFFIXES = ('', '123', '1234', '1', '!', '2024', '2025', '2026', '0', '12', '01',
            '2023', '2022', '2021', '2020', '12345', '123456', '007', '777', '@', '#')


def variants(word):
    folded = ''.join(char for char in unicodedata.normalize('NFKD', word) if not unicodedata.combining(char))
    return dict.fromkeys((word, word.lower(), word.capitalize(), word.upper(), folded.lower(),
                          word.lower().translate(str.maketrans('aeios', '@310$'))))


def transforms(word):
    for value in variants(word):
        for suffix in SUFFIXES:
            yield value + suffix
        for prefix in ('0', '1', '123'):
            yield prefix + value


def valid(candidate):
    if not isinstance(candidate, str):
        return False
    try:
        length = len(candidate.encode('utf-8'))
    except UnicodeEncodeError:
        return False
    return (8 <= length <= 63 and '\0' not in candidate
            and '\r' not in candidate and '\n' not in candidate)


def ssid_candidates(ssid):
    tokens = re.findall(r'[^\W_]+', ssid, flags=re.UNICODE)
    names = [word for word in tokens if word.casefold() not in ('wifi', 'guest', '2g', '5g', '2ghz', '5ghz')]
    bases = (ssid, ''.join(tokens), ''.join(names), *[word for word in tokens if len(word) >= 3])
    for base in dict.fromkeys(bases):
        if base:
            yield from (candidate for candidate in transforms(base) if valid(candidate))
