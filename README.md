# Passweaver

Passweaver archives offline Wi-Fi password research and synthetic tests.

## Revisions

| Revision | Role |
| --- | --- |
| [V3](final-algorithm/README.md) | Reference version with a V2 rollback profile. |
| [V4.1](hybrid-v4/README.md) | Experiment with staged scheduling and language profiles. |

Keep the version directories next to each other for their imports.

## Tests

From the repository root, run the portable suite with Python 3.9 or later.

```bash
python3 run_tests.py
```

See the [agent guide](AGENTS.md#checks) for documentation checks.

## Signed commits

Set up Git commit signing for your clone and check that Git trusts your
signing key. For SSH signing, put the trusted public signing keys in the
file set by `gpg.ssh.allowedSignersFile`.
See [GitHub's commit signing guide](https://docs.github.com/en/authentication/managing-commit-signature-verification/signing-commits).

```sh
git config --local commit.gpgsign true
git verify-commit HEAD
hook=$(git rev-parse --git-path hooks/pre-push)
test ! -e "$hook" && install -m 755 .githooks/pre-push "$hook"
```

If the clone already has a different pre-push hook, add this check to it.
The hook verifies each commit a push introduces to the remote `main` branch.

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
licenses: the Copydesk skills (MIT-0), the FrequencyWords wordlists (CC BY-SA
4.0), and the public password and frequency wordlists (MIT). One English
frequency wordlist has unconfirmed provenance, which [NOTICE](NOTICE) tracks. A
contribution is accepted only under the terms in
[CONTRIBUTING](CONTRIBUTING.md).
