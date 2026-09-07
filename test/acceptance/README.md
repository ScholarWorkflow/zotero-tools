# Issue #14 runtime acceptance procedure

This directory owns the **runtime probe** layer of the issue #14 acceptance
stack. It defines what each LLM runtime probe must prove, the exact minimal
evidence that constitutes a PASS, and the fail-fast rules the test controller
must enforce. The wider workflow contract is unchanged: no consumer
(`professor-contact`, `professor-research`, `scholarflow-codex`) may be patched
to make a probe pass.

Since issue #16, formal JSON/JSONL evidence is judged **structurally**:

> PASS must be decided deterministically by the checked-in controller from
> structured runtime evidence. JSON/JSONL is parsed with `jq`; XML (if it ever
> appears) would be parsed with `xmllint`. grep/regex are restricted to
> unstructured logs and auxiliary diagnostics and must never replace the
> structured parser for formal event evidence.

## Ownership split

| Layer | Owns | Must NOT be asked to prove |
|---|---|---|
| Deterministic/source tests (`test/test_*.py`) | APM target declarations, Codex/OpenCode projection shape, traceability, `needs_input` schema, per-category interaction cardinality, SAME-child-resume wording, native-MCP/native-`question()` wording, mutation (non-vacuous) checks, frozen business invariants (`test_issue14_source_contract.py`), fixture-driven evidence-contract gates (`test_issue16_runtime_evidence.py`) | anything requiring a live LLM runtime |
| Headless Zotero MCP integration (`test/integration/`) | cleanup business behavior against a real isolated Zotero: duplicate detection, NFKC, Tier-1 vs report-only, canonical priority, plan generation, serial fail-stop mutation, mapping-not-written-on-failure, action log, verification, idempotent rerun | runtime wiring |
| Runtime probes (this directory) | only the runtime primitives that cannot be established deterministically: exact-name spawn, native MCP wiring, interaction bridge + SAME-child resume, OpenCode surface regression | duplicate/canonical/plan/mutation business correctness |

Business invariants that are not yet well covered by the first two layers are
strengthened there — never by making an LLM smoke run the full cleaner skill.

## Layout

```
test/acceptance/
├── codex_probe.sh            # process lifecycle: launch/deadline/poll/verdict
├── runtime_evidence.sh       # structured evidence controller (tri-state CLI)
├── runtime_evidence.jq       # checked-in named evidence predicates
├── fixtures/                 # minimal sanitized measured-shape event fixtures
│   ├── common/               # shared stream fixture + availability text cases
│   ├── c1/ c2/ c3_leg1/ c3_leg2/
└── README.md
```

The event shapes frozen in `runtime_evidence.jq` were measured from the real
codex-cli 0.153.x runtime during the PR #15 final acceptance run. If the
runtime event schema ever changes, update the measured schema, the fixtures
and the predicates together — never reintroduce text scanning.

`jq` is a **test-harness prerequisite**, not a production dependency of the
`zotero-tools` package. `codex_probe.sh` and `runtime_evidence.sh` refuse to
start any model work without it (`HARNESS_PREREQUISITE`) and never fall back
to grep/Python ad-hoc parsing.

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

### Named evidence contracts

The harness no longer accepts caller-supplied `--evidence-regex` /
`--absent-regex`. PASS semantics are defined exclusively by the checked-in
named contracts:

```
--evidence-contract c1|c2|c3-leg1|c3-leg2
```

`--name` remains a display-only label for the run. Callers may pass dynamic
DATA only (structured child/thread ids derived by the controller, the
`--sentinel` fixture value for C2, `--expect-thread` for C3 leg 2) — never a
predicate program. Deterministic fixture tests and the live harness call the
same `runtime_evidence.sh` controller and the same `runtime_evidence.jq`
predicates.

### C1 — exact-name discovery/spawn (`--evidence-contract c1`)

Structured PASS conditions (then stop; do not proceed into
snapshot/plan/business JSON):

1. the current-run stream contains a real `spawn_agent` collab event, and the
   target child thread id is derived structurally from its
   `receiver_thread_ids` (prompt/instruction JSON fragments can never produce
   a child id; `item.started` collab events carry empty receiver lists);
2. the parent thread's rollout (matched by structured `session_meta.payload`
   id, never by filename tokens) contains a real `spawn_agent`
   `function_call` whose **parsed arguments** carry
   `agent_type == "zotero-collection-cleaner"`, correlated by `call_id` to a
   `function_call_output` whose parsed `agent_id` equals the target child id
   (failed spawn attempts with non-JSON outputs legitimately never
   correlate);
3. the target child's own fresh rollout contains a real `function_call`
   whose parsed arguments reference
   `zotero-collection-cleaner/SKILL.md`, correlated by `call_id` to a
   successful execution output;
4. scan-dir candidates are restricted to files newer than the probe's start
   marker whose structured session identity belongs to this run's derived
   child ids.

The following can never satisfy C1: the skill name in a prompt, in tool
schemas, or in any instruction echo (only parsed `function_call` arguments
count); stale rollouts; another child's rollout (structured session identity
scoping); the model claiming it loaded the skill in prose.

### C2 — native Zotero MCP wiring (`--evidence-contract c2 --sentinel <fixture-text>`)

Structured PASS conditions (then stop; do not analyze the tree or generate a
plan):

1. target child identity structurally confirmed (as in C1);
2. a real native MCP `function_call` with name `get_collections` and
   namespace `mcp__zotero` (checked-in constants) whose parsed arguments are
   a JSON object;
3. a `function_call_output` **correlated by `call_id`** to that call whose
   parsed output content contains the isolated fixture sentinel — a
   call and a response that are two independent hits prove nothing;
