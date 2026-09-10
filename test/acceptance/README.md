# Runtime acceptance procedure

This directory owns the **runtime probe** layer of the runtime acceptance
stack (introduced for issue #14). It defines what each LLM runtime probe must
prove, the exact minimal evidence that constitutes a PASS, and the fail-fast
rules the test controller must enforce. The wider workflow contract is
unchanged: no consumer (`professor-contact`, `professor-research`) may be
patched to make a probe pass.

**Testing authority**: the current Project Consensus governs harness, model,
fixture, and evidence rules for every runtime smoke in this repository. When
this README and the current consensus disagree, the consensus wins and this
README must be corrected.

## Ownership split

| Layer | Owns | Must NOT be asked to prove |
|---|---|---|
| Deterministic/source tests (`test/test_*.py`) | APM target declarations, Codex/OpenCode projection shape, traceability, `needs_input` schema, per-category interaction cardinality, SAME-child-resume wording, native-MCP/native-`question()` wording, endpoint resolution/transport contracts (`test/test_endpoints.py`, `test/test_endpoint_transport.py`, `test/test_endpoint_source_contract.py`), frozen business invariants (`test_issue14_source_contract.py`) | anything requiring a live LLM runtime |
| Headless Zotero MCP integration (`test/integration/`) | cleanup business behavior against a real isolated Zotero: duplicate detection, NFKC, Tier-1 vs report-only, canonical priority, plan generation, serial fail-stop mutation, mapping-not-written-on-failure, action log, verification, idempotent rerun | runtime wiring |
| Runtime probes (this directory) | only the runtime primitives that cannot be established deterministically: exact-name spawn, native MCP wiring, interaction bridge + SAME-child resume, OpenCode surface regression, endpoint override through installed surfaces | duplicate/canonical/plan/mutation business correctness |

Business invariants that are not yet well covered by the first two layers are
strengthened there — never by making an LLM smoke run the full cleaner skill.

## Current harness rules (Project Consensus)

1. **Codex runtime smokes run only through the existing eval server.** The
   controller sends a bounded prompt to the long-running eval server
   (`POST /eval`, port from `direnv exec . printenv EVAL_PORT`). The `command`
   field is the full `codex exec` parameter string, at minimum:
   `--json --ephemeral --skip-git-repo-check --sandbox workspace-write
   --cd "<fresh consumer>" --model <model> --config <overrides...> -- "<prompt>"`.
   Never invoke `codex` directly in the controller shell to bypass the eval
   service, and never treat a `source` of fixture env in the controller shell
   as env evidence: the eval `command` must inject endpoint overrides itself
   via `--config 'shell_environment_policy.set.ZOTERO_HTTP_URL="<fixture-http-url>"'`
   and `--config 'shell_environment_policy.set.ZOTERO_MCP_URL="<fixture-mcp-url>"'`,
   plus `--config sandbox_workspace_write.network_access=true` so the
   `workspace-write` sandbox can reach the fixture on localhost.
2. **Default Codex smoke profile**: `gpt-5.6-luna` with low reasoning
   (`--config 'model_reasoning_effort="low"'`). Switching to another
   profile/model is allowed only as the consensus permits when the default
   profile is unavailable; otherwise classify the run as a
   harness/model-availability blocker (`HARNESS_MODEL_AVAILABILITY`) — do not
   retry, and do not swap models to manufacture a PASS.
3. **OpenCode ordinary smoke model**: Big Pickle. Resolve the exact current
   row with `opencode models` (model id `big-pickle`) and pass the resolved
   `provider/model` to `opencode run`. If Big Pickle is unavailable, record a
   harness/model blocker; do not substitute another model for a PASS.
4. **Fixture provenance**: runtime smokes use the disposable Zotero fixture
   from the fixture repository at its exact clean SHA, started through the
   fixture repo's official scripts. Record `fixture_repo_sha`,
   `fixture_run_id`, the run's `ZOTERO_HTTP_URL` / `ZOTERO_MCP_URL`, and the
   run-unique sentinel used as feature evidence. Fixture readiness or port
   reachability alone is never a feature PASS: the installed owner surface
   must return the run-unique sentinel through the overridden endpoint.
5. **Clean consumers**: installed fresh from the **remote** final head SHA via
   the documented APM install command (`apm install <repo>#<FINAL_HEAD_SHA>
   --target <codex|opencode>`), never local/editable/symlinked/copied state,
   never hand-patched, never a user-global stale skill/agent. Any change to
   the final head SHA invalidates prior runtime acceptance.
6. Credentials are injected only by the local runtime environment (direnv);
   no key is ever placed in command arguments, fixtures, logs, or this
   repository. Provider/model config flags are configuration, not
   credentials.

### Probe evidence (applies to every harness transport)

1. PASS is based only on the probe's minimal evidence, asserted by the
   controller from logs/transcripts/response events, never on model
   self-report and never on receiving a final cleaner business JSON.
   Transcript/rollout scans must anchor to the payload event structure (e.g.
   `"payload":{"type":"function_call"`), otherwise they match instruction
   text and the probe degenerates into a vacuous pass. The streamed exec
   transcript carries no instruction echo, so it is the preferred evidence
   surface.
2. Evidence-complete ⇒ the probe stops immediately. The parent model never
   decides how long to keep polling.
3. Every probe runs under a wall-clock deadline. Exhaustion ⇒
   `HARNESS_DEADLINE`, never "ask the model to keep waiting".
4. Provider/model/approval availability failures (HTTP 402/403,
   payment/quota, region blocks, rate-limit exhaustion) ⇒
   `HARNESS_MODEL_AVAILABILITY`: stop, report, no `needs_input` routing, no
   retries, no provider/model policy change to get a green result. The benign
   `Model metadata ... not found` fallback message must not classify as
   availability failure.
5. The runtime process exiting without the evidence ⇒ `FAIL_NO_EVIDENCE` (an
   abnormal or ambiguous terminal state is a failure, not a wait state).
6. Thread-id expectations are asserted from the transcript's `thread.started`
   events, never taken from model claims.
7. Verdicts and elapsed seconds are printed as one JSON line per probe and
   must be recorded in the acceptance evidence. A probe that starts drifting
   toward full cleaner execution is a test-design regression: shrink the
   prompt/evidence, do not raise the deadline.

`codex_probe.sh` in this directory is the historical issue #14 direct-invocation
harness embodying rules 1–7; its fail-fast/evidence/classification behavior is
kept for deterministic coverage (`test_issue14_codex_probe_harness.py`). It is
**not** the current generic entry point: current Codex runtime smokes go
through the eval server as specified above.

## Codex probes

Each probe has exactly one compatibility question, a deterministic PASS
condition, and a hard stop as soon as the evidence appears.

### C1 — exact-name discovery/spawn

Evidence (then stop; do not proceed into snapshot/plan/business JSON):

1. clean consumer installed from remote final SHA;
2. fresh Codex session;
3. `spawn_agent` event with the spawned child sourced from the installed
   producer package;
4. the name `zotero-collection-cleaner` observed in the child's own rollout
   transcript (`CODEX_HOME/sessions/**`), proving the exact producer-owned
   agent spawned — not a user-global or lookalike;
5. canonical skill load/read observed (`zotero-collection-cleaner/SKILL.md`).

### C2 — native Zotero MCP wiring

Evidence (then stop; do not analyze the tree or generate a plan):

1. exact-name child spawns (as in C1);
2. one native read-only Zotero MCP call, preferably `get_collections`;
3. the response contains data from the isolated fixture;
4. no `skill_mcp()` production shim is invoked.

The Codex Zotero route stays native-MCP-only: bash `curl` is never a Zotero
path or reachability probe on Codex, and endpoint patches must not downgrade
this contract.

### C3 — interaction bridge / SAME-child resume

Smallest fixture/prompt that forces `root_selection`; no cleanup run.

Leg 1 evidence: child thread id `X`; child yields `needs_input` with
`category=root_selection` and `"multiple": true` (root selection is
multi-select; `canonical_tie_break` and `plan_confirmation` are single-select
— frozen deterministically by `test/test_issue14_codex_interaction_cardinality.py`).

Leg 2 evidence: the answer is delivered to **the same thread `X`** via the
eval `command`'s resume mechanism (`codex exec resume X` as the eval'd
command), and thread X produces its first post-resume event with context
retained. PASS at that point — no fresh snapshot, no plan, no final business
JSON.

