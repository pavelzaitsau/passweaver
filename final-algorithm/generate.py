from collections import Counter
import hashlib
import itertools
import json
import os
from pathlib import Path
import sys
import time

import engine


def export_candidates(path, ssid, config, raw, words, limit):
    if type(limit) is not int or limit <= 0:
        raise ValueError('Invalid candidate limit')
    engine.validate_config(config)
    path = Path(path)
    output = path.open('xb')
    digest, stages, count = hashlib.sha256(), Counter(), 0
    started = time.monotonic()
    try:
        with output:
            os.fchmod(output.fileno(), 0o600)
            source = engine.candidates_for_ssid(ssid, config, raw, words)
            for stage, value in itertools.islice(source, min(limit, config['budget_per_pair'])):
                data = value.encode('utf-8') + b'\n'
                output.write(data)
                digest.update(data)
                count += 1
                stages[stage] += 1
    except BaseException:
        path.unlink(missing_ok=True)
        raise
    return {'status': 'completed', 'candidates': count, 'by_stage': dict(stages),
            'sha256': digest.hexdigest(), 'output': str(path.resolve()),
            'generation_wall_seconds': time.monotonic() - started,
            'modeled_attack_seconds': count / config['assumed_checks_per_second'],
            'hashcat_wordlist_autohex_disable_required': True}


def main(argv=None):
    os.umask(0o077)
    try:
        parser = engine.SafeParser(description='Export one deterministic candidate file; no password or capture is read.')
        parser.add_argument('--ssid', required=True)
        parser.add_argument('--output', type=Path, required=True)
        parser.add_argument('--config', type=Path, default=engine.ROOT / 'config.json')
        parser.add_argument('--max-candidates', type=int)
        args = parser.parse_args(argv)
        config = json.loads(args.config.read_bytes())
        engine.validate_config(config)
        raw, words, _ = engine.load_words()
        limit = config['budget_per_pair'] if args.max_candidates is None else args.max_candidates
        result = export_candidates(args.output, args.ssid, config, raw, words, limit)
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except KeyboardInterrupt:
        print(json.dumps({'status': 'cancelled'}))
        return 130
    except Exception:
        print(json.dumps({'status': 'failed', 'code': 'candidate_export_failed'}))
        return 1


if __name__ == '__main__':
    sys.exit(main())
