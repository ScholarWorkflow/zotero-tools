#!/usr/bin/env bash
# Structured runtime-evidence controller for the Codex acceptance probes
# (issue #16). All JSON/JSONL event evidence is parsed and asserted with jq
# (checked-in predicates in runtime_evidence.jq); grep/ERE never decides
# formal event evidence.
#
# Tri-state contract result via exit code:
#   0  MATCH      the named contract's evidence is complete
#   1  NO_MATCH   JSON is valid, evidence not (yet) complete
#   2  MALFORMED  a newline-terminated record that must participate in the
#                 judgment is not valid JSON — never falls back to text scan
#   3  usage error
#   4  prerequisite missing (jq)
#
# Modes:
#   derive-child-ids --stream F
#       print child thread ids derived structurally from real spawn events
#   thread-ids --stream F
#       print every thread.started thread id, in stream order
#   check --contract c1|c2|c3-leg1|c3-leg2 --stream F --start-marker M
#         [--scan-dir D]... [--expect-thread ID] [--sentinel TEXT]
#       evaluate a named, checked-in evidence contract
#
# An unfinished trailing record of a live-writer file (no terminating
# newline) is pending framing, not malformed: it is excluded from the parse
# this round and re-read on the next poll. A newline-terminated invalid line
# is MALFORMED, always.
set -uo pipefail

DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
JQ_PROGRAM="$DIR/runtime_evidence.jq"

CONTRACT="" STREAM="" MARKER="" EXPECT_THREAD="" SENTINEL=""
SCAN_DIRS=()
TMP_LINES=$(mktemp "${TMPDIR:-/tmp}/revidence.XXXXXX") || exit 4
trap 'rm -f "$TMP_LINES"' EXIT

usage() {
  echo "usage: runtime_evidence.sh derive-child-ids --stream F" >&2
  echo "       runtime_evidence.sh thread-ids --stream F" >&2
  echo "       runtime_evidence.sh check --contract NAME --stream F --start-marker M" >&2
  echo "         [--scan-dir D]... [--expect-thread ID] [--sentinel TEXT]" >&2
  exit 3
}

prereq_fail() {
  echo "HARNESS_PREREQUISITE: jq is required by the evidence controller" >&2
  exit 4
}
command -v jq >/dev/null 2>&1 || prereq_fail
[[ -f "$JQ_PROGRAM" ]] || { echo "missing $JQ_PROGRAM" >&2; exit 3; }

