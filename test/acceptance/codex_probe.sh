#!/usr/bin/env bash
# Bounded, fail-fast Codex runtime probe harness for the issue #14/#16
# acceptance.
#
# Encoded harness rules (see README.md in this directory):
#   1. a probe PASSES only on its minimal evidence, asserted by the checked-in
#      structured evidence controller (runtime_evidence.sh + runtime_evidence.jq)
#      from the streamed transcript and child rollout transcripts — never on a
#      final cleaner business JSON, never on model self-report, and never on
#      caller-supplied regex/text scanning of JSON/JSONL;
#   2. evidence-complete => codex is terminated immediately (hard stop), so the
#      parent model never decides how long to keep polling;
#   3. a wall-clock deadline bounds every probe; exhaustion => HARNESS_DEADLINE;
#   4. provider/model/approval availability errors => HARNESS_MODEL_AVAILABILITY:
#      stop immediately, do not route through needs_input, do not retry, do not
#      change provider/model policy;
#   5. the codex process exiting without the evidence => FAIL_NO_EVIDENCE;
#   6. thread-id expectations (--expect-thread) are asserted structurally from
#      the stream's thread.started events, never from model claims;
#   7. a newline-terminated invalid JSON record participating in the judgment
#      => FAIL_MALFORMED_EVIDENCE (never falls back to text scanning).
#
# Credentials are never passed as arguments or logged: codex runs under
# `direnv exec` and inherits OPENROUTER_API_KEY from the user's approved
# .envrc. Only model/provider CONFIG flags are accepted, via --codex-arg.
#
# Usage:
#   codex_probe.sh --name c1 --prompt-file p.txt --log-dir logs/ \
#     --repo-root <dir under the direnv tree> --consumer-dir <clean consumer> \
#     --codex-home <isolated CODEX_HOME> \
#     --evidence-contract <c1|c2|c3-leg1|c3-leg2> \
#     [--sentinel <isolated fixture text>] [--scan-dir <dir with *.jsonl> ...] \
#     [--expect-thread <thread-id>] [--resume-thread <thread-id>] \
#     [--deadline-seconds <300>] [--codex-arg '<arg>' ...] [--profile <name>]
set -uo pipefail

DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
EVIDENCE_CTL="$DIR/runtime_evidence.sh"

PROBE_NAME="" PROMPT_FILE="" LOG_DIR="" REPO_ROOT="" CONSUMER_DIR="" CODEX_HOME=""
EXPECT_THREAD="" RESUME_THREAD="" DEADLINE=300 PROFILE="openrouter"
CONTRACT="" SENTINEL="" SCAN_DIRS=() CODEX_ARGS=()

while [[ $# -gt 0 ]]; do
  case "$1" in
    --name) PROBE_NAME=$2; shift 2 ;;
    --prompt-file) PROMPT_FILE=$2; shift 2 ;;
    --log-dir) LOG_DIR=$2; shift 2 ;;
    --repo-root) REPO_ROOT=$2; shift 2 ;;
    --consumer-dir) CONSUMER_DIR=$2; shift 2 ;;
    --codex-home) CODEX_HOME=$2; shift 2 ;;
    --evidence-contract) CONTRACT=$2; shift 2 ;;
    --sentinel) SENTINEL=$2; shift 2 ;;
    --scan-dir) SCAN_DIRS+=("$2"); shift 2 ;;
    --expect-thread) EXPECT_THREAD=$2; shift 2 ;;
    --resume-thread) RESUME_THREAD=$2; shift 2 ;;
    --deadline-seconds) DEADLINE=$2; shift 2 ;;
    --codex-arg) CODEX_ARGS+=("$2"); shift 2 ;;
    --profile) PROFILE=$2; shift 2 ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done

for required in PROBE_NAME PROMPT_FILE LOG_DIR REPO_ROOT CONSUMER_DIR CODEX_HOME CONTRACT; do
  if [[ -z "${!required}" ]]; then echo "--${required//-/_} is required" >&2; exit 2; fi
