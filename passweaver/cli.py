"""passweaver: offline WPA candidate generation (V5.1) piped into hashcat.

Discover captures, extract handshakes, generate V5.1 candidates per network
and stream them into hashcat. Only the V5.1 engine is supported.
"""
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import deps          # noqa: E402
import hashcat       # noqa: E402
import planning      # noqa: E402
import runner        # noqa: E402

SUPPORTED_ENGINE = 'v5.1'


def build_parser():
    parser = argparse.ArgumentParser(
        prog='passweaver',
        description='Generate V5.1 password candidates from *.pcap captures and crack them with hashcat.')
    parser.add_argument('-f', '--files', nargs='+', required=True, metavar='PATH',
                        help='capture files, directories (walked), or quoted globs')
    parser.add_argument('-t', '--time', choices=sorted(planning.TIME_MODES), default='std',
                        help='time mode per network (default: std = 3600s)')
    parser.add_argument('-v', '--engine', dest='version', default=SUPPORTED_ENGINE,
                        help='engine version (only v5.1 is supported)')
    parser.add_argument('--rate', type=int, metavar='HPS',
                        help='cracker rate in H/s; skips the hashcat benchmark')
    parser.add_argument('--lang', type=str.lower,
                        help='language code; loads English plus this language (e.g. pl, de, ru)')
    parser.add_argument('--venue', help='venue name for candidate context')
    parser.add_argument('--address', help='address for candidate context')
    parser.add_argument('-j', '--jobs', type=int, default=1, metavar='N',
                        help='parallel capture extraction workers (cracking stays serial)')
    parser.add_argument('-o', '--outdir', metavar='DIR',
                        help='output directory (default: ./passweaver-run-<timestamp>)')
    parser.add_argument('--max-total', metavar='DUR',
                        help='global wall-clock cap, e.g. 30m, 2h, 1h30m')
    parser.add_argument('-w', '--workload', type=int, choices=(1, 2, 3, 4), default=3,
                        help='hashcat workload profile (default: 3)')
    parser.add_argument('--keep', action='store_true',
                        help='write per-network candidate lists to the output directory')
    parser.add_argument('--fresh', action='store_true',
                        help='ignore any cracked.txt from an earlier run (no resume)')
    parser.add_argument('--list', action='store_true',
                        help='list the networks found in the captures and exit')
    parser.add_argument('--dry-run', action='store_true',
                        help='show the plan without cracking')
    parser.add_argument('--yes', action='store_true',
                        help='skip the confirmation prompt')
    return parser


def _validate(args):
    if args.version != SUPPORTED_ENGINE:
        raise runner.RunError('only engine {} is supported (got {!r})'.format(
            SUPPORTED_ENGINE, args.version))
    if args.jobs < 1:
        raise runner.RunError('--jobs must be >= 1')
    if args.rate is not None and args.rate <= 0:
        raise runner.RunError('--rate must be positive')
    if args.max_total:
        planning.parse_duration(args.max_total)      # raises ValueError on bad input
    if args.lang:
        import v51engine as engine
        if args.lang not in engine.languages():
            raise runner.RunError('unknown --lang {!r}; choices: {}'.format(
                args.lang, ', '.join(engine.languages())))


def main(argv=None):
    args = build_parser().parse_args(argv)
    args.interactive = sys.stdin.isatty() and sys.stdout.isatty()
    try:
        _validate(args)
        return runner.run(args)
    except (runner.RunError, deps.MissingDependency, hashcat.HashcatError,
            RuntimeError, ValueError) as exc:
        print('passweaver: {}'.format(exc), file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print('passweaver: interrupted', file=sys.stderr)
        return 130


if __name__ == '__main__':
    sys.exit(main())
