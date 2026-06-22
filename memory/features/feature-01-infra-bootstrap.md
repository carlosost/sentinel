# Feature 01 — Infra Bootstrap

**Phase introduced:** Phase 4
**Status:** Done — implemented and tested (against sandbox shims; see Implementation Status below)
**PMA sections touched:** ADR-007 (new), ADR-021 (new), §3 Pillar 3, §3 Pillar 5, §6 Feature Log, §7 (new Open Question #15), §9 item 1

## Feature Description

Bootstrap local infra: docker-compose for Postgres+pgvector, Redis, and the LiteLLM
proxy; implement `src/gateway/client_factory.py` as the only path to model clients;
stub `guardrail_check()`; define the initial `IncidentState` schema and an empty graph
with just `entry`→`END`.

## Step 1 — Conflict Check

| ADR / Contract | Verdict |
|---|---|
| ADR-001 (LangGraph as backbone) | No conflict — this feature creates the empty `StateGraph` shell ADR-001 calls for. |
| ADR-002 (Postgres checkpointer, no SQLite) | No conflict — docker-compose provisions Postgres for both pgvector and the checkpointer per this ADR. Checkpointer wiring itself is not yet attached to the empty graph (no interrupts exist yet); that's correct sequencing, not a conflict. |
| ADR-003 (LiteLLM gateway in front of every call) | No conflict — `client_factory.py` is exactly the enforcement point ADR-003 specifies. |
| ADR-004 (Guardrail stub wired from commit 1) | No conflict — this feature *is* "commit 1." Stub verdict, real wiring, as specified. |
| ADR-005 (Eval strategy / golden dataset) | No conflict — out of scope for this feature (covered by roadmap item 2); nothing here contradicts it. |
| ADR-006 (Static lint enforcing gateway-only imports) | No conflict — this feature is the first point the lint rule has something to enforce against (`client_factory.py` existing). |
| §5.1 IncidentState schema | No conflict — this feature instantiates the schema as already specified, no fields changed. |
| §5.2 Graph skeleton | No conflict — this feature implements only the `entry`→`END` shell; no edges beyond that are claimed or contradicted. |
| §5.3 Gateway contract | No conflict — directly implements it. |

**Verdict: ADDITIVE.** No existing ADR or contract is contradicted; this feature is first-implementation of already-decided infrastructure, not a new architectural choice — except for a few concrete details (directory layout, pinned versions, lint mechanics) that the PMA left implicit. Those are captured in a new ADR-007 below rather than silently decided in code.

## New ADR

### ADR-007: Repository scaffolding for infra bootstrap
- **Context:** ADRs 001–006 establish *what* must be true (gateway-only calls, stubbed guardrails, Postgres-backed checkpointing) but not the concrete repo layout or pinned tool versions needed to start coding.
- **Decision:**
  - Repo layout: `src/gateway/client_factory.py`, `src/guardrails/check.py`, `src/graph/state.py`, `src/graph/build.py`, `infra/docker-compose.yml`.
  - `docker-compose.yml` provisions: `postgres:16` with `pgvector` extension enabled, `redis:7`, and `litellm` (proxy mode) as separate services, networked together.
  - `client_factory.py` exposes `get_chat_client(model: str)` and `get_embedding_client(model: str)`, both constructing clients with `base_url` read from `LITELLM_PROXY_URL` env var — no other construction path exists in the codebase.
  - `guardrail_check(text: str, direction: Literal["input","output"]) -> GuardrailVerdict` lives in `src/guardrails/check.py`; v1 body is `return GuardrailVerdict(verdict="safe", reason="stub")` unconditionally.
  - The CI lint from ADR-006 is implemented as `scripts/lint_gateway_usage.sh`, a `grep -rn` check run in CI and as a pre-commit hook.
- **Consequences:** Every subsequent feature builds inside this layout; changing it later is itself a retrofit.
- **Status:** Accepted.

## Pillar Impact

- [x] 3. Guardrails — `guardrail_check()` stub implemented and wired (function exists; callers come in later features).
- [x] 5. AI Gateway — `client_factory.py` implemented as the sole model-client construction path; fallback/caching/rate-limit *configuration* itself is NOT in scope here (tracked as roadmap item 12) — this feature only guarantees all calls are routed through one chokepoint.
- [ ] 1. Advanced RAG Mechanics — not touched.
- [ ] 2. Human-in-the-Loop — not touched (no interrupts exist yet).
- [ ] 4. LLM Evals — not touched.
- [ ] 6. Fine-Tuning Integration — not touched.

## Gherkin

```gherkin
Feature: Gateway client factory is the sole path to model clients

  Scenario: chat client is constructed against the gateway, not a provider directly
    Given the environment variable LITELLM_PROXY_URL is set to "http://litellm:4000"
    When client_factory.get_chat_client("gpt-4o-mini") is called
    Then the returned client's base_url equals "http://litellm:4000"

  Scenario: embedding client is constructed against the gateway
    Given the environment variable LITELLM_PROXY_URL is set to "http://litellm:4000"
    When client_factory.get_embedding_client("text-embedding-3-small") is called
    Then the returned client's base_url equals "http://litellm:4000"

@guardrail
Feature: Guardrail stub is wired but inert

  Scenario: guardrail_check returns a stub-safe verdict for input direction
    Given any input text
    When guardrail_check(text, direction="input") is called
    Then it returns a GuardrailVerdict with verdict "safe"

  Scenario: guardrail_check returns a stub-safe verdict for output direction
    Given any output text
    When guardrail_check(text, direction="output") is called
    Then it returns a GuardrailVerdict with verdict "safe"

Feature: Initial graph skeleton compiles and runs

  Scenario: empty graph runs from entry to END unchanged
    Given a StateGraph built with only an entry node and an edge to END
    And a minimal valid IncidentState
    When the graph is invoked
    Then it terminates without error
    And the returned state equals the input state

Feature: IncidentState schema enforces required keys

  Scenario: a state dict missing thread_id fails schema validation
    Given a state dict with all IncidentState keys except "thread_id"
    When it is validated against the IncidentState schema
    Then validation fails with a missing-key error
```

## PyTest Skeletons (all Deterministic Tier — pure infra mechanics, no model-output judgment involved)

```python
# tests/gateway/test_client_factory.py

def test_get_chat_client_uses_gateway_base_url(monkeypatch):
    """Deterministic Tier. Asserts client_factory routes through LITELLM_PROXY_URL,
    never a provider SDK default. No live network call."""
    ...

def test_get_embedding_client_uses_gateway_base_url(monkeypatch):
    """Deterministic Tier. Same contract as above, embedding client variant."""
    ...


# tests/guardrails/test_check_stub.py

def test_guardrail_check_input_returns_stub_safe():
    """Deterministic Tier. Asserts the stub's *shape and value* (verdict == "safe"),
    not moderation accuracy — accuracy is out of scope until roadmap item 13."""
    ...

def test_guardrail_check_output_returns_stub_safe():
    """Deterministic Tier. Same as above, output direction."""
    ...


# tests/graph/test_skeleton.py

def test_empty_graph_invoke_returns_unchanged_state():
    """Deterministic Tier. Asserts the compiled entry->END graph is a no-op on state,
    confirming the skeleton wires correctly before any node logic exists."""
    ...


# tests/graph/test_state_schema.py

def test_incident_state_missing_thread_id_fails_validation():
    """Deterministic Tier. Schema/shape check only."""
    ...
```

## Blast Radius

Additive — no existing ADR superseded, no existing test/spec files broken (none exist
yet at this point in the project).

## Implementation Status (real code/tests, sandbox-constrained)

This feature was implemented and tested for real in this session. The execution
sandbox has no PyPI egress (confirmed via repeated `pip install`/`pip download`
failures against `langgraph`, `langchain-core`, `langchain-openai`, `pydantic`, and
`pytest` — all rejected by the network proxy). **ADR-021** documents the resulting
substitution. Concretely, against the skeletons above:

- `src/gateway/client_factory.py` — implemented as designed, except `get_chat_client`/
  `get_embedding_client` return stdlib `dataclass` stand-ins (`_ChatClient`/
  `_EmbeddingClient`) instead of `ChatOpenAI`/`OpenAIEmbeddings`. `GatewayConfigError`
  on a missing `LITELLM_PROXY_URL` is real, as designed.
- `src/guardrails/check.py` — implemented exactly as designed; no substitution was
  needed (already stdlib-only `TypedDict`/`Literal`).
- `src/graph/state.py` — implemented exactly as designed (stdlib-only `TypedDict`);
  no substitution needed.
- `src/graph/build.py` / `src/graph/_compat.py` — `_compat.py` is a new file, not in
  the original skeleton: a minimal linear-only `StateGraph`/`START`/`END` stand-in
  for `langgraph.graph`. It explicitly cannot do branching or cycles
  (`GraphNotLinearError`) — adequate for this feature's `entry -> END` shell, but
  **not** adequate for Features 04/06/09 once implementation reaches them.
- `scripts/lint_gateway_usage.sh` — implemented, with two corrections found while
  writing its own test (see below): (1) restricted to scanning `src/` and `scripts/`
  only, not the whole repo, since scanning `tests/` caused the script to flag its
  own test fixtures' string literals as violations; (2) added an optional
  target-directory argument so its test can point it at a synthetic `/tmp` fixture
  tree instead of writing a real violating file into this repo.
- Tests: written with stdlib `unittest` instead of `pytest` (also blocked), in
  `tests/gateway/test_client_factory.py`, `tests/guardrails/test_check.py`,
  `tests/graph/test_build.py`, `tests/graph/test_compat.py` (new — covers the
  `_compat.py` shim's own behavior and failure modes), and
  `tests/test_lint_gateway_usage.py`. The originally-sketched
  `test_incident_state_missing_thread_id_fails_validation` scenario was **dropped**,
  not silently ignored: `TypedDict` performs no runtime validation, and the
  validation library that would provide it (`pydantic`) is also blocked in this
  sandbox. Revisit once Open Question #15 is resolved.
- Result: **14/14 tests pass** via `python3 -m unittest discover -s tests -v`.
- One operational incident during this work: an earlier version of the lint
  script's test wrote a synthetic bad-import fixture directly into `src/` and tried
  to delete it afterward — the workspace mount does not permit unlinking files
  (confirmed: neither Python's `os.unlink`, `shutil.move`, nor `sudo rm` succeed).
  This left two harmless orphaned files in `src/` (`tmp6i7_b1m5.py`,
  `tmph94x_g5b.py`), now neutralized to empty comment-only stubs explaining their
  origin; they can be deleted by hand outside this environment if desired. The test
  itself was rewritten to build its fixture tree under `tempfile.TemporaryDirectory()`
  (sandbox-local `/tmp`) instead, so this cannot recur.

**Definition of Done (§8.5) status:** (1) Gherkin scenarios above are covered by the
test files listed; (2)/(3) deterministic tests are real and pass; (4) not
applicable — this feature has no Probabilistic Tier surface; (5) LangSmith
structural assertions not applicable yet (no tracing wired until later features);
(6) this Feature Log row is updated. Caveat: "passing" currently means passing
against ADR-021's shims, not the real `langgraph`/`langchain-openai` stack — Open
Question #15 is the explicit tracker for closing that gap.