The other two interaction types need no LLM run; their contract is frozen by
the deterministic cardinality gate.

### O1 — OpenCode regression smoke

1. clean OpenCode consumer from the same remote final SHA;
2. exact-name `zotero-collection-cleaner` spawnable via the native OpenCode
   path (ordinary smoke model: Big Pickle, resolved per the harness rules);
3. canonical skill load succeeds;
4. deployed agent keeps canonical OpenCode frontmatter and the native
   `question()` path (one minimal harmless interaction/read at most).

Stop there: no full `mode=plan` workflow, no plan/report regeneration, no
duplicate/scope re-evaluation.

## Final merge evidence checklist (per final remote SHA)

Any change to the final head invalidates prior runtime acceptance. On the
final SHA:

```bash
uv sync --locked
uv run --with pytest==8.4.2 pytest -q
bash test/integration/run_headless_zotero_mcp.sh   # or final-head CI equivalent
git diff --check
```

Then require final-head GitHub CI green and run C1/C2/C3/O1 from clean
consumers installed from the remote final SHA, recording per-probe timings
and — for endpoint-override smokes — the fixture run identity, the injected
`ZOTERO_HTTP_URL` / `ZOTERO_MCP_URL`, the run-unique sentinel, and the
deterministic zero-default-attempt evidence. No new lint/typecheck/build
toolchain is introduced by this procedure.
