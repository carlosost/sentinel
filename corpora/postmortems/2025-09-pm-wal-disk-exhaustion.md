# Postmortem: db-primary Disk Exhaustion from Stuck Replication Slot

**Date:** 2025-09-14
**Severity:** Sev-2
**Duration:** 47 minutes (alert fire to resolution)

## Summary
A logical replication slot consumer crashed silently three days before the
incident, leaving its slot active but unconsumed. WAL segments accumulated
until `db-primary`'s data volume hit 95% usage, triggering the disk-usage
alert and causing write latency to spike.

## Root Cause
The downstream consumer (an analytics ETL job) crashed on an unrelated schema
migration and was never restarted because its supervisor process didn't treat
the crash as actionable (logged at `WARN`, not `ERROR`). Postgres correctly
retained WAL for the inactive slot per its durability guarantees, but nothing
alerted on slot lag itself — only on the downstream symptom (disk usage).

## Action Taken & Outcome
On-call identified the stuck slot via `pg_replication_slots`, confirmed the
consumer was dead (not just lagging), and dropped the slot after confirming
no other consumer depended on it. Disk usage returned to normal within 4
minutes of the drop. The ETL job was restarted separately and backfilled from
a snapshot.

## Notes
This incident is a recurring failure mode: any logical replication slot can
silently accumulate WAL if its consumer dies. The fix was reactive
(drop-and-restart), not preventive. Follow-up: add a direct alert on
replication slot lag/age, not just the downstream disk-usage symptom — this
postmortem is referenced by that follow-up ticket.
