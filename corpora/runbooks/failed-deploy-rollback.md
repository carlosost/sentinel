# Runbook: Failed Deploy Rollback

**Symptom:** Deploy pipeline reports a failed health check post-deploy, or
error-rate alert fires within 5 minutes of a deploy completing.

**Triage steps:**
1. Confirm the deploy timestamp correlates with the error-rate spike in the
   dashboard — don't assume causation without checking the timeline.
2. Pull the diff for the deploy; look for config changes (env vars, feature
   flags) in addition to code changes — config-only regressions are common
   and easy to miss.
3. Check whether the failure is isolated to one instance/AZ (infra issue) or
   uniform across the fleet (code/config issue).

**Remediation:**
- Uniform failure across the fleet: roll back to the previous known-good
  release immediately via the standard `rollback_deploy` tool, then
  investigate offline.
- Isolated to one instance: cordon/drain that instance and let autoscaling
  replace it; do not roll back the whole fleet for a single bad host.
- If rollback itself fails (e.g., previous artifact was already garbage
  collected), escalate to the platform team — do not attempt a manual
  artifact rebuild under incident pressure.

**Escalation:** Any rollback affecting a customer-facing service requires a
human approval step before execution, regardless of confidence level.
