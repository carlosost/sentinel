# Using Sentinel

This document explains how Sentinel actually gets invoked today, what it expects as
input, what's already wired up (even if mocked), what's flat-out missing for a real
deployment, and what would need ongoing upkeep once it's live. It's a companion to
`README.md` (what the project is) and `PROJECT_MEMORY.md` (why every decision was
made) — this file is about the practical "how do I run this / what do I feed it"
question.

## How it receives input today

Sentinel has no CLI, no HTTP API, and no listener of any kind. There are exactly two
ways to run it:

1. Call `build_graph()` (`src/graph/build.py`) directly from Python and invoke the
   resulting graph with a state dict.
2. Run `scripts/entrypoint.sh` in `smoke` mode, which does the same thing with a
   literal example state.

The graph's input is an `IncidentState` (`src/graph/state.py`), a `TypedDict`. The
only field that carries real signal is:

```python
{"raw_alert": "disk usage at 95% on db-primary"}
```

Every other field (`route`, `retrieved_docs`, `reranked_docs`, `relevance_grade`,
`retry_count`, `diagnosis`, `proposed_action`, `human_decision`, `execution_result`,
`postmortem_draft`, `thread_id`, guardrail verdicts, etc.) has to be explicitly
initialized to an empty/zero value before the first call — the sandbox stand-in for
LangGraph doesn't apply defaults for you. `scripts/entrypoint.sh` shows the full dict
shape.

In short: **`raw_alert` is the entire input surface today.** Everything downstream —
routing, retrieval, diagnosis, proposed remediation, human approval, execution,
postmortem — is derived from that one string.

## How to write a `raw_alert`

`raw_alert` is unstructured text — there's no required schema — but the router,
retriever, and diagnose nodes are all working from this string alone, so the more
context it carries, the better everything downstream performs. A good `raw_alert`
reads like a one-paragraph incident summary a human on-call engineer would type into
a chat, not a single keyword.

Include, where you have it:

- **What fired** (alert name/metric, or "deploy failed", "error spike", etc.)
- **Where** (service/host/region)
- **The signal** (the actual metric value, error message, or symptom)
- **Anything already known** (recent deploys, recent changes) — this is what lets
  `router` and `retriever` pull the right corpus (runbooks vs. postmortems vs.
  infra/code docs).

**Good examples:**

```text
Disk usage on db-primary (us-east-1) has been at 95%+ for the last 20 minutes.
PagerDuty alert "disk-utilization-critical" fired at 14:32 UTC. No recent deploys
to this host. Similar spike happened 3 weeks ago per a past postmortem.
```

```text
checkout-api p99 latency jumped from 180ms to 4.2s starting 09:05 UTC, right after
the v2.14.0 deploy finished rolling out. Error rate is still near zero — this looks
like a latency regression, not a crash.
```

```text
Datadog monitor "high-5xx-rate" triggered for payments-service: 5xx rate at 12%
over the last 5 minutes, up from a baseline of <0.1%. Started immediately after a
config change to the rate-limiter sidecar.
```

**Weak examples to avoid:**

```text
disk full
```

```text
something's wrong with checkout
```

These aren't invalid — Sentinel will still run them through the graph — but with
this little signal, `router`/`retriever` have almost nothing to match against, and
`diagnose` has to guess. The self-RAG loop (`grade_documents` retrying on low
relevance) exists partly to compensate for vague input like this, but it can't
invent context that was never in the alert to begin with.

## How to submit an alert to Sentinel

There's no CLI flag or API call for this yet (see the integration section below) —
submitting means building the graph and calling `.invoke()` (or `.stream()`/
`.invoke()` with a config, if you want to resume a paused HITL run later) directly in
Python. Every field in `IncidentState` (`src/graph/state.py`) needs to be present in
the dict you pass in; the sandbox stand-in for LangGraph doesn't fill in defaults for
you.