4. a structural negative gate: no real `function_call` named `skill_mcp` in
   any scoped child rollout. Instructions forbidding the shim are text, not
   calls, and never trip the gate;
5. no business invariants: no tree analysis, plan generation or cleaner final
   JSON is required.

### C3 leg 1 — `needs_input` (`--evidence-contract c3-leg1`)

Structured PASS conditions: the stream's `wait` collab event correlates to
the target child both through `receiver_thread_ids` and the `agents_states`
key, and the child's message — parsed as JSON with `fromjson` — satisfies the
interaction contract as object fields:

- `control == "needs_input"`
- `interaction.category == "root_selection"`
- `interaction.multiple == true`
- `interaction.question` is a string
- `interaction.options` is a non-empty array

Measured-schema note: the declared envelope also contains
`interaction.resume_token`, but the measured runtime may omit it in a valid
emission; same-child continuity is proven structurally in leg 2, so the
predicate does not require the token. A prose question with no control JSON
is a model-fidelity failure and stays NO_MATCH — it never degrades to text
matching.

### C3 leg 2 — SAME-child resume (`--evidence-contract c3-leg2 --expect-thread X`)

Structured PASS conditions (in stream order):

1. the resume invocation is `codex exec ... resume X`;
2. the stream contains exactly one `thread.started` event and its
   `thread_id` is strictly equal to the leg-1 child id `X`; any other thread
   id is `FAIL_THREAD_MISMATCH`;
3. a post-resume structured runtime event (agent message / tool call /
   reasoning / collab event) appears **after** that `thread.started`;
4. PASS immediately at that point — no fresh snapshot, no plan, no final
   business JSON.

A child-id string inside message text proves nothing. Benign metadata `error`
items between the two (e.g. the measured model-mismatch warning) are
tolerated and do not break the ordering.

### O1 — OpenCode regression smoke

Unchanged by issue #16 and untouched by the jq refactor: clean OpenCode
consumer from the same remote final SHA; exact-name
`zotero-collection-cleaner` spawnable via the native OpenCode task path
(project smoke-test model: Big Pickle); canonical skill load; deployed agent
keeps canonical OpenCode frontmatter and the native `question()` path (one
minimal harmless interaction/read at most). Stop there: no full `mode=plan`
workflow, no plan/report regeneration, no duplicate/scope re-evaluation.

## Harness rules (`codex_probe.sh`)

1. PASS is based only on the probe's minimal evidence, evaluated by the
   checked-in structured evidence controller (`runtime_evidence.sh` +
   `runtime_evidence.jq`) over the streamed exec transcript and the child
   rollout transcripts under `--scan-dir`. It is never based on model
   self-report and never on receiving a final cleaner business JSON.
2. The controller distinguishes three internal results, mapped to verdicts by
   the harness: `MATCH` → `PASS_EVIDENCE`; `NO_MATCH` → keep polling;
   `MALFORMED` → `FAIL_MALFORMED_EVIDENCE`. A newline-terminated record that
   participates in the judgment and fails jq parsing is MALFORMED and never
   falls back to text scanning. A live writer's unfinished trailing record
   (no terminating newline) is pending framing: it is excluded from that
   poll's parse and re-read next round — it cannot mask a completed-line
   parse error.
3. Evidence-complete ⇒ codex is terminated immediately (TERM → bounded wait
   → KILL). The parent model never decides how long to keep polling.
4. Every probe runs under a wall-clock deadline (`--deadline-seconds`, default
   300). Exhaustion ⇒ `HARNESS_DEADLINE`, never "ask the model to keep
   waiting".
5. Provider/model/approval availability failures (HTTP 402/403, payment/quota,
   region blocks, rate-limit exhaustion, model-withdrawal 404 copy) ⇒
   `HARNESS_MODEL_AVAILABILITY`: stop, report, no `needs_input` routing, no
   retries, no provider/model policy change to get a green result. The
   classifier greps the unstructured provider-text surfaces (codex stderr and
   provider error events in the stream) — diagnostic classification only,
   never event evidence. The benign `Model metadata ... not found` fallback
   message and a bare `HTTP 404` must not classify as availability failure.
6. The codex process exiting without the evidence ⇒ `FAIL_NO_EVIDENCE` (an
   abnormal or ambiguous terminal state is a failure, not a wait state). A
   parser failure is never disguised as `FAIL_NO_EVIDENCE`.
7. Thread-id expectations (`--expect-thread`) are asserted structurally from
   the stream's `thread.started` events via the controller.
8. Verdicts (`PASS_EVIDENCE`, `HARNESS_DEADLINE`, `HARNESS_MODEL_AVAILABILITY`,
   `FAIL_NO_EVIDENCE`, `FAIL_THREAD_MISMATCH`, `FAIL_MALFORMED_EVIDENCE`,
   `HARNESS_PREREQUISITE`) and elapsed seconds are printed as one JSON line
   per probe and must be recorded in the acceptance evidence. A probe that
   starts drifting toward full cleaner execution is a test-design regression:
   shrink the prompt/evidence, do not raise the deadline.

## Final merge evidence checklist (per final remote SHA)

Any change to the final head invalidates prior runtime acceptance. On the
final SHA:

```bash
jq --version
bash -n test/acceptance/codex_probe.sh
bash -n test/acceptance/runtime_evidence.sh
uv sync --locked
uv run --with pytest==8.4.2 pytest -q
bash test/integration/run_headless_zotero_mcp.sh   # or final-head CI equivalent
git diff --check
```

Then require final-head GitHub CI green and re-run C1/C2/C3 leg 1/C3 leg 2
from clean consumers installed from the remote final SHA with the named
contracts above, recording per-probe verdicts and timings. O1 re-runs only if
the OpenCode acceptance path changed. No new lint/typecheck/build toolchain is
introduced by this procedure.
