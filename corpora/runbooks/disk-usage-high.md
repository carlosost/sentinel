# Runbook: High Disk Usage on Database Hosts

**Symptom:** Disk usage alert fires at >=90% on a `db-*` host.

**Triage steps:**
1. Check `df -h` on the affected host to confirm the alert and identify which
   mount is filling up (usually `/var/lib/postgresql/data` or `/var/log`).
2. Check for unrotated WAL segments: `du -sh /var/lib/postgresql/data/pg_wal`.
   A stuck logical replication slot is the most common cause of WAL buildup.
3. Check for runaway application logs under `/var/log/` that missed log
   rotation.

**Remediation:**
- If a replication slot is stuck: drop the inactive slot after confirming no
  consumer needs it, or restart the consuming service to let it catch up.
- If logs are the cause: rotate/compress immediately, then fix the logrotate
  cron entry so this doesn't recur.
- If genuinely out of headroom: provision additional disk via the standard
  volume-resize procedure, then page the platform team to review retention
  policy.

**Escalation:** If usage is climbing faster than triage can keep up (doubling
in under 15 minutes), page the secondary on-call immediately rather than
completing triage solo.
