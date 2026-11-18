# Agent guide

Write project docs and commit messages in plain English. Keep the version
directories next to each other because their imports use sibling paths.

## Copydesk skills

The seven skills come from [Copydesk](https://github.com/pavelzaitsau/copydesk/tree/f2b8f18417da0e586a26556ae10227a681813761).
Codex can find them in `.agents/skills/`.

| Skill | When to read it |
| --- | --- |
| [Technical writing](.agents/skills/technical-writing/SKILL.md) | Write or edit prose in a file. |
| [Markdown formatting](.agents/skills/markdown-formatting/SKILL.md) | Write or review Markdown. |
| [Docs linter](.agents/skills/docs-linter/SKILL.md) | Run Vale or change a prose rule. |
| [Commit messages](.agents/skills/commit-messages/SKILL.md) | Write or revise a commit message. |
| [Branch names](.agents/skills/branch-names/SKILL.md) | Name or rename a branch. |
| [Demo video](.agents/skills/demo-video/SKILL.md) | Record an app or a finished slide deck. |
| [Explainer](.agents/skills/explainer/SKILL.md) | Invoke explicitly to research and make a narrated explainer. |

## Checks

Run these from the repository root. The docs checks need
`markdownlint-cli2` and `vale` on your path. V5 and V5.1 include PRINCE
source and a macOS ARM64 binary.

```bash
python3 run_tests.py
.agents/skills/markdown-formatting/scripts/lint-markdown.sh '*.md' 'final-algorithm/*.md' 'hybrid-v*/*.md' 'docs/**/*.md'
.agents/skills/docs-linter/scripts/lint-docs.sh .
```

See the README for [archive provenance](README.md#provenance).

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
