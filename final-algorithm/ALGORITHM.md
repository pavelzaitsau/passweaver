# V3 algorithm notes

V3 uses the network name (SSID) and independent wordlists. The evaluator
compares the output with known answers. The source and checksums for the
wordlists are in the [wordlist manifest](wordlists/general-v2-manifest.json).

## Input and output

The evaluator accepts JSON Lines (JSONL). This format preserves spaces and
slashes in fields. Input limits count UTF-8 bytes. The evaluator rejects
unknown fields and keeps duplicate records in the totals.

The report contains aggregate results, settings, and checksums. It omits
network names, passwords, and per-record match positions. Each run gets a
random input ID.

Modeled time comes from the number of attempts and an assumed rate. The
report records evaluator runtime separately.
