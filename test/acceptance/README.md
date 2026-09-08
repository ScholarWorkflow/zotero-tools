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
├── codex_probe.sh            # eval-service request/deadline/response/verdict
├── runtime_evidence.sh       # structured evidence controller (tri-state CLI)
├── runtime_evidence.jq       # checked-in named evidence predicates
├── fixtures/                 # minimal sanitized measured-shape event fixtures
│   ├── common/               # shared stream fixture + availability text cases
│   ├── c1/ c2/ c3_leg1/ c3_leg2/
└── README.md
```

The event shapes frozen in `runtime_evidence.jq` are the structured events
returned in the eval service's `output.events` array. If the service/runtime
event schema ever changes, update the measured schema, the fixtures and the
predicates together — never reintroduce text scanning.

`jq` is a **test-harness prerequisite**, not a production dependency of the
`zotero-tools` package. `codex_probe.sh` and `runtime_evidence.sh` refuse to
start any model work without it (`HARNESS_PREREQUISITE`) and never fall back
to grep/Python ad-hoc parsing.

## Codex probes

Each probe has exactly one compatibility question and a deterministic PASS
condition. All consumers are installed fresh from the **remote** final head
SHA (never local/editable state), with an isolated disposable Zotero MCP
endpoint. Codex is invoked by the project consensus eval service. The harness
runs the `curl` request through `direnv exec` so the service port comes from
`EVAL_PORT`, and sends the complete Codex parameter text, including the
prepared consumer's workspace root:

```
curl -X POST http://127.0.0.1:$EVAL_PORT/eval \
  -H 'Content-Type: application/json' \
  -d '{
    "command": "--json --skip-git-repo-check --sandbox workspace-write --cd /tmp/test-project --model MODEL_NAME -- \"检查当前项目的测试\"",
    "timeout": 300
  }'
