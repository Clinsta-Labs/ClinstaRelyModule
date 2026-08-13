# FIFO Group semantics

Ordering is scoped by **`(organization_id, event_group)`**. `group_sequence` is the deterministic order key (not `created_at`).

## Allowed

- Org 1 Group A seq1 and Org 1 Group B seq1 processed concurrently
- Org 1 Group A seq1 and Org 2 Group A seq1 processed concurrently (same group name, different org)
- Within one org+group: seq1 → seq2 → seq3 only

## Blocking

If Org 1 / Group A seq2 fails, later sequences in that same org+group wait until seq2 is `SYNCED` (or manually unblocked from `RETRY_EXHAUSTED`).

Failure in one org+group never blocks another org or another group.
