# passweaver

`passweaver` cracks a folder of Wi-Fi captures in one command. It extracts
handshakes with `hcxpcapngtool`, generates V5.1 password candidates for each
network, and streams them into `hashcat`. Only the V5.1 engine is supported.

```bash
bin/passweaver -f '/Volumes/MARAUDER/*.pcap' -t std
```

That reads every capture under the path, finds each distinct network, and
spends up to one hour of candidates on each until `hashcat` recovers the key.

## Requirements

- Python 3.9 or later.
- [`hcxtools`](https://github.com/ZerBea/hcxtools) for `hcxpcapngtool`.
- [`hashcat`](https://hashcat.net/hashcat/) with a working backend.

Install the two tools on macOS with one command. `passweaver` checks for both
at start and names the missing one.

```bash
brew install hcxtools hashcat
```

## Usage

Point `-f` at files, a directory, or a quoted glob. A directory is walked
recursively for `.pcap`, `.pcapng` and `.cap` files.

```bash
bin/passweaver -f /Volumes/MARAUDER -t short --lang pl
```

Preview the networks in a capture set without cracking:

```bash
bin/passweaver -f /Volumes/MARAUDER --list
```

Run unattended, with a hard time limit and no prompt:

```bash
bin/passweaver -f caps/ -t deep --max-total 4h --yes
```

## Options

| Flag | Meaning | Default |
| --- | --- | --- |
| `-f`, `--files` | Capture files, directories, or quoted globs | required |
| `-t`, `--time` | Time mode per network | `std` |
| `--rate` | Cracker rate in H/s; skips the benchmark | auto |
| `--lang` | Load English plus this language's wordlists | English only |
| `--venue`, `--address` | Extra candidate context | none |
| `-j`, `--jobs` | Parallel extraction workers | 1 |
| `-o`, `--outdir` | Output directory | `./passweaver-run-<timestamp>` |
| `--max-total` | Global wall-clock cap, such as `30m` or `2h` | none |
| `-w`, `--workload` | `hashcat` workload profile, 1 to 4 | 3 |
| `--keep` | Write each network's candidate list to disk | off |
| `--fresh` | Ignore an earlier run's `cracked.txt` | off |
| `--list` | List networks and exit | off |
| `--dry-run` | Show the plan without cracking | off |
| `--yes` | Skip the confirmation prompt | off |

## Time modes

A mode sets the per-network candidate budget: `budget = rate x until`. The
rate is the measured `hashcat` speed, so a mode spends about its own duration
on each network before moving on.

| Mode | Checkpoint | Time per network |
| --- | --- | --- |
| `test` | 120 s | 2 min |
| `quick` | 600 s | 10 min |
| `short` | 1800 s | 30 min |
| `std` | 3600 s | 1 h |
| `deep` | 7200 s | 2 h |

The budget applies to each network. A run over 40 networks in `std` mode can
last up to 40 hours. The pre-run plan prints the network count and the
estimate, and asks for confirmation. Use `--max-total` to cap the whole run.

## How it works

1. Resolve `-f` into a list of capture files.
2. Run `hcxpcapngtool` on each capture and read its 22000 hash lines.
3. Group handshakes by ESSID across all captures, so each network is cracked
   once even when it appears in several files.
4. Benchmark `hashcat` once and cache the rate in `~/.passweaver/rate.json`.
5. For each network, generate V5.1 candidates and pipe them into `hashcat`.

Candidates stream through a pipe and are never written to disk unless `--keep`
is set. This keeps a multi-billion candidate budget off the filesystem.

## Output

The output directory holds three things.

- `cracked.txt`: one `ESSID<tab>passphrase` line per recovered key.
- `report.json`: every network's status, the skipped captures, and the run
  metadata.
- `passweaver.potfile`: the `hashcat` pot for this run.

A capture that yields no usable handshake is skipped with a reason, such as
`no handshake found` or `no ESSID (hidden)`. The reasons appear in the summary
and in `report.json`.

The exit code is `0` on a clean run, `1` when `hashcat` failed on a network,
and `2` on a usage or setup error. A network left unprocessed by `--max-total`
or an interrupt is written to `report.json` with status `skipped` or
`interrupted`, so a capped run never hides what it did not reach.

## Resume

A run writes `cracked.txt` and `report.json` after every network. Re-running
with the same `-o` directory skips networks already in `cracked.txt`. Pass
`--fresh` to crack them again.

## Limitations

- The engine supports V5.1 only. `-v` accepts no other value.
- A hidden network has no ESSID, so V5.1 cannot build its candidates. These
  networks are skipped.
- Networks are keyed by ESSID, so distinct access points that share a name are
  cracked as one. When they resolve to different keys, `report.json` lists all
  of them and the summary marks the network with more than one key.
- Candidate generation in Python can be slower than `hashcat` consumes. For a
  large budget the run time is bound by generation, not by the cracker.
- `--lang`, `--venue` and `--address` apply to the whole run. Set them only
  when every capture comes from one place.
- `--lang` always keeps the English base lists and adds the chosen language.
  The codes are `cs`, `de`, `en`, `es`, `fr`, `it`, `nl`, `pl`, `pt`, `ru`,
  `tr` and `uk`. Without it, the run uses English only.