done
case "$CONTRACT" in c1|c2|c3-leg1|c3-leg2) ;; *)
  echo "--evidence-contract must be one of: c1 c2 c3-leg1 c3-leg2" >&2; exit 2 ;;
esac
if [[ "$CONTRACT" == "c2" && -z "$SENTINEL" ]]; then
  echo "--sentinel is required for contract c2 (isolated fixture data)" >&2; exit 2
fi
if [[ ! -x "$EVIDENCE_CTL" ]]; then echo "missing $EVIDENCE_CTL" >&2; exit 2; fi

mkdir -p "$LOG_DIR"
STREAM_LOG="$LOG_DIR/$PROBE_NAME.stream.jsonl"
STDERR_LOG="$LOG_DIR/$PROBE_NAME.stderr.log"
LAST_LOG="$LOG_DIR/$PROBE_NAME.last.txt"
VERDICT_JSON="$LOG_DIR/$PROBE_NAME.verdict.json"
PROMPT_COPY="$LOG_DIR/$PROBE_NAME.prompt.txt"
cp "$PROMPT_FILE" "$PROMPT_COPY"
: >"$STREAM_LOG"; : >"$STDERR_LOG"
# Rollout scan marker: only files created after this moment count as evidence,
# so transcripts left by earlier probes can never satisfy this run's gates.
START_MARKER="$LOG_DIR/$PROBE_NAME.start-marker"
touch "$START_MARKER"

START=$(date +%s)

finish() {
  local verdict=$1 elapsed
  elapsed=$(( $(date +%s) - START ))
  printf '{"probe":"%s","verdict":"%s","elapsed_seconds":%d,"deadline_seconds":%d}\n' \
    "$PROBE_NAME" "$verdict" "$elapsed" "$DEADLINE" | tee "$VERDICT_JSON"
  if [[ "$verdict" == PASS_EVIDENCE ]]; then
    echo "probe $PROBE_NAME PASSED on minimal evidence in ${elapsed}s"
    exit 0
  fi
  printf 'probe %s verdict=%s in %ss\n' "$PROBE_NAME" "$verdict" "$elapsed" >&2
  exit 1
}

# Controller prerequisite: without jq the structured evidence contract cannot
# be evaluated. Refuse before starting any model work and never fall back to
# grep/Python ad-hoc parsing.
if ! command -v jq >/dev/null 2>&1; then
  echo "HARNESS_PREREQUISITE: jq is required by the evidence controller" >&2
  finish HARNESS_PREREQUISITE
fi

PID=""
terminate() {
  [[ -z "$PID" ]] && return 0
  pkill -TERM -P "$PID" 2>/dev/null || true
  kill -TERM "$PID" 2>/dev/null || return 0
  for _ in 1 2 3 4 5; do kill -0 "$PID" 2>/dev/null || return 0; sleep 1; done
  pkill -KILL -P "$PID" 2>/dev/null || true
  kill -KILL "$PID" 2>/dev/null || true
}
trap terminate EXIT