# newline-terminated records only; a live writer's unfinished trailing record
# is pending framing (see file header), never silently parsed as JSON
complete_lines() {
  local src=$1 n
  n=$(wc -l <"$src" 2>/dev/null) || n=0
  n=${n//[!0-9]/}
  if (( n > 0 )); then head -n "$n" "$src" >"$TMP_LINES"; else : >"$TMP_LINES"; fi
}

# run a jq mode over one file's complete records; prints jq stdout
# return codes: 0 ok, 1 no-match (jq -e false), 2 malformed, 5+ jq error
run_mode() {
  local mode=$1 file=$2; shift 2
  complete_lines "$file" || return 2
  jq --slurp -e -r -f "$JQ_PROGRAM" \
    --arg mode "$mode" \
    --arg child_id "${ARG_CHILD_ID:-}" \
    --arg expected "${ARG_EXPECTED:-}" \
    --arg sentinel "${ARG_SENTINEL:-}" \
    --argjson child_ids_arr "${ARG_CHILD_IDS_ARR:-[]}" \
    "$@" "$TMP_LINES"
}

# validate every newline-terminated record of a file; MALFORMED on failure
validate_file() {
  local file=$1
  [[ -f "$file" ]] || return 0
  complete_lines "$file" || return 2
  jq --slurp -e . "$TMP_LINES" >/dev/null 2>&1
  local rc=$?
  if (( rc == 0 )); then return 0; fi
  echo "MALFORMED: not valid JSON in $file" >&2
  return 2
}

# structured rollout identity: session_meta payload id (never filename tokens)
meta_id() {
  local file=$1
  complete_lines "$file" || return 0
  jq -r 'select(.type == "session_meta") | .payload.id // empty' "$TMP_LINES" 2>/dev/null | head -n 1
}

contains_id() {
  local id=$1; shift
  local candidate
  for candidate in "$@"; do [[ "$candidate" == "$id" ]] && return 0; done
  return 1
}

mode=${1:-}
[[ $# -gt 0 ]] && shift
case "$mode" in
  derive-child-ids|thread-ids)
    while [[ $# -gt 0 ]]; do
      case "$1" in
        --stream) STREAM=$2; shift 2 ;;
        *) usage ;;
      esac
    done
    [[ -n "$STREAM" ]] || usage
    run_mode "$mode" "$STREAM"
    rc=$?
    if (( rc == 0 )); then exit 0; fi
    if (( rc == 1 )); then exit 1; fi
    echo "MALFORMED: not valid JSON in $STREAM" >&2
    exit 2
    ;;
  check)
    while [[ $# -gt 0 ]]; do
      case "$1" in
        --contract) CONTRACT=$2; shift 2 ;;
        --stream) STREAM=$2; shift 2 ;;
        --start-marker) MARKER=$2; shift 2 ;;
        --scan-dir) SCAN_DIRS+=("$2"); shift 2 ;;
        --expect-thread) EXPECT_THREAD=$2; shift 2 ;;
        --sentinel) SENTINEL=$2; shift 2 ;;
        *) usage ;;
      esac
    done
    [[ -n "$CONTRACT" && -n "$STREAM" && -n "$MARKER" ]] || usage
    case "$CONTRACT" in c1|c2|c3-leg1|c3-leg2) ;; *) usage ;; esac
    if [[ "$CONTRACT" == "c2" && -z "$SENTINEL" ]]; then
      echo "contract c2 requires --sentinel (isolated fixture data)" >&2
      exit 3
    fi

    if ! validate_file "$STREAM"; then exit 2; fi

    # structured child ids for this run: real spawn events only
    ARG_CHILD_IDS_RAW=$(run_mode derive-child-ids "$STREAM")
    rc=$?
    if (( rc != 0 && rc != 1 )); then exit 2; fi
    CHILD_IDS=(${ARG_CHILD_IDS_RAW//$'\n'/ })

    ARG_EXPECTED="$EXPECT_THREAD"
    ARG_SENTINEL="$SENTINEL"
    ARG_CHILD_ID=""
    ARG_CHILD_IDS_ARR="[$(printf '"%s",' "${CHILD_IDS[@]+"${CHILD_IDS[@]}"}" | sed 's/,$//')]"

    # contracts c1/c2 consume scoped rollout transcripts; c3 legs are
    # stream-only in the measured runtime
    PARENT_ID=""
    if [[ "$CONTRACT" == "c1" ]]; then
      complete_lines "$STREAM"
      PARENT_ID=$(jq -r 'select(.type == "thread.started") | .thread_id // empty' \
        "$TMP_LINES" 2>/dev/null | head -n 1)
    fi

    PARENT_FILES=() CHILD_FILES=()
    scan_rollouts() {
      local dir f id
      for dir in ${SCAN_DIRS[@]+"${SCAN_DIRS[@]}"}; do
        [[ -d "$dir" ]] || continue
        while IFS= read -r -d '' f; do
          validate_file "$f" || { exit 2; }
          id=$(meta_id "$f")
          [[ -n "$id" ]] || continue
          if [[ -n "$PARENT_ID" && "$id" == "$PARENT_ID" ]]; then
            PARENT_FILES+=("$f")
          elif contains_id "$id" "${CHILD_IDS[@]+"${CHILD_IDS[@]}"}"; then
            CHILD_FILES+=("$f")
          fi
          # files with other structured identities never participate
        done < <(find "$dir" -name '*.jsonl' -newer "$MARKER" -type f -print0 2>/dev/null)
      done
    }

    RESULT=1
    case "$CONTRACT" in
      c1)
        scan_rollouts
        for cid in ${CHILD_IDS[@]+"${CHILD_IDS[@]}"}; do
          pf_ok=0
          for pf in ${PARENT_FILES[@]+"${PARENT_FILES[@]}"}; do
            ARG_CHILD_ID="$cid"
            if run_mode c1-spawn "$pf" >/dev/null 2>&1; then pf_ok=1; break; fi
          done
          cf_ok=0
          for cf in ${CHILD_FILES[@]+"${CHILD_FILES[@]}"}; do
            id=$(meta_id "$cf")
            [[ "$id" == "$cid" ]] || continue
            if run_mode c1-read "$cf" >/dev/null 2>&1; then cf_ok=1; break; fi
          done
          if (( pf_ok && cf_ok )); then RESULT=0; break; fi
        done
        ;;
      c2)
        scan_rollouts
        call_ok=0 shim_ok=1
        for cf in ${CHILD_FILES[@]+"${CHILD_FILES[@]}"}; do
          if run_mode c2-call "$cf" >/dev/null 2>&1; then call_ok=1; fi
          if ! run_mode c2-no-shim "$cf" >/dev/null 2>&1; then shim_ok=0; fi
        done
        if (( call_ok && shim_ok )); then RESULT=0; fi
        ;;
      c3-leg1)
        if run_mode c3-leg1 "$STREAM" >/dev/null 2>&1; then RESULT=0; fi
        ;;
      c3-leg2)
        [[ -n "$EXPECT_THREAD" ]] || { echo "c3-leg2 requires --expect-thread" >&2; exit 3; }
        if run_mode c3-leg2 "$STREAM" >/dev/null 2>&1; then RESULT=0; fi
        ;;
    esac

    case "$RESULT" in
      0) echo "evidence: contract=$CONTRACT result=MATCH" >&2; exit 0 ;;
      *) echo "evidence: contract=$CONTRACT result=NO_MATCH" >&2; exit 1 ;;
    esac
    ;;
  *)
    usage
    ;;
esac
