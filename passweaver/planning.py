"""Time modes, the pre-run plan, and the budget arithmetic behind it."""
import re

# Named time modes map to the fixed V5.1 checkpoints (seconds). Each sets the
# per-network candidate budget together with the measured cracker rate.
TIME_MODES = {
    'test': 120,
    'quick': 600,
    'short': 1800,
    'std': 3600,
    'deep': 7200,
}

_DURATION = re.compile(r'(\d+)\s*([smh])', re.IGNORECASE)


def parse_duration(text):
    """Parse '90s', '20m', '2h', '1h30m' into seconds. Raises ValueError."""
    matches = _DURATION.findall(text.strip())
    if not matches or _DURATION.sub('', text).strip():
        raise ValueError('invalid duration: {!r} (use forms like 90s, 20m, 2h)'.format(text))
    unit = {'s': 1, 'm': 60, 'h': 3600}
    total = sum(int(value) * unit[suffix.lower()] for value, suffix in matches)
    if total <= 0:
        raise ValueError('duration must be positive')
    return total


def human_duration(seconds):
    """Render seconds as a compact '2h', '30m', '1h30m' style string."""
    seconds = int(seconds)
    if seconds < 60:
        return '{}s'.format(seconds)
    hours, rest = divmod(seconds, 3600)
    minutes = rest // 60
    parts = []
    if hours:
        parts.append('{}h'.format(hours))
    if minutes:
        parts.append('{}m'.format(minutes))
    return ''.join(parts) or '{}s'.format(seconds)


def human_count(number):
    """Render a candidate count as 2.2G, 540M, 48k."""
    for scale, suffix in ((1_000_000_000, 'G'), (1_000_000, 'M'), (1_000, 'k')):
        if number >= scale:
            return '{:.1f}{}'.format(number / scale, suffix)
    return str(number)


class Plan:
    def __init__(self, network_count, mode, until, rate, budget, max_total):
        self.network_count = network_count
        self.mode = mode
        self.until = until
        self.rate = rate
        self.budget = budget
        self.max_total = max_total
        self.est_seconds = network_count * until
        if max_total is not None:
            self.est_seconds = min(self.est_seconds, max_total)

    def render(self):
        line = ('{n} network{s} · mode {mode} ({until}s) · rate {rate} H/s '
                '· budget {budget}/net').format(
            n=self.network_count, s='' if self.network_count == 1 else 's',
            mode=self.mode, until=self.until,
            rate=human_count(self.rate), budget=human_count(self.budget))
        est = 'estimate: up to ~{}'.format(human_duration(self.est_seconds))
        if self.max_total is not None:
            est += ' (capped)'
        est += ' (stops early on crack)'
        return line + '\n' + est
