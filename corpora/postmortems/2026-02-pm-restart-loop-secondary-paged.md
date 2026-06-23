# Postmortem: restart_service Loop on payments-api, Secondary Paged Mid-Incident

**Date:** 2026-02-19
**Severity:** Sev-1
**Duration:** 1 hour 12 minutes

## Summary
`payments-api` entered a crash-restart loop after a dependency's TLS
certificate expired. The first two `restart_service` remediation attempts
were approved and executed but did not fix the underlying cause, since the
service kept failing its startup health check against the same expired
certificate. Secondary on-call was paged after the second failed restart per
the secondary-oncall-paging runbook's guidance on escalating mitigation that
isn't converging.

## Root Cause
An internal CA-issued certificate used by `payments-api` to call a downstream
fraud-scoring service expired. The service's startup health check called the
same downstream dependency, so every restart immediately failed the same way,
making the symptom look like a transient crash rather than a fixed,
deterministic dependency failure.

## Action Taken & Outcome
Secondary on-call recognized the deterministic failure pattern after the
second restart and checked the downstream TLS chain, finding the expired
cert. The cert was rotated via the standard CA renewal process, and a third
`restart_service` succeeded. Total of three restart attempts; two were
ultimately unnecessary remediation given the root cause.

## Notes
This is a case where `execute -> diagnose` re-entry behavior mattered: the
first failed restart should have been treated as new evidence that the
initial diagnosis (transient crash) was wrong, rather than simply retried.
Diagnosis confidence was not flagged as low going into the second restart
attempt, even though the same failure recurring identically is itself a
signal worth lowering confidence on.
