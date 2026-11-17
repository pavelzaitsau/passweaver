# V4.1 spec

V4.1 tests staged scheduling with the same checkpoint budgets as V3.
The checkpoints range from 10 seconds to two hours of modeled checking.
Preparation and generation time are separate.

The scheduler carries unfinished sources between stages. The language
profile uses English and can add a language based on the country. Duplicate
filtering applies within each source. The same ordered stream feeds
evaluation and export.

The comparison fixes the source, settings, and data before scoring. It
reports match counts, gains, and losses at each checkpoint. New data is
needed to check whether a result generalizes.
