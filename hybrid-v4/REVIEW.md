# V4.1 review

The first V4 review found five defects. Regression tests reproduced each
defect before the fixes. The final V4.1 suite passed 48 tests.

| Finding | Fix |
| --- | --- |
| Normalization changed the original case. | Preserve the original form. |
| Unfinished sources vanished at stage boundaries. | Carry unfinished sources forward. |
| Early fields crowded out other fields. | Share space across fields before filtering. |
| Small budgets favored one source. | Split work in proportion to the stage weights. |
| Reports could not identify the exact inputs. | Record checksums and reject mid-run changes. |

The early comparison stopped before both versions finished. The later
comparison used the reviewed V4.1 code. See the [V4.1 summary](README.md)
for the outcome.
