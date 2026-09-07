#!/usr/bin/env bash
# Bounded, fail-fast Codex runtime probe harness for the issue #14 acceptance.
#
# Encoded harness rules (see README.md in this directory):
#   1. a probe PASSES only on its minimal evidence, asserted by the controller
#      from logs/transcripts — never on a final cleaner business JSON;
#   2. evidence-complete => codex is terminated immediately (hard stop), so the
#      parent model never decides how long to keep polling;
#   3. a wall-clock deadline bounds every probe; exhaustion => HARNESS_DEADLINE;
#   4. provider/model/approval availability errors => HARNESS_MODEL_AVAILABILITY:
#      stop immediately, do not route through needs_input, do not retry, do not
#      change provider/model policy;
#   5. the codex process exiting without the evidence => FAIL_NO_EVIDENCE;
#   6. thread-id expectations (--expect-thread) are asserted from logs, not
#      taken from model claims.
#
# Credentials are never passed as arguments or logged: codex runs under
# `direnv exec` and inherits OPENROUTER_API_KEY from the user's approved
# .envrc. Only model/provider CONFIG flags are accepted, via --codex-arg.
#
# Usage:
#   codex_probe.sh --name c1 --prompt-file p.txt --log-dir logs/ \
#     --repo-root <dir under the direnv tree> --consumer-dir <clean consumer> \
#     --codex-home <isolated CODEX_HOME> \
#     --evidence-regex '<ERE>' [--evidence-regex '<ERE>' ...] \
#     [--absent-regex '<ERE>' ...] [--scan-dir <dir with *.jsonl> ...] \
#     [--expect-thread <thread-id>] [--resume-thread <thread-id>] \
#     [--deadline-seconds <300>] [--codex-arg '<arg>' ...]
set -uo pipefail

PROBE_NAME="" PROMPT_FILE="" LOG_DIR="" REPO_ROOT="" CONSUMER_DIR="" CODEX_HOME=""
EXPECT_THREAD="" RESUME_THREAD="" DEADLINE=300
EVIDENCE=() ABSENT=() SCAN_DIRS=() CODEX_ARGS=()

while [[ $# -gt 0 ]]; do
  case "$1" in
    --name) PROBE_NAME=$2; shift 2 ;;
    --prompt-file) PROMPT_FILE=$2; shift 2 ;;
    --log-dir) LOG_DIR=$2; shift 2 ;;
    --repo-root) REPO_ROOT=$2; shift 2 ;;
    --consumer-dir) CONSUMER_DIR=$2; shift 2 ;;
    --codex-home) CODEX_HOME=$2; shift 2 ;;
    --evidence-regex) EVIDENCE+=("$2"); shift 2 ;;
    --absent-regex) ABSENT+=("$2"); shift 2 ;;
    --scan-dir) SCAN_DIRS+=("$2"); shift 2 ;;
    --expect-thread) EXPECT_THREAD=$2; shift 2 ;;
    --resume-thread) RESUME_THREAD=$2; shift 2 ;;
    --deadline-seconds) DEADLINE=$2; shift 2 ;;
    --codex-arg) CODEX_ARGS+=("$2"); shift 2 ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done

for required in PROBE_NAME PROMPT_FILE LOG_DIR REPO_ROOT CONSUMER_DIR CODEX_HOME; do
  if [[ -z "${!required}" ]]; then echo "--${required//-/_} is required" >&2; exit 2; fi
