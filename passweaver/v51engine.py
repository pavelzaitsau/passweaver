"""Bridge to the V5.1 candidate generator.

The CLI only supports V5.1. Its engine lives in the sibling hybrid-v5.1
directory and yields password candidates for one network at a time, sized to
a cracker rate and a time checkpoint. We import it rather than shelling out so
candidates can be streamed straight into hashcat.
"""
import sys
from pathlib import Path

VERSION = 'v5.1'
_V51 = Path(__file__).resolve().parent.parent / 'hybrid-v5.1'

_v5 = None
_hybrid = None


def _load():
    """Import the V5.1 engine once, keeping its sibling import path intact."""
    global _v5, _hybrid
    if _v5 is not None:
        return
    if not _V51.is_dir():
        raise RuntimeError('hybrid-v5.1 not found next to the passweaver package')
    sys.path.insert(0, str(_V51))
    import v5          # noqa: E402  (adds hybrid-v4 to sys.path on import)
    _v5 = v5
    _hybrid = v5.hybrid


def checkpoints():
    _load()
    return tuple(_hybrid.CHECKPOINTS)


def languages():
    """Language codes V5.1 can load, each alongside the English base lists."""
    _load()
    return sorted(set(_hybrid.COUNTRIES.values()))


def country_for(language):
    """Map a language code to a country the engine accepts for that language.

    The engine selects wordlists by country; a country only carries its
    language here, so any country with the wanted language serves.
    """
    _load()
    for country in sorted(_hybrid.COUNTRIES):
        if _hybrid.COUNTRIES[country] == language:
            return country
    raise ValueError('unsupported_language')


def budget_for(rate, until):
    """Candidate count V5.1 will emit for this rate and checkpoint."""
    _load()
    plans = _hybrid.plan(rate)
    if until not in _hybrid.CHECKPOINTS:
        raise ValueError('invalid_checkpoint')
    return next(p['total_candidates'] for p in plans if p['seconds'] == until)


def candidate_stream(context, rate, until):
    """Yield candidate passwords (str) for one network.

    context must carry 'ssid' and may carry 'country', 'venue', 'address'.
    The returned generator must be closed by the caller (or fully consumed);
    use closing() around it.
    """
    _load()
    source = _v5.candidates(dict(context), rate, until)
    try:
        for _phase, _family, value in source:
            yield value
    finally:
        source.close()
