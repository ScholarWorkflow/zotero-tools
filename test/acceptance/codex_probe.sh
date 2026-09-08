#!/usr/bin/env bash
# Bounded Codex runtime probe harness for the issue #14/#16 acceptance.
#
# Encoded harness rules (see README.md in this directory):
#   1. a probe PASSES only on its minimal evidence, asserted by the checked-in
#      structured evidence controller (runtime_evidence.sh + runtime_evidence.jq)
#      from the streamed transcript and child rollout transcripts — never on a
#      final cleaner business JSON, never on model self-report, and never on
#      caller-supplied regex/text scanning of JSON/JSONL;
#   2. a wall-clock deadline bounds every service request; exhaustion =>
#      HARNESS_DEADLINE;
#   3. provider/model/approval availability errors => HARNESS_MODEL_AVAILABILITY:
#      stop after the service response, do not route through needs_input, do not
#      retry, do not change provider/model policy;
#   4. the service returning without the evidence => FAIL_NO_EVIDENCE;
#   5. thread-id expectations (--expect-thread) are asserted structurally from
#      the stream's thread.started events, never from model claims;
#   6. a service transport/schema failure => HARNESS_SERVICE_FAILURE or
#      FAIL_MALFORMED_EVIDENCE;
#   7. a newline-terminated invalid JSON record participating in the judgment
#      => FAIL_MALFORMED_EVIDENCE (never falls back to text scanning).
#
# The Codex process is owned by the project eval service. This harness sends
# the complete Codex CLI parameter text in the JSON `command` field; it
# never starts `codex`, copies provider credentials, or selects a
# provider/model on the command line.
#
# Usage:
#   codex_probe.sh --name c1 --prompt-file p.txt --log-dir logs/ \
#     --consumer-dir <clean consumer> \
#     --evidence-contract <c1|c2|c3-leg1|c3-leg2> \
#     [--sentinel <isolated fixture text>] [--scan-dir <dir with *.jsonl> ...] \
#     [--expect-thread <thread-id>] [--deadline-seconds <300>] \
#     [--service-url <http://127.0.0.1:8765/eval>]
set -uo pipefail

DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
EVIDENCE_CTL="$DIR/runtime_evidence.sh"

PROBE_NAME="" PROMPT_FILE="" LOG_DIR="" CONSUMER_DIR=""
EXPECT_THREAD="" DEADLINE=300 SERVICE_URL="${CODEX_EVAL_URL:-http://127.0.0.1:8765/eval}"
CONTRACT="" SENTINEL="" SCAN_DIRS=()

while [[ $# -gt 0 ]]; do
  case "$1" in
    --name) PROBE_NAME=$2; shift 2 ;;
    --prompt-file) PROMPT_FILE=$2; shift 2 ;;
    --log-dir) LOG_DIR=$2; shift 2 ;;
    --consumer-dir) CONSUMER_DIR=$2; shift 2 ;;
    --evidence-contract) CONTRACT=$2; shift 2 ;;
    --sentinel) SENTINEL=$2; shift 2 ;;
    --scan-dir) SCAN_DIRS+=("$2"); shift 2 ;;
    --expect-thread) EXPECT_THREAD=$2; shift 2 ;;
    --deadline-seconds) DEADLINE=$2; shift 2 ;;
    --service-url) SERVICE_URL=$2; shift 2 ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done

for required in PROBE_NAME PROMPT_FILE LOG_DIR CONSUMER_DIR CONTRACT; do
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
if ! command -v curl >/dev/null 2>&1; then
  echo "HARNESS_PREREQUISITE: curl is required by the eval service client" >&2
  finish HARNESS_PREREQUISITE
fi

SERVICE_PID=""
terminate() {
  [[ -z "$SERVICE_PID" ]] && return 0
  kill -TERM "$SERVICE_PID" 2>/dev/null || return 0
  for _ in 1 2 3 4 5; do
    kill -0 "$SERVICE_PID" 2>/dev/null || return 0
    sleep 1
  done
  kill -KILL "$SERVICE_PID" 2>/dev/null || true
}
trap terminate EXIT