```

The checked-in harness writes the JSON request to a log file and passes that
file with curl's `-d` option, preserving the same request while keeping prompt
text out of the shell command line.

The service owns Codex lifecycle, provider/model selection and credentials. Its
default policy is `openrouter` for cost control, but that policy is not an
acceptance condition. The harness does not pass `-p`, provider/model flags or
credentials. Invoke a probe with `--consumer-dir <clean consumer>`; this is
rendered as Codex's documented `--cd <consumer>` argument inside `command`.

The complete service response is retained as `<name>.eval.json`; its
`output.events` array is normalized to `<name>.stream.jsonl` for the shared
controller. No key is placed in command arguments, fixtures, logs, or this
repository.

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

### Target-child and session scoping

All child-scoped evidence is gated on the **confirmed target child**, never on
"any child this run spawned":

1. Candidate pool: ids structurally spawned in the run's own stream
   (`receiver_thread_ids` of real `spawn_agent` collab events). Candidates
   alone never confirm a target.
2. Confirmation: the parent thread's rollout (matched by structured
   `session_meta.payload.id` against the stream's `thread.started`) contains a
   real `spawn_agent` `function_call` whose parsed arguments carry
   `agent_type == "zotero-collection-cleaner"`, correlated by `call_id` to a
   `function_call_output` whose parsed `agent_id` is the child id
   (controller mode `derive-target-ids`). Only correlation-confirmed ids that
   the stream also spawned scope child evidence.
3. Correlation is the only source of target identity: another child spawned
   in the same run can neither contribute evidence (C2 native call, C3 leg 1
   `wait`/`agents_states`) nor trip the C2 shim negative gate on the target's
   behalf. Until a parent rollout confirms a target, no candidate scopes
   evidence and every contract stays NO_MATCH — a candidate can never
   terminate a live probe before the exact-name correlation exists.
4. Identity-first malformed scoping: a fresh rollout's structured identity is
   read before any byte of it is judged. A rollout whose identity is
   unreadable or belongs to another session never participates — it cannot
   contribute evidence and cannot make the verdict `FAIL_MALFORMED_EVIDENCE`.
   A rollout scoped to the probe (its own thread id or a confirmed target
   child id) is validated in full, and a newline-terminated invalid record in
   it is `FAIL_MALFORMED_EVIDENCE` — never a text-scan fallback.

### C1 — exact-name discovery/spawn (`--evidence-contract c1`)

Structured PASS conditions (then stop; do not proceed into
snapshot/plan/business JSON):

1. the current-run stream contains a real `spawn_agent` collab event, and the
   target child thread id is one of the ids structurally derived from its
   `receiver_thread_ids` (prompt/instruction JSON fragments can never produce
   a child id; `item.started` collab events carry empty receiver lists);
2. the target child id is **confirmed** by exact-name correlation in the
   parent thread's rollout (matched by structured `session_meta.payload` id,
   never by filename tokens): a real `spawn_agent` `function_call` whose
   **parsed arguments** carry `agent_type == "zotero-collection-cleaner"`,
   correlated by `call_id` to a `function_call_output` whose parsed
   `agent_id` equals the target child id (failed spawn attempts with non-JSON
   outputs legitimately never correlate). Unconfirmed candidates never scope
   C1 evidence — until the parent rollout confirms a target, C1 stays
   NO_MATCH;
3. the target child's own fresh rollout contains a real `exec_command`
   `function_call` whose structured `arguments.cmd` runs `cat` on
   `zotero-collection-cleaner/SKILL.md`, correlated by `call_id` to a
   successful execution output; a command that only echoes or mentions the
   path is not a skill read;
4. scan-dir candidates are restricted to files newer than the probe's start
   marker whose structured session identity belongs to this run's evidence
   scope (own thread id, confirmed target child ids).

The following can never satisfy C1: the skill name in a prompt, in tool
schemas, or in any instruction echo (only parsed `function_call` arguments
count); stale rollouts; another child's rollout (structured session identity
scoping); the model claiming it loaded the skill in prose.

### C2 — native Zotero MCP wiring (`--evidence-contract c2 --sentinel <fixture-text>`)

Structured PASS conditions (then stop; do not analyze the tree or generate a
plan):

1. target child identity structurally confirmed (as in C1) — native-call and
   no-shim evidence is read exclusively from the confirmed target child's
   rollout; other children spawned in the same run can neither satisfy nor
   trip these gates;
2. a real native MCP `function_call` with name `get_collections` and
   namespace `mcp__zotero` (checked-in constants) whose parsed arguments are
   a JSON object;
3. a `function_call_output` **correlated by `call_id`** to that call whose
   parsed output content contains the isolated fixture sentinel — a
   call and a response that are two independent hits prove nothing;
4. a structural negative gate: no real `function_call` named `skill_mcp` in
   the confirmed target child's rollout. Instructions forbidding the shim are
   text, not calls, and never trip the gate;
5. no business invariants: no tree analysis, plan generation or cleaner final
   JSON is required.

### C3 leg 1 — `needs_input` (`--evidence-contract c3-leg1`)

Structured PASS conditions: the stream's `wait` collab event correlates to
the target child — the correlation-confirmed one (see target-child and
session scoping above), so a valid `needs_input` emitted by another spawned
child never satisfies leg 1 — both through `receiver_thread_ids` and the
`agents_states` key, and the child's message — parsed as JSON with
`fromjson` — satisfies the interaction contract as object fields:

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

1. the service-returned stream contains exactly one `thread.started` event and its
   `thread_id` is strictly equal to the leg-1 child id `X`; any other thread
   id is `FAIL_THREAD_MISMATCH`;
2. a post-resume structured runtime event (agent message / tool call /
   reasoning / collab event) appears **after** that `thread.started`;
3. PASS after the service response is complete — no fresh snapshot, no plan, no final
   business JSON.

A child-id string inside message text proves nothing. Benign metadata `error`
items between the two are tolerated and do not break the ordering. The service
owns the underlying continuation invocation; the probe asserts only the
returned structured SAME-child evidence.

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
   the harness: `MATCH` → `PASS_EVIDENCE`; `NO_MATCH` after the service
   response → `FAIL_NO_EVIDENCE`;
   `MALFORMED` → `FAIL_MALFORMED_EVIDENCE`. A newline-terminated record that
   participates in the judgment and fails jq parsing is MALFORMED and never
   falls back to text scanning. A live writer's unfinished trailing record
   (no terminating newline) is pending framing: it is excluded from that
   poll's parse and re-read next round — it cannot mask a completed-line
   parse error. Rollouts are attributed by their structured
   `session_meta.payload.id` before any byte is judged: only probe-scoped
   rollouts are validated, and an unrelated session's rollout — even a
   malformed one — never affects the verdict.
3. The eval service is synchronous. The harness evaluates evidence after the
   complete response and cannot terminate the service-owned Codex process
   mid-request.
4. Every service request runs under a wall-clock deadline
   (`--deadline-seconds`, default 300). Local exhaustion or the eval service's
   HTTP 504 timeout response ⇒ `HARNESS_DEADLINE`.
5. Provider/model/approval availability failures (HTTP 402/403, payment/quota,
   region blocks, rate-limit exhaustion, model-withdrawal 404 copy) ⇒
   `HARNESS_MODEL_AVAILABILITY`: stop, report, no `needs_input` routing, no
   retries, no provider/model policy change to get a green result. The
   classifier greps the unstructured provider-text surfaces (service transport
   text and `output.stderr`) — diagnostic classification only,
   never event evidence. The benign `Model metadata ... not found` fallback
   message and a bare `HTTP 404` must not classify as availability failure.
6. The service returning without the evidence ⇒ `FAIL_NO_EVIDENCE` (an
   abnormal or ambiguous terminal state is a failure, not a wait state). A
   parser failure is never disguised as `FAIL_NO_EVIDENCE`.
7. Thread-id expectations (`--expect-thread`) are asserted structurally from
   the stream's `thread.started` events via the controller.
8. Verdicts (`PASS_EVIDENCE`, `HARNESS_DEADLINE`, `HARNESS_MODEL_AVAILABILITY`,
   `HARNESS_SERVICE_FAILURE`, `FAIL_NO_EVIDENCE`, `FAIL_THREAD_MISMATCH`,
   `FAIL_MALFORMED_EVIDENCE`, `HARNESS_PREREQUISITE`) and elapsed seconds are printed as one JSON line
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
