# Runbook: CPU Spike on Application or Database Hosts

**Symptom:** CPU usage alert (>=90% sustained for >5 minutes) on an app or
database host, or p99 latency alert correlating with high CPU saturation.

**Triage steps:**
1. Identify the hot process: `top -bn1 | head -20` or `kubectl top pods`.
   For Postgres, check `pg_stat_activity` for long-running or blocking queries.
2. Determine if the spike correlates with a deploy, a cron job, or external
   traffic patterns. Check the dashboard for a request-rate spike at the same
   timestamp.
3. For Postgres CPU spikes: look for missing indexes (`pg_stat_user_tables`,
   `seq_scan` counter jump), lock contention (`pg_locks` joined to
   `pg_stat_activity`), or a newly introduced expensive query.
4. For app-service CPU spikes: check for tight retry loops, hot code paths
   reintroduced by a recent change (profile if possible), or a dependency that
   started returning errors at high rate (retry storm).

**Remediation:**
- External traffic spike: scale the service horizontally via `scale_service`
  if headroom allows, or enable rate limiting at the gateway layer.
- Runaway query (Postgres): terminate the offending backend via
  `pg_terminate_backend(pid)` to unblock the system, then add an index or
  fix the query offline. This is a side-effecting action requiring human approval.
- Retry storm: identify the failing downstream dependency and circuit-break or
  disable the retry loop. Restart the affected service once the downstream is
  healthy.
- Cron / batch job: kill the job and reschedule for off-peak hours.

**Escalation:** If CPU is saturated database-wide and queries are queuing, the
incident is Sev-1 — page secondary on-call immediately and open a bridge.
