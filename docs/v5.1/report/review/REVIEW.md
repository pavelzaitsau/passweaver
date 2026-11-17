# V5.1 fixes and checks

The V5 review found three issues. V5.1 fixed all three before the
comparison.

| Finding | Fix |
| --- | --- |
| The command line did not pass country to the hybrid. | Pass country, venue, and address. |
| The hybrid ignored venue and address. | Use the extra fields in later output. |
| A review link pointed outside the archive. | Include the log and check the link. |

The historical suite passed 26 tests. Independent reviewers also
checked 12,000 scheduling and indexing cases and 40 samples of the
early V3 sequence. They checked empty budgets, language selection,
output without extra context, and archive privacy.

The [final review](../FINAL-REVIEW.md) records the checks after the
comparison.