RESUME_ARGS=()
if [[ -n "$RESUME_THREAD" ]]; then RESUME_ARGS=(resume "$RESUME_THREAD"); fi
CODEX_ARGS_Q=""
if [[ ${#CODEX_ARGS[@]} -gt 0 ]]; then CODEX_ARGS_Q=$(printf '%q ' "${CODEX_ARGS[@]}"); fi
RESUME_ARGS_Q=""
if [[ ${#RESUME_ARGS[@]} -gt 0 ]]; then RESUME_ARGS_Q=$(printf '%q ' "${RESUME_ARGS[@]}"); fi

direnv exec "$REPO_ROOT" bash -lc "\
cd '$CONSUMER_DIR' && export CODEX_HOME='$CODEX_HOME' && \
codex exec -p "$PROFILE" --skip-git-repo-check \
--dangerously-bypass-approvals-and-sandbox --disable guardian_approval \
$CODEX_ARGS_Q \
--json -o '$LAST_LOG' $RESUME_ARGS_Q \
<'$PROMPT_COPY' >'$STREAM_LOG' 2>'$STDERR_LOG'" &
PID=$!

# Availability failures observed on this harness (rule 4), classified on the
# unstructured provider text surfaces (codex stderr and the stream's provider
# error events). Tight patterns on purpose: the benign "Model metadata ...
# not found" fallback must not match, and a bare HTTP 404 must not match
# either — the 404 arm additionally requires the "unavailable"
# model-withdrawal wording (e.g. OpenRouter free-tier deprecation copy).
# Rate-limit exhaustion (quota-type, rule 4) is matched on the provider's
# verbatim "Rate limit exceeded" wording.
# Note: keep regexes portable — BSD grep caps {n,m} repetition at 255; prefer
# `.*` (line-oriented, never crosses lines) over bounded repetition.
# Availability text is DIAGNOSTIC classification only; JSON/JSONL event
# evidence is decided exclusively by the structured controller.
AVAILABILITY_RE='HTTP 40[23]|HTTP 404.*unavailable|Rate limit exceeded|Payment Required|not available in your region|insufficient_quota|quota exceeded'

# Run one evaluation of the named evidence contract. Echoes the controller's
# stderr diagnostics; maps its tri-state exit code to 0/1/2.
contract_check() {
  local args=(check --contract "$CONTRACT" --stream "$STREAM_LOG" \
    --start-marker "$START_MARKER")
  local dir
  for dir in ${SCAN_DIRS[@]+"${SCAN_DIRS[@]}"}; do args+=(--scan-dir "$dir"); done
  [[ -n "$EXPECT_THREAD" ]] && args+=(--expect-thread "$EXPECT_THREAD")
  [[ -n "$SENTINEL" ]] && args+=(--sentinel "$SENTINEL")
  local rc=0
  bash "$EVIDENCE_CTL" "${args[@]}" >&2 || rc=$?
  case "$rc" in
    0|1|2) return "$rc" ;;
    *)  echo "evidence controller failure (rc=$rc)" >&2; return 2 ;;
  esac
}

# Structural resume-safety gate: if the resume stream's thread.started events
# do not all carry the expected thread id, the run can never become a valid
# SAME-child resume. Data comes from the controller's structured parse.
thread_mismatch() {
  [[ -n "$EXPECT_THREAD" ]] || return 1
  local ids rc=0
  ids=$(bash "$EVIDENCE_CTL" thread-ids --stream "$STREAM_LOG" 2>/dev/null) || rc=$?
  (( rc == 0 )) || return 1   # no thread.started yet: nothing to mismatch
  local id
  for id in $ids; do
    [[ "$id" == "$EXPECT_THREAD" ]] || return 0
  done
  return 1
}

VERDICT=""
while :; do
  NOW=$(date +%s)
  if (( NOW - START >= DEADLINE )); then VERDICT="HARNESS_DEADLINE"; terminate; break; fi
  if grep -qE "$AVAILABILITY_RE" "$STDERR_LOG" 2>/dev/null \
     || grep -qE "$AVAILABILITY_RE" "$STREAM_LOG" 2>/dev/null; then
    VERDICT="HARNESS_MODEL_AVAILABILITY"; terminate; break
  fi
  if thread_mismatch; then VERDICT="FAIL_THREAD_MISMATCH"; terminate; break; fi
  contract_check
  rc=$?
  if (( rc == 0 )); then VERDICT="PASS_EVIDENCE"; terminate; break; fi
  if (( rc == 2 )); then VERDICT="FAIL_MALFORMED_EVIDENCE"; terminate; break; fi
  if ! kill -0 "$PID" 2>/dev/null; then
    wait "$PID" 2>/dev/null
    # final evidence re-check after exit (the child may have flushed just
    # before exiting); a process exit without evidence stays FAIL_NO_EVIDENCE
    contract_check
    rc=$?
    if (( rc == 0 )); then VERDICT="PASS_EVIDENCE"
    elif (( rc == 2 )); then VERDICT="FAIL_MALFORMED_EVIDENCE"
    else VERDICT="FAIL_NO_EVIDENCE"; fi
    break
  fi
  sleep 1
done

finish "$VERDICT"