```python
from src.graph.build import build_graph

graph = build_graph()

incident_state = {
    "raw_alert": (
        "Disk usage on db-primary (us-east-1) has been at 95%+ for the last 20 "
        "minutes. PagerDuty alert \"disk-utilization-critical\" fired at 14:32 UTC. "
        "No recent deploys to this host."
    ),
    "guardrail_input_verdict": None,
    "guardrail_output_verdict": None,
    "rejection_reason": None,
    "route": None,
    "retrieved_docs": [],
    "reranked_docs": [],
    "relevance_grade": None,
    "retry_count": 0,
    "current_query": None,
    "diagnosis": None,
    "diagnosis_confidence": None,
    "proposed_action": None,
    "human_decision": None,
    "execution_result": None,
    "postmortem_draft": None,
    "thread_id": "incident-2026-06-23-001",  # unique per run — the checkpointer keys on this
}

result = graph.invoke(incident_state)
```

A few things worth knowing about that call:

- **`thread_id` must be unique per incident.** It's the checkpointer's key
  (`PostgresSaver`, ADR-002) — reusing one resumes a previous run's state instead of
  starting fresh.
- **The run can pause.** If `propose_action` comes up with anything `side_effecting`
  (per `src/tools/registry.py`), the graph pauses at `await_human_approval`
  (`interrupt()`, ADR-015) instead of returning a final result. A human (or, today,
  whatever script is standing in for the approval UI — there isn't one yet) has to
  resume that `thread_id` with a `human_decision` dict (`{"approved": bool,
  "modified_action": Optional[dict], "note": str}`) before execution can continue.
- **`scripts/entrypoint.sh smoke`** runs essentially this exact call with a canned
  `"smoke-test alert"` string — it's the quickest way to see the call shape exercised
  end to end (minus the LLM/embedding calls themselves, which raise
  `NotImplementedError` in this sandbox per ADR-021).

**If you actually run `bash scripts/entrypoint.sh smoke` in this sandbox, expect it
to fail** with:

```
NotImplementedError: Real model invocation requires langchain_openai (Open
Question #15); not available in this sandbox.
```

This is expected, not a bug. The graph builds fine and correctly reaches
`guardrail_input`, which calls `guardrail_check()` → `client_factory.get_chat_client(
).invoke()` — and that `invoke()` is still the ADR-021 stand-in, because there's no
network/PyPI access here to install `langchain_openai`. The script exits non-zero
rather than silently returning a fake `"safe"` verdict, per the project's
"never silently default" convention. To see the smoke check actually pass end to end,
you'd need to run it in the real Docker image (`infra/docker-compose.yml`) with real
dependencies installed and real API keys configured — not in this sandbox.

This is also exactly the gap the next section is about: today, *you* are the
integration — there's no automated path from a real alerting tool to this
`graph.invoke()` call.

## Is it meant to integrate with Sentry / Datadog / AWS / PagerDuty?

Yes, eventually — that's the obvious next step for an "alert comes in, copilot
triages it" tool — but **no integration code exists yet**. There is no webhook
receiver, no vendor-specific payload parser, and no HTTP server to receive one. The
tech-stack table in `README.md` lists FastAPI as the planned API layer, but it's
aspirational; nothing has been built against it. `PROJECT_MEMORY.md`'s Open Questions
section explicitly flags the HTTP API layer as undesigned.

What this means practically: hooking up a real alert source (a Sentry issue webhook,
a Datadog monitor notification, an AWS EventBridge rule, a PagerDuty incident
trigger) requires building, from scratch:

- An HTTP endpoint or queue consumer to receive the vendor payload.
- A per-vendor adapter that extracts a coherent alert summary from that payload and
  maps it into `raw_alert` (and ideally a few structured fields — service name,
  severity, alert source — that nothing in the current `IncidentState` schema has a
  place for yet).
- Auth for the inbound webhook (none exists anywhere in the project today).

None of this is hard, but none of it is started either. Today, the only way
something becomes a `raw_alert` is a human typing or pasting one in.

## What inputs already exist (even if mocked)

| Input | Status | Where |
|---|---|---|
| Incident alert text | Working — the one real input | `IncidentState.raw_alert` |
| RAG document corpus | **Stubbed, no seed data** | `scripts/ingest_corpora.py` expects markdown files under `corpora/{runbooks,postmortems,infra_code_docs}/*.md`; that directory doesn't exist in the repo. The in-memory store (`src/ingestion/document_store.py`) works structurally but has nothing in it. Embedding calls themselves raise `NotImplementedError` in this sandbox. |
| Remediation tool registry | Working as a registry, not executable | `src/tools/registry.py` defines four tools: `restart_service`, `rollback_deploy`, `page_secondary_oncall` (side-effecting) and `fetch_additional_logs` (read-only). Dispatch goes through a stand-in staging-API client that raises `NotImplementedError` — there's no real staging environment behind it. |
| Golden eval set | Synthetic but present | `evals/golden_incidents.jsonl` — incidents `INC-001`–`INC-003` with reference root cause, reference remediation, and a grading rubric. Notably references `revert_feature_flag`, which isn't actually in the tool registry — a known mismatch. |
| Guardrail red-team set | Synthetic but present | `evals/guardrail_redteam.jsonl` — labeled safe/unsafe examples (e.g. a prompt-injection attempt tagged unsafe/S1) used to check moderation accuracy. |

## What's missing entirely

A real production deployment of Sentinel would still need, from zero:

- A webhook/alert-ingestion listener and an HTTP API in general.
- Authn/authz for that API.
- A real vector database connection (Postgres + pgvector) — currently an in-memory
  dict stand-in.
- A real LLM gateway connection (LiteLLM proxy) and real model API keys — currently a
  stand-in client that raises `NotImplementedError`.
- A real execution target for remediation actions (the actual staging/production API
  the tools would call) — currently a stand-in with no backing service.
- A postmortem publishing destination — `write_postmortem` only produces draft text
  inside the graph state; it's never sent anywhere (no Confluence/Notion/git commit/
  ticketing integration).