done
if [[ ${#EVIDENCE[@]} -eq 0 ]]; then
  echo "at least one --evidence-regex is required (rule 1: pass on minimal evidence only)" >&2
  exit 2
fi

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

# Child-thread scoping: rollout transcripts embed prompts, instructions and
# tool schemas, so scan-dir evidence is only meaningful inside the spawned
# child's OWN rollout file. The controller derives the child thread id from the
# stream's spawn events (never from model claims) and restricts scan-dir
# matching to files whose name carries that id.
CHILD_IDS=""
update_child_ids() {
  local ids
  ids=$(grep -oE '"receiver_thread_ids":\["[0-9a-f-]+' "$STREAM_LOG" 2>/dev/null |
    grep -oE '[0-9a-f-]{16,}' | sort -u | tr '\n' ' ')
  CHILD_IDS="$CHILD_IDS $ids"
}

# All evidence assertions run against the controller-owned logs, never against
# model self-reports: the streamed exec transcript, codex stderr, and (when
# provided) the per-thread rollout transcripts under --scan-dir. Scan-dir files
# are filtered to those created after this probe started, so transcripts left
# by earlier probes can never satisfy this run's gates.
matched_somewhere() {
  local re=$1
  grep -qE "$re" "$STREAM_LOG" 2>/dev/null && return 0
  grep -qE "$re" "$STDERR_LOG" 2>/dev/null && return 0
  local dir f id skip
  for dir in ${SCAN_DIRS[@]+"${SCAN_DIRS[@]}"}; do
    [[ -d "$dir" ]] || continue
    while IFS= read -r -d '' f; do
      skip=1
      for id in $CHILD_IDS; do
        case "$f" in *"$id"*) skip=0; break ;; esac
      done
      [[ "$skip" == 1 ]] && continue
      grep -qE "$re" "$f" 2>/dev/null && return 0
    done < <(find "$dir" -name '*.jsonl' -newer "$START_MARKER" -type f -print0 2>/dev/null)
  done
  return 1
}

RESUME_ARGS=()
if [[ -n "$RESUME_THREAD" ]]; then RESUME_ARGS=(exec resume "$RESUME_THREAD"); fi
CODEX_ARGS_Q=""
if [[ ${#CODEX_ARGS[@]} -gt 0 ]]; then CODEX_ARGS_Q=$(printf '%q ' "${CODEX_ARGS[@]}"); fi
RESUME_ARGS_Q=""
if [[ ${#RESUME_ARGS[@]} -gt 0 ]]; then RESUME_ARGS_Q=$(printf '%q ' "${RESUME_ARGS[@]}"); fi

START=$(date +%s)
direnv exec "$REPO_ROOT" bash -lc "\
cd '$CONSUMER_DIR' && export CODEX_HOME='$CODEX_HOME' && \
codex exec -p openrouter --skip-git-repo-check \
--dangerously-bypass-approvals-and-sandbox --disable guardian_approval \
$CODEX_ARGS_Q \
--json -o '$LAST_LOG' $RESUME_ARGS_Q \
<'$PROMPT_COPY' >'$STREAM_LOG' 2>'$STDERR_LOG'" &
PID=$!

# Availability failures observed on this harness (rule 4). Tight patterns on
# purpose: the benign "Model metadata ... not found" fallback must not match.
# Note: keep regexes portable — BSD grep caps {n,m} repetition at 255; prefer
# `.*` (line-oriented, never crosses lines) over bounded repetition. Rollout
# transcripts embed instructions, prompts and tool schemas as single-line JSON,
# so behavioral evidence against --scan-dir MUST anchor to the payload event
# structure (e.g. `"payload":{"type":"function_call"`), never to bare words
# that also occur in instruction/config text.
AVAILABILITY_RE='HTTP 40[23]|Payment Required|not available in your region|insufficient_quota|quota exceeded'

VERDICT=""
while :; do
  NOW=$(date +%s)
  update_child_ids
  if (( NOW - START >= DEADLINE )); then VERDICT="HARNESS_DEADLINE"; terminate; break; fi
  if matched_somewhere "$AVAILABILITY_RE"; then
    VERDICT="HARNESS_MODEL_AVAILABILITY"; terminate; break
  fi
  ALL_FOUND=1
  for re in ${EVIDENCE[@]+"${EVIDENCE[@]}"}; do
    if ! matched_somewhere "$re"; then ALL_FOUND=0; break; fi
  done
  if (( ALL_FOUND )); then VERDICT="PASS_EVIDENCE"; terminate; break; fi
  if ! kill -0 "$PID" 2>/dev/null; then
    wait "$PID" 2>/dev/null
    ALL_FOUND=1
    for re in ${EVIDENCE[@]+"${EVIDENCE[@]}"}; do
      matched_somewhere "$re" || { ALL_FOUND=0; break; }
    done
    if (( ALL_FOUND )); then VERDICT="PASS_EVIDENCE"; else VERDICT="FAIL_NO_EVIDENCE"; fi
    break
  fi
  sleep 1
done

ELAPSED=$(( $(date +%s) - START ))

# Post-run controller assertions.
FAILURES=()
if [[ "$VERDICT" == PASS_EVIDENCE* ]]; then
  for re in ${ABSENT[@]+"${ABSENT[@]}"}; do
    if matched_somewhere "$re"; then
      FAILURES+=("forbidden pattern observed: $re")
      VERDICT="FAIL_FORBIDDEN_PATTERN"
    fi
  done
fi
if [[ -n "$EXPECT_THREAD" ]]; then
  if ! grep -qE "\"type\":\"thread.started\",\"thread_id\":\"$EXPECT_THREAD\"" "$STREAM_LOG"; then
    FAILURES+=("thread.started did not carry expected thread id $EXPECT_THREAD")
    [[ "$VERDICT" == PASS_EVIDENCE ]] && VERDICT="FAIL_THREAD_MISMATCH"
  fi
fi

printf '{"probe":"%s","verdict":"%s","elapsed_seconds":%d,"deadline_seconds":%d}\n' \
  "$PROBE_NAME" "$VERDICT" "$ELAPSED" "$DEADLINE" | tee "$VERDICT_JSON"
if [[ "$VERDICT" == PASS_EVIDENCE && ${#FAILURES[@]} -eq 0 ]]; then
  echo "probe $PROBE_NAME PASSED on minimal evidence in ${ELAPSED}s"
  exit 0
fi
printf 'probe %s verdict=%s in %ss\n' "$PROBE_NAME" "$VERDICT" "$ELAPSED" >&2
for f in ${FAILURES[@]+"${FAILURES[@]}"}; do echo "  $f" >&2; done
exit 1
