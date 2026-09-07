# Issue #14 runtime acceptance procedure

This directory owns the **runtime probe** layer of the issue #14 acceptance
stack. It defines what each LLM runtime probe must prove, the exact minimal
evidence that constitutes a PASS, and the fail-fast rules the test controller
must enforce. The wider workflow contract is unchanged: no consumer
(`professor-contact`, `professor-research`, `scholarflow-codex`) may be patched
to make a probe pass.

## Ownership split

| Layer | Owns | Must NOT be asked to prove |
|---|---|---|
| Deterministic/source tests (`test/test_*.py`) | APM target declarations, Codex/OpenCode projection shape, traceability, `needs_input` schema, per-category interaction cardinality, SAME-child-resume wording, native-MCP/native-`question()` wording, mutation (non-vacuous) checks, frozen business invariants (`test_issue14_source_contract.py`) | anything requiring a live LLM runtime |
| Headless Zotero MCP integration (`test/integration/`) | cleanup business behavior against a real isolated Zotero: duplicate detection, NFKC, Tier-1 vs report-only, canonical priority, plan generation, serial fail-stop mutation, mapping-not-written-on-failure, action log, verification, idempotent rerun | runtime wiring |
| Runtime probes (this directory) | only the runtime primitives that cannot be established deterministically: exact-name spawn, native MCP wiring, interaction bridge + SAME-child resume, OpenCode surface regression | duplicate/canonical/plan/mutation business correctness |

Business invariants that are not yet well covered by the first two layers are
strengthened there — never by making an LLM smoke run the full cleaner skill.

## Codex probes

Each probe has exactly one compatibility question, a deterministic PASS
condition, and a hard stop as soon as the evidence appears. All consumers are
installed fresh from the **remote** final head SHA (never local/editable
state), with an isolated `CODEX_HOME` whose `mcp_servers.zotero` points at an
isolated disposable Zotero MCP endpoint. Codex is invoked through the project
consensus wrapper:

```
direnv exec <dir-under-the-direnv-tree> codex exec -p <profile> ...
```

The profile name is the maintainer-approved provider/model policy for the run
(passed to the harness via `--profile`; it defaults to `openrouter`). The
profile layer carries provider/model configuration; the credential it
references stays in the local runtime config and is never copied into this
repository, fixtures, logs, or command arguments.

Credentials are injected by direnv only; no key is ever placed in command
arguments, fixtures, logs, or this repository. Provider/model config flags
(e.g. `-c 'review_model=...'`) are configuration, not credentials.

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

### C3 — interaction bridge / SAME-child resume

Smallest fixture/prompt that forces `root_selection`; no cleanup run.

Leg 1 evidence: child thread id `X`; child yields `needs_input` with
`category=root_selection` and `"multiple": true` (root selection is
multi-select; `canonical_tie_break` and `plan_confirmation` are single-select
— frozen deterministically by `test/test_issue14_codex_interaction_cardinality.py`).

Leg 2 evidence: the answer is delivered to **the same thread `X`** via
`codex exec resume X`, and thread X produces its first post-resume event with
context retained. PASS at that point — no fresh snapshot, no plan, no final
business JSON.

The other two interaction types need no LLM run; their contract is frozen by
the deterministic cardinality gate.

### O1 — OpenCode regression smoke

1. clean OpenCode consumer from the same remote final SHA;
2. exact-name `zotero-collection-cleaner` spawnable via the native OpenCode
   path (project smoke-test model: Big Pickle);
3. canonical skill load succeeds;
4. deployed agent keeps canonical OpenCode frontmatter and the native
   `question()` path (one minimal harmless interaction/read at most).

Stop there: no full `mode=plan` workflow, no plan/report regeneration, no
duplicate/scope re-evaluation.

## Harness rules (`codex_probe.sh`)

1. PASS is based only on the probe's minimal evidence, asserted by the
   controller from logs/transcripts (`--evidence-regex` over the streamed
   transcript, codex stderr, and rollout dirs), never on model self-report and
   never on receiving a final cleaner business JSON. Rollout transcripts embed
   instructions, prompts and tool schemas as single-line JSON: any scan-dir
   pattern aimed at behavior must anchor to the payload event structure (e.g.
   `"payload":{"type":"function_call"`), otherwise it matches instruction text
   and the probe degenerates into a vacuous pass. The streamed exec transcript
   carries no instruction echo, so it is the preferred evidence surface.
2. Evidence-complete ⇒ codex is terminated immediately. The parent model never
   decides how long to keep polling.
3. Every probe runs under a wall-clock deadline (`--deadline-seconds`, default
   300). Exhaustion ⇒ `HARNESS_DEADLINE`, never "ask the model to keep
   waiting".
4. Provider/model/approval availability failures (HTTP 402/403, payment/quota,
   region blocks) ⇒ `HARNESS_MODEL_AVAILABILITY`: stop, report, no
   `needs_input` routing, no retries, no provider/model policy change to get a
   green result. The benign `Model metadata ... not found` fallback message
   must not classify as availability failure.
5. The codex process exiting without the evidence ⇒ `FAIL_NO_EVIDENCE` (an
   abnormal or ambiguous terminal state is a failure, not a wait state).
6. Thread-id expectations (`--expect-thread`) are asserted from the
   transcript's `thread.started` events.
7. Verdicts and elapsed seconds are printed as one JSON line per probe and
   must be recorded in the acceptance evidence. A probe that starts drifting
   toward full cleaner execution is a test-design regression: shrink the
   prompt/evidence, do not raise the deadline.

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
consumers installed from the remote final SHA, recording per-probe timings.
No new lint/typecheck/build toolchain is introduced by this procedure.
