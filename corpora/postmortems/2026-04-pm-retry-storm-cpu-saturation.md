# Postmortem: Payments API CPU Saturation from Retry Storm

**Date:** 2026-04-03
**Severity:** Sev-1
**Duration:** 31 minutes (alert fire to full resolution)

## Summary

A dependency (the fraud-scoring microservice) began returning HTTP 503 after a
misconfigured rate limit was applied during a routine config push. The payments
API's retry policy had no exponential backoff cap — retries amplified load
6× at peak, saturating all payments-api pods at 98% CPU and pushing p99
checkout latency above 8 seconds.

## Timeline

| Time | Event |
|------|-------|
| 14:02 | Fraud-scoring config push lands; rate-limit threshold set to 10 % of correct value |
| 14:04 | Fraud-scoring starts returning 503 to payments-api |
| 14:05 | Payments-api retry storm starts; CPU climbs from 35% to 80% |
| 14:08 | p99 latency alert fires (SLO breach) |
| 14:09 | On-call acknowledges; starts triage |
| 14:14 | Root cause identified (fraud-scoring 503s visible in dependency dashboard) |
| 14:17 | Fraud-scoring config reverted; 503s stop |
| 14:18 | Retry storm subsides; CPU returns to 40% |
| 14:22 | p99 latency back within SLO |
| 14:33 | All-clear; postmortem scheduled |

## Root Cause

Two compounding issues:
1. The fraud-scoring config push lowered the per-service rate limit from 5,000
   req/s to 50 req/s — a typo (missing a zero) that passed config linting
   because the schema only enforces the field type, not a sensible range.
2. The payments-api retry policy retried on 503 with a fixed 100 ms delay and
   no jitter or backoff cap. Under sustained 503s, retry volume grew
   proportional to concurrency × retry count — approximately 6× the baseline
   request volume.

## Action Taken & Outcome

The on-call reverted the fraud-scoring config to the previous known-good value.
No code change was required. Recovery was immediate once 503s stopped.

## Follow-up Items

1. Add a minimum-value guard to the fraud-scoring rate-limit config schema.
2. Replace the fixed-delay retry in payments-api with exponential backoff +
   jitter (capped at 30 s) and a circuit breaker (open after 50% errors over
   10 s).
3. Add a synthetic canary that fires an alert if fraud-scoring success rate
   drops below 99% for more than 60 seconds — catching this before it cascades.
4. The postmortem template did not include a "dependency health" section; add
   one so future on-calls check dependency dashboards earlier in triage.