# The eval API owns Codex lifecycle, provider/model selection and credentials.
# Build the complete parameter text here so the service executes in the fresh
# consumer, while retaining both the complete service response and its
# normalized event stream. jq's @sh quoting keeps paths/prompts data-only even
# though the service receives one command string.
REQUEST_JSON="$LOG_DIR/$PROBE_NAME.request.json"
RESPONSE_JSON="$LOG_DIR/$PROBE_NAME.eval.json"
HTTP_STATUS="$LOG_DIR/$PROBE_NAME.http-status.txt"
TRANSPORT_LOG="$LOG_DIR/$PROBE_NAME.transport.log"
COMMAND_FILE="$LOG_DIR/$PROBE_NAME.command.txt"
CODEX_CD=$(jq -nr --arg value "$CONSUMER_DIR" '$value | @sh') || finish HARNESS_PREREQUISITE
CODEX_PROMPT=$(jq -Rrs '@sh' "$PROMPT_COPY") || finish HARNESS_PREREQUISITE
printf '%s --cd %s -- %s' \
  '--json --skip-git-repo-check --sandbox workspace-write' \
  "$CODEX_CD" "$CODEX_PROMPT" >"$COMMAND_FILE" \
  || finish HARNESS_PREREQUISITE
jq -n --rawfile command "$COMMAND_FILE" --argjson timeout "$DEADLINE" \
  '{command: $command, timeout: $timeout}' >"$REQUEST_JSON" \
  || finish HARNESS_PREREQUISITE

# Availability failures are classified from unstructured provider/service text
# only. Formal event evidence is still judged exclusively by jq below. The
# benign metadata fallback and a bare HTTP 404 intentionally do not match.
AVAILABILITY_RE='HTTP 40[23]|HTTP 404.*unavailable|Rate limit exceeded|Payment Required|not available in your region|insufficient_quota|quota exceeded'

curl --silent --show-error --max-time "$((DEADLINE + 20))" \
  --output "$RESPONSE_JSON" --write-out '%{http_code}' \
  -X POST "$SERVICE_URL" \
  -H 'Content-Type: application/json' \
  --data-binary "@$REQUEST_JSON" \
  >"$HTTP_STATUS" 2>"$TRANSPORT_LOG" &
SERVICE_PID=$!

# The service is synchronous, so evidence can only be evaluated after its
# complete response arrives. This loop still enforces the probe deadline.
while kill -0 "$SERVICE_PID" 2>/dev/null; do
  NOW=$(date +%s)
  if (( NOW - START >= DEADLINE )); then
    terminate
    finish HARNESS_DEADLINE
  fi
  sleep 1
done
wait "$SERVICE_PID" 2>/dev/null
SERVICE_RC=$?
SERVICE_PID=""

if grep -qE "$AVAILABILITY_RE" "$TRANSPORT_LOG" 2>/dev/null; then
  finish HARNESS_MODEL_AVAILABILITY
fi
if (( SERVICE_RC != 0 )); then
  echo "HARNESS_SERVICE_FAILURE: eval service request failed" >&2
  finish HARNESS_SERVICE_FAILURE
fi
HTTP_CODE=$(tr -d '[:space:]' <"$HTTP_STATUS")
if [[ ! "$HTTP_CODE" =~ ^2[0-9][0-9]$ ]]; then
  if grep -qE "$AVAILABILITY_RE" "$RESPONSE_JSON" 2>/dev/null; then
    finish HARNESS_MODEL_AVAILABILITY
  fi
  echo "HARNESS_SERVICE_FAILURE: eval service returned HTTP $HTTP_CODE" >&2
  finish HARNESS_SERVICE_FAILURE
fi

# Parse the service envelope before looking at any event. A malformed or
# schema-incomplete response is malformed evidence, never a text-scan
# opportunity.
if ! jq -e 'type == "object" and (.output | type == "object") and
  (.passed | type == "boolean") and (.output.events | type == "array") and
  (.output.exit_code | type == "number")' \
  "$RESPONSE_JSON" >/dev/null 2>"$STDERR_LOG"; then
  echo "FAIL_MALFORMED_EVIDENCE: invalid eval service response" >&2
  finish FAIL_MALFORMED_EVIDENCE
fi
jq -r '.output.stderr // empty' "$RESPONSE_JSON" >"$STDERR_LOG"
jq -c '.output.events[]' "$RESPONSE_JSON" >"$STREAM_LOG"

if grep -qE "$AVAILABILITY_RE" "$STDERR_LOG" 2>/dev/null \
   || grep -qE "$AVAILABILITY_RE" "$STREAM_LOG" 2>/dev/null; then
  finish HARNESS_MODEL_AVAILABILITY
fi
if ! jq -e '.passed == true and .output.exit_code == 0' "$RESPONSE_JSON" >/dev/null; then
  finish FAIL_NO_EVIDENCE
fi

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

if thread_mismatch; then finish FAIL_THREAD_MISMATCH; fi
contract_check
rc=$?
if (( rc == 0 )); then finish PASS_EVIDENCE; fi
if (( rc == 2 )); then finish FAIL_MALFORMED_EVIDENCE; fi
finish FAIL_NO_EVIDENCE
