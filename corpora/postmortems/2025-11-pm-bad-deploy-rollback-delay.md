# Postmortem: Delayed Rollback After Bad Config Deploy

**Date:** 2025-11-02
**Severity:** Sev-1
**Duration:** 23 minutes (alert fire to rollback completion)

## Summary
A deploy shipped a feature-flag default change alongside unrelated code
changes. The flag change caused a 12x increase in downstream API error rate.
On-call spent 14 of the 23 minutes investigating the code diff before
checking the config/flag diff, delaying the rollback decision.

## Root Cause
The error-rate spike was caused entirely by a feature-flag default flip, not
by any code change in the same deploy. Triage initially focused on the code
diff because the deploy's commit message described a code refactor, and the
flag change was buried in a separate config file with no mention in the
commit message.

## Action Taken & Outcome
Once the flag change was identified, on-call reverted the flag directly
(faster than a full deploy rollback) and confirmed error rates returned to
baseline within 90 seconds. A full `rollback_deploy` was not necessary once
the actual cause was isolated.

## Notes
Triage should check config/flag diffs in parallel with code diffs from the
start, not as a fallback after the code diff turns up nothing — this is now
reflected in the failed-deploy-rollback runbook's triage steps. Diagnosis
confidence on the initial 14 minutes should be considered low in retrospect:
the investigation was searching the wrong artifact.
