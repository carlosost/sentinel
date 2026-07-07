# Runbook: Service Restart Loop (CrashLoopBackOff / Repeated OOM)

**Symptom:** A service is restarting repeatedly (Kubernetes `CrashLoopBackOff`,
or systemd restart counter climbing). The restart interval may back off
exponentially, masking the underlying cause.

**Triage steps:**
1. Fetch the logs from the *previous* (crashed) container, not the current one:
   `kubectl logs <pod> --previous`. The exit reason is usually in the final
   10-20 lines.
2. Check the exit code: 137 = OOM kill (memory), 1 = application panic/exception,
   139 = segfault. Each has a distinct triage path.
3. Confirm whether the restart loop started with a recent deploy or
   configuration change — check the deploy log and `git log` on the config repo.
4. Look for unhealthy dependency signals: if the service is restarting because
   a required upstream (database, secrets store, message broker) is unreachable,
   fix the upstream first; restarting the service repeatedly won't help.

**Remediation:**
- OOM loop (exit 137): see the High Memory / OOM runbook. Increase memory limit
  as a temporary measure if you need to stabilize, but treat it as technical
  debt — a service that requires more memory than its limit is budgeted for
  needs root-cause analysis.
- Application panic (exit 1): roll back the last deploy if the panic correlates
  with it. Use `rollback_deploy` with human approval for customer-facing services.
- Config error: fix the bad config value in the config store and trigger a
  rolling restart. A restart loop from a bad env var or secrets reference is
  usually faster to fix than a code rollback.
- Dependency unreachable: fix the downstream first. Temporarily scale down the
  crashing service to 0 replicas via `scale_service` to stop the noise while
  the dependency recovers.

**Escalation:** If the restart loop affects a payment, authentication, or
data-write service, treat as Sev-1 regardless of the current traffic impact.
