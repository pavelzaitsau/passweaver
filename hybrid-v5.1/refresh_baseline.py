import hashlib
import hmac
import json
import os
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent / 'hybrid-v4'))
import hybrid
import batch

SOURCE = ROOT.parent / 'hybrid-v4/results/comparison-20261116-full'
DESTINATION = ROOT / 'results/verified-baseline'


def check_files(protocol, producer):
    for name, checksum in protocol['method']['files_sha256'].items():
        path = ROOT.parent / name
        if hashlib.sha256(path.read_bytes()).hexdigest() != checksum:
            raise ValueError('reference_method_changed')
    if hashlib.sha256(Path(__file__).read_bytes()).hexdigest() != producer:
        raise ValueError('reference_producer_changed')
    manifest = json.loads((hybrid.v3.ROOT / 'release-manifest.json').read_text())
    if any(hashlib.sha256((hybrid.v3.ROOT / name).read_bytes()).hexdigest() != checksum
           for name, checksum in manifest['files_sha256'].items()):
        raise ValueError('reference_release_changed')


def run():
    os.umask(0o077)
    protocol = json.loads((SOURCE / 'protocol.json').read_text())
    producer = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    check_files(protocol, producer)
    if protocol['rate'] != '235000' or [d['dataset'] for d in protocol['datasets']] != ['p01','p02','p03','p04','p05','p06','p07']:
        raise ValueError('reference_protocol_invalid')
    rows, inputs = [], {}
    for dataset in protocol['datasets']:
        filename = 'wifox_ssid_password-' + dataset['dataset'] + '.txt'
        data = (SOURCE / 'private-inputs' / filename).read_bytes()
        parsed = hybrid.v3.parse_input(data, 'legacy-text')
        if len(parsed) != dataset['records']:
            raise ValueError('reference_count_changed')
        rows.extend({'ssid': r['ssid'], 'password': r['password']} for r in parsed)
        inputs[filename] = data
    canonical = json.dumps(rows, ensure_ascii=False, separators=(',', ':')).encode()
    old_key = (SOURCE / 'private-inputs/attestation.key').read_bytes()
    if not hmac.compare_digest(hmac.new(old_key, canonical, hashlib.sha256).hexdigest(),
                               protocol['snapshot_attestation_hmac_sha256']):
        raise ValueError('reference_inputs_changed')
    DESTINATION.mkdir(mode=0o700, exist_ok=False)
    private = DESTINATION / 'private-inputs'
    private.mkdir(mode=0o700)
    for filename, data in inputs.items():
        with (private / filename).open('xb') as stream:
            os.fchmod(stream.fileno(), 0o400)
            stream.write(data)
    print(json.dumps({'status': 'reference_started', 'records': len(rows)}), flush=True)
    started = time.monotonic()
    with (DESTINATION / 'progress.jsonl').open('x') as log:
        def progress(value):
            log.write(json.dumps(dict(value, wall_seconds=time.monotonic() - started)) + '\n')
            log.flush()
        report, outcomes = batch.evaluate_version(rows, 'v3', 235000, 7200, workers=6, progress=progress)
    check_files(protocol, producer)
    outcome_bytes = json.dumps(outcomes, separators=(',', ':')).encode()
    key = os.urandom(32)
    binding = dict(records=len(rows), rate=235000, checkpoints=protocol['checkpoints'],
                   datasets=protocol['datasets'], input_attestation=protocol['snapshot_attestation_hmac_sha256'],
                   source_files_sha256=protocol['method']['files_sha256'], producer_sha256=producer,
                   config=report['v3_effective_config'], creation='fresh exact reference evaluation, not adopted old outcomes')
    signature_bytes = json.dumps(binding, sort_keys=True, separators=(',', ':')).encode()
    certificate = dict(binding=binding, hmac_sha256=hmac.new(key, signature_bytes + b'\0' + outcome_bytes + b'\0' + canonical, hashlib.sha256).hexdigest())
    for filename, data in [('cache.key', key), ('v3-outcomes.json', outcome_bytes)]:
        with (private / filename).open('xb') as stream:
            os.fchmod(stream.fileno(), 0o400)
            stream.write(data)
    hybrid.write_json_exclusive(DESTINATION / 'v3-report.json', report)
    hybrid.write_json_exclusive(DESTINATION / 'certificate.json', certificate)
    print(json.dumps({'status': 'reference_completed_and_attested', 'curve': report['curve'],
                      'wall_seconds': time.monotonic() - started}), flush=True)


if __name__ == '__main__':
    try:
        run()
    except KeyboardInterrupt:
        raise SystemExit(130)
    except Exception:
        print(json.dumps({'status': 'failed', 'code': 'reference_refresh_failed'}))
        raise SystemExit(1)
