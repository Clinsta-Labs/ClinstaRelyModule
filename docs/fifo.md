# FIFO Group semantics

`event_group` is the ordering boundary. `group_sequence` is the deterministic order key (not `created_at`).

## Allowed

- Group A seq1 and Group B seq1 processed concurrently
- Within Group A: seq1 → seq2 → seq3 only

## Blocking

If Group A seq2 fails, seq3/seq4 wait until seq2 is `SYNCED` (or manually unblocked from `RETRY_EXHAUSTED`).

Failure in Group A never blocks Group B.
