# V5 spec

V5 preserves the V3 sequence through the ten-minute modeled checkpoint.
After that checkpoint, the hybrid shares its budget among V3, V4.1, and
PRINCE. Shared entries across sources can consume part of the budget.

The comparison uses the same input and budget at each of eight checkpoints.
A separate control assigns the PRINCE share back to V3. Both policies are
fixed before scoring. The result measures the effect of the policy on the
sample.

The evaluator checks attestations before it reuses a baseline. Public
reports contain totals and keep individual inputs and outcomes private.
