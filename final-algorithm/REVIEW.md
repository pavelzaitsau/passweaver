# V3 review

The reviewed release kept the V3 order. It fixed input handling, budget
accounting, portability, and report privacy.

| Finding | Fix |
| --- | --- |
| A short first stage could hide entries from later stages. | Exclude only entries the first stage used. |
| Per-record match positions exposed sensitive information. | Report aggregate results. |
| Text parsing changed significant spaces. | Use JSONL for exact field values. |
| Validation missed invalid configuration and control characters. | Validate settings and count input length in UTF-8 bytes. |
| Separate export and evaluation logic could change output order. | Use the same source and stage order. |

The two historical regression sets matched the accepted V3 record by record.
They had 20 matches out of 31 and 151 out of 424. The earlier V2 found 129
matches in the second set.

Separate capture checks validated the known-answer setup. The reference
configuration missed the control case within its budget. The source snapshot
excludes the private inputs and review logs.