- Seed corpus content (runbooks, past postmortems, infra docs) — the ingestion
  pipeline exists, but there's nothing to ingest yet.

This isn't a criticism of the project — it's a learning project built in a sandbox
with no network or package-install access, so every external dependency was
deliberately built as a named stand-in (`PROJECT_MEMORY.md`'s ADR-021) rather than
silently faked. The point of this section is just to be explicit about the gap
between "all 14 features pass their tests" and "this could take a real PagerDuty
alert today."

## What would need continuous, ongoing updates in a real deployment

A handful of inputs aren't "set once" — they'd need a refresh cadence once Sentinel
is handling real incidents:

- **The RAG corpus.** New runbooks and postmortems get written after every real
  incident; if they're not re-ingested, retrieval quality degrades over time. The
  golden eval set is currently 100% synthetic and would ideally get seeded from real
  past postmortems once any exist.
- **The golden eval set and guardrail red-team set.** Both need new entries as new
  incident types and new attack patterns show up — otherwise the eval gate measures
  an increasingly outdated slice of reality.
- **Self-RAG tuning knobs.** The relevance-grading threshold and the retry cap on the
  self-RAG loop are fixed constants today; they'd likely need periodic re-tuning
  against real traffic.
- **Gateway rate limits and budgets.** Per-key rate limits and spend caps in the
  LiteLLM config are exactly the kind of thing that needs revisiting as usage grows.
- **Guardrail precision/recall thresholds**, re-checked against the red-team set as
  it grows.
- **The fine-tuned embedding model pipeline.** Training pairs get exported from
  LangSmith traces (`scripts/export_finetune_pairs.py`), used to fine-tune
  (`scripts/finetune_embedding_model.py`), and gated by an A/B promotion check
  (`scripts/ab_eval_embedding_model.py`) before replacing the base embedding model.
  This whole loop is meant to re-run periodically, not once.
- **The tool registry**, as new remediation actions get added to match what the
  on-call team actually needs to do.

`PROJECT_MEMORY.md` §7 (Open Questions/Risks) tracks all of these explicitly, along
with the single largest one: Open Question #15, the full list of sandbox stand-ins
that still need to be swapped for real packages and re-verified end to end before any
of this is production-real.
