# Runbook: When to Page Secondary On-Call

**Symptom:** Primary on-call is triaging an incident that is either (a)
escalating faster than mitigation steps can keep pace, or (b) outside their
service-ownership expertise.

**Triage steps:**
1. Check the incident's severity classification. Sev-1/Sev-2 incidents lasting
   longer than 20 minutes without a mitigation in progress should trigger a
   secondary page by default — this is a floor, not a ceiling.
2. Identify whether the affected system has a designated owning team distinct
   from the primary on-call's usual rotation. If so, page that team's
   secondary directly rather than routing through the generic escalation
   chain.
3. If the primary on-call is also the one who caused the incident (e.g., via
   a recent deploy), page a secondary regardless of severity, to keep a fresh
   set of eyes on the decision to roll back or not.

**Remediation:** Paging is not itself a remediation — it exists to get a
second qualified person into the incident channel. Continue triage in
parallel; do not block on the secondary's response if a safe mitigating
action is already identified.

**Escalation:** If neither primary nor secondary on-call is responsive within
10 minutes of a Sev-1, escalate to the engineering manager on the incident
escalation roster.
