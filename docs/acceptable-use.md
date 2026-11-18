# Passweaver acceptable use and licensing

This document states what Passweaver is for, who may run it, and the limits on
that use. It sits alongside the [LICENSE](../LICENSE) and the
[NOTICE](../NOTICE). When the law and this policy disagree, the stricter rule
wins.

The **author** is Pavel Zaitsau, the copyright holder. The **operator** is any
person who runs, modifies, or distributes Passweaver.

## Purpose

Passweaver is an archive of offline Wi-Fi password research. It generates
password candidates and matches them against handshake records that were
captured earlier. It performs no capture and no transmission. The author uses it
only for noncommercial research, and only against captures the author owns or has
written permission to test. It is not a product, a service, or a tool for use
against captures or networks the operator does not own or control.

## Intended operator

The author is the intended operator, for the author's own noncommercial research
only. A paid assessment, a client engagement, or any other commercial use is
prohibited by this policy. For an operator who is an individual, commercial use
is also outside the license.

## Authorized perimeter

Run Passweaver only against a handshake record that the operator captured from a
network the operator owns, or captured under written, time-bounded permission
from the network's owner. Running it against any other capture or record is
prohibited. Possession of a capture file is not authorization.

## Prohibited use

- Testing candidates against a third-party or otherwise unauthorized capture or
  network.
- Any commercial use, including a paid security assessment.
- Redistributing private inputs, individual outcomes, captures, or keys.
- Using any result to target, track, or profile a person or a device.

## Data handling

The published archive excludes private inputs, individual outcomes, captures, and
keys. Keep working captures only on devices the operator controls, delete them
when the assessment ends, and never commit a capture, an outcome, or a key to
this repository. Treat a handshake record as being as sensitive as the
passphrase itself.

## Operator responsibility

The operator carries full responsibility for every run, as the README
[disclaimer](../README.md#disclaimer) states. Nothing in this repository
authorizes testing any network or capture the operator does not own or have
written permission to test, and nothing in it is legal advice.

## Licensing

The author's original code and documentation are under the
[PolyForm Noncommercial License 1.0.0](../LICENSE). That license permits any
noncommercial purpose, including use by a noncommercial organization. This policy
is narrower: the intended use is the author's own research, as stated above.

| File | Role |
| --- | --- |
| `LICENSE` | The PolyForm Noncommercial License 1.0.0 for the original work. |
| `NOTICE` | The third-party components and the license each one keeps. |
| `CONTRIBUTING.md` | The inbound license (MIT-0) and sign-off for a contribution. |
| `docs/acceptable-use.md` | This policy: the intended use and its limits. |

Keep the required notice with any copy of the software:

```text
Required Notice: Copyright 2026 Pavel Zaitsau
```

### What the noncommercial restriction covers

The noncommercial restriction covers the author's original code and
documentation. It does not override the license of any component that the
[NOTICE](../NOTICE) lists. Each listed component keeps its own terms, and some of
those terms permit commercial use of that component.

### Adding third-party code

Add a third-party component only under a permissive license, such as MIT,
MIT-0, BSD, or Apache 2.0, or under a Creative Commons license for data. Do not
add code under the GNU GPL or another strong copyleft license. Keep the upstream
copyright and license text with the component, and record the component, its
source, and its license in the [NOTICE](../NOTICE).

The PolyForm Noncommercial License is not approved by the Open Source Initiative,
so Passweaver as a whole is not open source. Individual components keep whatever
status their own licenses give them.
