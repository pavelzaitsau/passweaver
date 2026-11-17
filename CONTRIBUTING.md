# Contributing to Passweaver

Passweaver accepts a contribution only under the MIT No Attribution license
(MIT-0), and only with a Developer Certificate of Origin sign-off on every
commit. Read [acceptable use](docs/acceptable-use.md) first: a contribution that
adds a capture, transmission, or any capability to attack a network or a capture
the operator does not own is out of scope and is declined. A contribution does
not make you an intended operator of Passweaver; see
[acceptable use](docs/acceptable-use.md#intended-operator).

## License of a contribution

When you open a pull request, you license every change in it to the project
under MIT-0. The MIT-0 text is in [LICENSES/MIT-0.txt](LICENSES/MIT-0.txt), with
your name as the copyright holder.

MIT-0 lets the copyright holder ship your change under the project license, the
PolyForm Noncommercial License 1.0.0, and under any other license later. Without
that grant, one contribution under other terms blocks every later change of
license.

Some files are excluded, because their own licenses decide the terms of a
change:

| Files | Rule |
| --- | --- |
| `hybrid-v5/vendor/princeprocessor/` | PRINCE stays under its own MIT license. Change it upstream, not here. |
| `hybrid-v4/wordlists/frequencywords-*.txt` and their `.source.txt` originals | The FrequencyWords data stays under CC-BY-SA-4.0 with attribution. |
| `.agents/skills/` | The Copydesk skills stay under MIT-0, and the demo-video license texts stay under the voice model owners' terms. Do not edit them. |

To add third-party code, follow
[adding third-party code](docs/acceptable-use.md#adding-third-party-code). That
code keeps its upstream license, which [NOTICE](NOTICE) records.

## Sign-off

Sign off every commit:

```bash
git commit -s
```

The `-s` flag adds a `Signed-off-by:` line with the name and email from your Git
configuration. Use your real name. A pull request with an unsigned commit is not
merged until every commit carries a sign-off.

In this project, the sign-off states two things:

1. You certify the change under the
   [Developer Certificate of Origin 1.1](https://developercertificate.org/):
   you wrote it, or you otherwise have the right to submit it.
1. You license the change to the project under MIT-0, as
   [License of a contribution](#license-of-a-contribution) describes.

## Before you open a pull request

1. Run the tests and the documentation checks in [AGENTS.md](AGENTS.md#checks).
1. Name the branch and write the commit message as the Copydesk skills in
   [AGENTS.md](AGENTS.md#copydesk-skills) describe.
