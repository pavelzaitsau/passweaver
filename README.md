# Passweaver

Passweaver archives offline Wi-Fi password research and synthetic tests.

## Revisions

| Revision | Role |
| --- | --- |
| [V3](final-algorithm/README.md) | Reference version with a V2 rollback profile. |

## Tests

Run the portable suite from the repository root with Python 3.9 or later.

```bash
python3 run_tests.py
```

## Disclaimer

To the maximum extent permitted by law, the author provides Passweaver "as is",
without any warranty or condition of any kind. The author and the contributors
accept no liability under any legal theory, including contract, tort, and
negligence. The exclusion covers any damage, loss, legal consequence, or other
harm from the software, its documentation, or any use of them.

Anyone who runs, modifies, or distributes Passweaver does so at their own risk
and is responsible for every run: the captures and records they test candidates
against, the legal basis for that test, the handling of any captured data, and
compliance with the law. Nothing in this repository authorizes testing any
network or any capture you do not own or have written permission to test, and
nothing in it is legal advice. Many jurisdictions restrict intercepting wireless
traffic and recovering passwords, and doing so without authorization can be a
crime.

## License

Passweaver is licensed under the [PolyForm Noncommercial License
1.0.0](LICENSE). Commercial use is not permitted. The license permits more than
the intended use; [acceptable use](docs/acceptable-use.md) states the intended
use and its limits. The components that [NOTICE](NOTICE) lists keep their own
licenses: the public password and frequency wordlists (MIT). One English
frequency wordlist has unconfirmed provenance, which [NOTICE](NOTICE) tracks. A
contribution is accepted only under the terms in
[CONTRIBUTING](CONTRIBUTING.md).
