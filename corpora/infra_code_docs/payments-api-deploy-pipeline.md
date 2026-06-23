# Infra Doc: payments-api Deploy Pipeline

`payments-api` deploys via a two-stage pipeline: build (container image,
tagged by commit SHA) then deploy (rolling update across 3 AZs, one AZ at a
time, with a 60-second health-check gate between AZs).

**Health check:** the startup health check calls the fraud-scoring service
(a downstream dependency) over mTLS using a certificate issued by the
internal CA, rotated automatically every 90 days by a separate cert-manager
job. If the fraud-scoring call fails for any reason — including an expired
certificate — the health check fails and the rolling update halts, but an
**already-running** instance that starts failing this same check post-deploy
will also restart-loop, since the check is also used as the liveness probe,
not just the startup probe. This dual use is a known sharp edge: a restart
cannot fix a dependency-side failure, only a code/config rollback or fixing
the dependency can.

**Rollback:** `rollback_deploy` redeploys the previous commit SHA's image
across all 3 AZs using the same rolling-update mechanism as a forward deploy
— there is no separate fast-path rollback mechanism in v1. Typical rollback
time is 4-6 minutes end to end (all 3 AZs, with health-check gating).

**Feature flags:** flag defaults are defined in a separate config file
(`flags.yaml`) deployed independently of code, on its own faster pipeline
with no health-check gating. This means a flag-only change can ship and take
effect within seconds, which is faster than triage usually expects when
reading deploy timestamps from the code pipeline alone.
