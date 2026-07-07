# Runbook: High Memory / OOM Kill on Application Hosts

**Symptom:** Memory usage alert (>=85%) on an app host, or `OOMKilled` event
in container logs/pod events.

**Triage steps:**
1. Identify the offending process: `ps aux --sort=-%mem | head -20`. For
   Kubernetes, `kubectl top pods -n <namespace>` gives real-time memory by pod.
2. Check for a memory leak signature: is the process's RSS growing monotonically
   since the last deploy or restart? Compare with yesterday's same-hour metric.
3. Check heap dumps or profiler output if the service publishes them (check
   `/<service>/debug/pprof/heap` for Go services, JVM heap dump path for JVM
   services).
4. Determine if the spike is sudden (possible memory bomb: large payload, bad
   query, cache stampede) or gradual (classic leak).

**Remediation:**
- Sudden spike: identify the triggering request/job and rate-limit or block it.
  Restart the affected instance to restore service while investigating offline.
- Gradual leak: restart the affected pod/container now to buy time, then open a
  P1 bug for root-cause analysis. Do not leave a leaking service restarting
  in a loop without a fix timeline — escalate.
- If multiple pods are OOMKilled simultaneously, check for a shared upstream
  trigger (e.g., a large batch job, runaway queue consumer, or cache invalidation
  flood) before restarting everything at once.

**Remediation tools:** `restart_service` (read-only diagnosis first, then
restart), `scale_service` (if adding replicas can absorb load while the leak
is fixed upstream).

**Escalation:** OOM on the database host (not app hosts) is a different
incident — page the database team directly. OOM that causes data loss or
transaction rollbacks is automatically Sev-1.
