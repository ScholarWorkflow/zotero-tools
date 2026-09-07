"""Fixture-driven regression gates for the issue #16 structured evidence controller.

Every gate executes the real checked-in evidence controller
(``test/acceptance/runtime_evidence.sh`` + ``runtime_evidence.jq``) — the same
code path the live probe harness uses — against minimal fixtures frozen from
the measured codex-cli runtime shapes. No gate inspects shell source to decide
evidence; source gates exist only for CLI-surface and legacy-anchor checks.

Tri-state controller contract: exit 0 = MATCH, 1 = NO_MATCH, 2 = MALFORMED.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
ACC = ROOT / "test" / "acceptance"
CONTROLLER = ACC / "runtime_evidence.sh"
JQ_PROGRAM = ACC / "runtime_evidence.jq"
PROBE = ACC / "codex_probe.sh"
FIXTURES = ACC / "fixtures"
BASH = shutil.which("bash") or "/bin/bash"

MATCH = 0
NO_MATCH = 1
MALFORMED = 2

# Synthetic identity constants shared with the checked-in fixtures.
PARENT = "11111111-1111-4111-8111-111111111111"
CHILD_A = "22222222-2222-4222-8222-222222222222"
CHILD_B = "33333333-3333-4333-8333-333333333333"
WRONG_THREAD = "44444444-4444-4444-8444-444444444444"
SENTINEL = "SYNTH-FIXTURE-UNIV-2718"

STREAM_SPAWN = FIXTURES / "common" / "stream_spawn.jsonl"


# --- helpers ---------------------------------------------------------------


def run_controller(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [BASH, str(CONTROLLER), *args], capture_output=True, text=True, check=False
    )


def check_contract(
    contract: str,
    stream: Path,
    tmp: Path,
    *,
    scan_dirs: tuple[Path, ...] = (),
    expect_thread: str | None = None,
    sentinel: str | None = None,
) -> subprocess.CompletedProcess:
    args = [
        "check",
        "--contract",
        contract,
        "--stream",
        str(stream),
        "--start-marker",
        str(tmp / "marker"),
    ]
    for d in scan_dirs:
        args += ["--scan-dir", str(d)]
    if expect_thread is not None:
        args += ["--expect-thread", expect_thread]
    if sentinel is not None:
        args += ["--sentinel", sentinel]
    return run_controller(*args)


def evidence_case(
    tmp_path: Path, *, rollouts: tuple[Path, ...] = (), stale: tuple[Path, ...] = ()
) -> tuple[Path, Path]:
    """Build a scan dir with a fresh start marker.

    ``rollouts`` become scan-dir files newer than the marker; ``stale`` are
    copied and explicitly back-dated (never rely on checkout mtimes). Returns
    ``(marker, sessions_dir)``.
    """
    marker = tmp_path / "marker"
    marker.touch()
    sessions = tmp_path / "sessions"
    sessions.mkdir()
    old = time.time() - 3600
    for src in rollouts:
        # shutil.copy stamps the copy with the current time: strictly newer
        # than the marker created above, independent of checkout mtimes.
        shutil.copy(src, sessions / src.name)
    for src in stale:
        dst = sessions / src.name
        shutil.copy(src, dst)
        os.utime(dst, (old, old))
    return marker, sessions


def mutate_jsonl(src: Path, dst: Path, jq_filter: str) -> Path:
    result = subprocess.run(
        ["jq", "-c", jq_filter, str(src)], capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stderr
    dst.write_text(result.stdout, encoding="utf-8")
    return dst


def availability_regex() -> str:
    text = PROBE.read_text(encoding="utf-8")
    match = re.search(r"^AVAILABILITY_RE='([^']+)'$", text, flags=re.MULTILINE)
    assert match is not None, "probe must keep the AVAILABILITY_RE definition"
    return match.group(1)


def matches_ere(pattern: str, message: str) -> bool:
    result = subprocess.run(
        ["grep", "-Eq", pattern], input=message, text=True, check=False
    )
    return result.returncode == 0


# --- surface gates ----------------------------------------------------------


def test_controller_and_probe_shell_syntax() -> None:
    for script in (CONTROLLER, PROBE):
        result = subprocess.run(
            ["bash", "-n", str(script)], capture_output=True, text=True, check=False
        )
        assert result.returncode == 0, result.stderr


def test_probe_source_has_no_regex_evidence_surface() -> None:
    """Formal JSON/JSONL evidence must flow exclusively through the controller.

    The availability classifier (grep over provider error text) is the only
    allowed regex surface and is covered by its own dedicated gates.
    """
    text = PROBE.read_text(encoding="utf-8")

    assert "--evidence-regex" not in text, "caller-supplied evidence regex must stay removed"
    assert "--absent-regex" not in text, "absent-regex formal gate must stay removed"
    assert "runtime_evidence.sh" in text, "probe must delegate evidence to the controller"
    assert '--evidence-contract <c1|c2|c3-leg1|c3-leg2>' in text
    assert 'AVAILABILITY_RE=' in text


def test_legacy_issue14_harness_anchors_survive() -> None:
    """The issue #14 gates keep their anchors: resume vector + availability RE."""
    text = PROBE.read_text(encoding="utf-8")

    assert 'RESUME_ARGS=(resume "$RESUME_THREAD")' in text
    assert 'RESUME_ARGS=(exec resume "$RESUME_THREAD")' not in text

    pattern = availability_regex()
    assert matches_ere(pattern, "HTTP 402 Payment Required")
    assert not matches_ere(pattern, "Model metadata for openrouter/free not found; using fallback metadata")


# --- structured child-id derivation ----------------------------------------


def test_child_ids_derived_structurally_from_spawn_events(tmp_path: Path) -> None:
    stream = tmp_path / "stream.jsonl"
    shutil.copy(STREAM_SPAWN, stream)

    result = run_controller("derive-child-ids", "--stream", str(stream))
    assert result.returncode == MATCH, result.stderr
    assert result.stdout.split() == [CHILD_A]


def test_child_id_derivation_is_non_vacuous(tmp_path: Path) -> None:
    """Deleting receiver_thread_ids from the spawn event yields no child id."""
    stream = mutate_jsonl(
        STREAM_SPAWN,
        tmp_path / "stream.jsonl",
        'if .type == "item.completed" and .item.tool == "spawn_agent"'
        " then .item.receiver_thread_ids = [] else . end",
    )

    result = run_controller("derive-child-ids", "--stream", str(stream))
    assert result.returncode == NO_MATCH, result.stderr


# --- C1 ----------------------------------------------------------------------


def _c1_case(tmp_path: Path, child_rollout: Path) -> subprocess.CompletedProcess:
    marker, sessions = evidence_case(
        tmp_path,
        rollouts=(
            FIXTURES / "c1" / "parent_rollout.jsonl",
            child_rollout,
        ),
    )
    return check_contract("c1", tmp_path / "stream.jsonl", tmp_path, scan_dirs=(sessions,))


def test_c1_positive_structured_evidence(tmp_path: Path) -> None:
    shutil.copy(STREAM_SPAWN, tmp_path / "stream.jsonl")
    result = _c1_case(tmp_path, FIXTURES / "c1" / "child_rollout_ok.jsonl")
    assert result.returncode == MATCH, result.stderr


def test_c1_instruction_echo_never_passes(tmp_path: Path) -> None:
    """T1: the child rollout echoes the skill path in messages but has no read
    function_call event — the measured vacuous-pass shape this issue removes."""
    shutil.copy(STREAM_SPAWN, tmp_path / "stream.jsonl")
    result = _c1_case(tmp_path, FIXTURES / "c1" / "child_rollout_echo_only.jsonl")
    assert result.returncode == NO_MATCH, result.stderr


def test_c1_wrong_child_rollout_never_passes(tmp_path: Path) -> None:
    """T3: a rollout belonging to another child holds a perfect read event."""
    shutil.copy(STREAM_SPAWN, tmp_path / "stream.jsonl")
    result = _c1_case(tmp_path, FIXTURES / "c1" / "child_rollout_wrong_child.jsonl")
    assert result.returncode == NO_MATCH, result.stderr


def test_c1_stale_rollout_excluded_until_freshened(tmp_path: Path) -> None:
    """T4: marker-before rollouts never satisfy the contract; mtime is the
    discriminator (explicitly controlled, never fixture checkout mtime)."""
    shutil.copy(STREAM_SPAWN, tmp_path / "stream.jsonl")
    marker, sessions = evidence_case(
        tmp_path,
        rollouts=(FIXTURES / "c1" / "parent_rollout.jsonl",),
        stale=(FIXTURES / "c1" / "child_rollout_ok.jsonl",),
    )
    result = check_contract("c1", tmp_path / "stream.jsonl", tmp_path, scan_dirs=(sessions,))
    assert result.returncode == NO_MATCH, result.stderr

    fresh = time.time()
    os.utime(sessions / "child_rollout_ok.jsonl", (fresh, fresh))
    result = check_contract("c1", tmp_path / "stream.jsonl", tmp_path, scan_dirs=(sessions,))
    assert result.returncode == MATCH, result.stderr


def test_c1_spawn_without_child_id_never_passes(tmp_path: Path) -> None:
    """Anti-vacuous: a spawn event missing receiver_thread_ids yields neither a
    child id nor scoped rollouts, so a perfectly equipped rollout cannot pass."""
    mutate_jsonl(
        STREAM_SPAWN,
        tmp_path / "stream.jsonl",
        'if .type == "item.completed" and .item.tool == "spawn_agent"'
        " then .item.receiver_thread_ids = [] else . end",
    )
    result = _c1_case(tmp_path, FIXTURES / "c1" / "child_rollout_ok.jsonl")
    assert result.returncode == NO_MATCH, result.stderr


def test_c1_spawn_output_without_child_id_never_passes(tmp_path: Path) -> None:
    """Anti-vacuous: dropping the correlated spawn output (the agent_id
    carrier) must fail C1 even though the stream spawn event exists."""
    shutil.copy(STREAM_SPAWN, tmp_path / "stream.jsonl")
    marker, sessions = evidence_case(
        tmp_path,
        rollouts=(FIXTURES / "c1" / "child_rollout_ok.jsonl",),
    )
    mutate_jsonl(
        FIXTURES / "c1" / "parent_rollout.jsonl",
        sessions / "parent_rollout.jsonl",
        'select(.type != "response_item"'
        ' or .payload.type != "function_call_output"'
        ' or .payload.call_id != "call_0good00000000000000000")',
    )
    result = check_contract("c1", tmp_path / "stream.jsonl", tmp_path, scan_dirs=(sessions,))
    assert result.returncode == NO_MATCH, result.stderr


# --- C2 ----------------------------------------------------------------------


def _c2_case(tmp_path: Path, rollout: Path, *, sentinel: str = SENTINEL):
    shutil.copy(STREAM_SPAWN, tmp_path / "stream.jsonl")
    marker, sessions = evidence_case(tmp_path, rollouts=(rollout,))
    return check_contract(
        "c2", tmp_path / "stream.jsonl", tmp_path, scan_dirs=(sessions,), sentinel=sentinel
    )


def test_c2_positive_structured_evidence(tmp_path: Path) -> None:
    """T2/anti-vacuous 8: the positive fixture also embeds forbidding
    skill_mcp instruction text, proving the negative gate ignores it."""
    result = _c2_case(tmp_path, FIXTURES / "c2" / "child_rollout_ok.jsonl")
    assert result.returncode == MATCH, result.stderr


def test_c2_call_without_response_never_passes(tmp_path: Path) -> None:
    result = _c2_case(tmp_path, FIXTURES / "c2" / "child_rollout_call_only.jsonl")
    assert result.returncode == NO_MATCH, result.stderr


def test_c2_response_call_id_mismatch_never_passes(tmp_path: Path) -> None:
    result = _c2_case(tmp_path, FIXTURES / "c2" / "child_rollout_output_mismatch.jsonl")
    assert result.returncode == NO_MATCH, result.stderr


def test_c2_schema_echo_only_never_passes(tmp_path: Path) -> None:
    result = _c2_case(tmp_path, FIXTURES / "c2" / "child_rollout_schema_echo_only.jsonl")
    assert result.returncode == NO_MATCH, result.stderr


def test_c2_real_shim_call_trips_negative_gate(tmp_path: Path) -> None:
    result = _c2_case(tmp_path, FIXTURES / "c2" / "child_rollout_shim_call.jsonl")
    assert result.returncode == NO_MATCH, result.stderr


def test_c2_non_native_call_never_passes(tmp_path: Path) -> None:
    """A get_collections call without the native mcp__zotero namespace."""
    result = _c2_case(tmp_path, FIXTURES / "c2" / "child_rollout_nonnative.jsonl")
    assert result.returncode == NO_MATCH, result.stderr


def test_c2_wrong_sentinel_never_passes(tmp_path: Path) -> None:
    result = _c2_case(
        tmp_path, FIXTURES / "c2" / "child_rollout_ok.jsonl", sentinel="WRONG-SENTINEL"
    )
    assert result.returncode == NO_MATCH, result.stderr


# --- C3 leg 1 ----------------------------------------------------------------


def _leg1_case(name: str, tmp_path: Path):
    stream = FIXTURES / "c3_leg1" / f"stream_wait_{name}.jsonl"
    return check_contract("c3-leg1", stream, tmp_path)


def test_c3_leg1_positive_structured_evidence(tmp_path: Path) -> None:
    result = _leg1_case("ok", tmp_path)
    assert result.returncode == MATCH, result.stderr


def test_c3_leg1_multiple_false_never_passes(tmp_path: Path) -> None:
    result = _leg1_case("multiple_false", tmp_path)
    assert result.returncode == NO_MATCH, result.stderr


def test_c3_leg1_wrong_category_never_passes(tmp_path: Path) -> None:
    result = _leg1_case("wrong_category", tmp_path)
    assert result.returncode == NO_MATCH, result.stderr


def test_c3_leg1_other_child_wait_never_passes(tmp_path: Path) -> None:
    """The wait event references a child this run never spawned."""
    result = _leg1_case("wrong_child", tmp_path)
    assert result.returncode == NO_MATCH, result.stderr


def test_c3_leg1_prose_message_never_passes(tmp_path: Path) -> None:
    result = _leg1_case("prose_message", tmp_path)
    assert result.returncode == NO_MATCH, result.stderr


def test_c3_leg1_instruction_echo_never_passes(tmp_path: Path) -> None:
    """T1: a complete needs_input envelope embedded in the spawn prompt text —
    with no wait event — must not pass."""
    result = _leg1_case("echo_only", tmp_path)
    assert result.returncode == NO_MATCH, result.stderr


# --- C3 leg 2 ----------------------------------------------------------------


def _leg2_case(name: str, tmp_path: Path, *, expect_thread: str = CHILD_A):
    stream = FIXTURES / "c3_leg2" / f"stream_resume_{name}.jsonl"
    return check_contract(
        "c3-leg2", stream, tmp_path, expect_thread=expect_thread
    )


def test_c3_leg2_positive_same_thread_ordering(tmp_path: Path) -> None:
    """T6: thread.started == X followed by the first post-resume event
    (tolerating the measured benign metadata error item) completes evidence."""
    result = _leg2_case("ok", tmp_path)
    assert result.returncode == MATCH, result.stderr


def test_c3_leg2_wrong_thread_never_passes(tmp_path: Path) -> None:
    """T5: thread.started carries Y, everything else perfect."""
    result = _leg2_case("wrong_thread", tmp_path)
    assert result.returncode == NO_MATCH, result.stderr


def test_c3_leg2_thread_id_only_in_text_never_passes(tmp_path: Path) -> None:
    """Anti-vacuous: the expected id appears in message text while the real
    thread.started is another thread."""
    result = _leg2_case("id_in_text_only", tmp_path)
    assert result.returncode == NO_MATCH, result.stderr


def test_c3_leg2_without_post_resume_event_never_passes(tmp_path: Path) -> None:
    result = _leg2_case("no_post_event", tmp_path)
    assert result.returncode == NO_MATCH, result.stderr


def test_c3_leg2_event_before_thread_started_never_passes(tmp_path: Path) -> None:
    result = _leg2_case("event_before_started", tmp_path)
    assert result.returncode == NO_MATCH, result.stderr


def test_c3_leg2_thread_ids_mode_reports_mismatch(tmp_path: Path) -> None:
    """The probe's FAIL_THREAD_MISMATCH gate consumes this structured output."""
    stream = FIXTURES / "c3_leg2" / "stream_resume_wrong_thread.jsonl"
    result = run_controller("thread-ids", "--stream", str(stream))
    assert result.returncode == MATCH, result.stderr
    assert result.stdout.split() == [WRONG_THREAD]


# --- malformed JSON -----------------------------------------------------------


def test_malformed_stream_record_is_malformed_even_with_keyword(tmp_path: Path) -> None:
    """T7: a newline-terminated invalid record containing the evidence keyword
    must return MALFORMED, never degrade to text scanning."""
    shutil.copy(STREAM_SPAWN, tmp_path / "stream.jsonl")
    marker, sessions = evidence_case(tmp_path, rollouts=(FIXTURES / "c2" / "child_rollout_ok.jsonl",))
    with open(tmp_path / "stream.jsonl", "a", encoding="utf-8") as f:
        f.write('{"type":"item.completed" broken get_collections ' + SENTINEL + "\n")

    result = check_contract(
        "c2", tmp_path / "stream.jsonl", tmp_path, scan_dirs=(sessions,), sentinel=SENTINEL
    )
    assert result.returncode == MALFORMED, result.stderr


def test_malformed_record_in_scoped_rollout_is_malformed(tmp_path: Path) -> None:
    shutil.copy(STREAM_SPAWN, tmp_path / "stream.jsonl")
    marker, sessions = evidence_case(tmp_path, rollouts=(FIXTURES / "c2" / "child_rollout_ok.jsonl",))
    with open(sessions / "child_rollout_ok.jsonl", "a", encoding="utf-8") as f:
        f.write('{"payload":{"broken": true}\n')

    result = check_contract(
        "c2", tmp_path / "stream.jsonl", tmp_path, scan_dirs=(sessions,), sentinel=SENTINEL
    )
    assert result.returncode == MALFORMED, result.stderr


def test_unfinished_trailing_record_is_pending_not_malformed(tmp_path: Path) -> None:
    """T7 framing rule: a live writer's unterminated trailing record is
    pending, so evidence already present still MATCHes this round; a
    newline-terminated broken line would be MALFORMED."""
    shutil.copy(STREAM_SPAWN, tmp_path / "stream.jsonl")
    marker, sessions = evidence_case(tmp_path, rollouts=(FIXTURES / "c2" / "child_rollout_ok.jsonl",))
    with open(tmp_path / "stream.jsonl", "a", encoding="utf-8") as f:
        f.write('{"type":"item.compl')  # no newline: writer mid-record

    result = check_contract(
        "c2", tmp_path / "stream.jsonl", tmp_path, scan_dirs=(sessions,), sentinel=SENTINEL
    )
    assert result.returncode == MATCH, result.stderr


def test_controller_is_idempotent(tmp_path: Path) -> None:
    """Re-evaluating the same immutable logs must return the identical result."""
    shutil.copy(STREAM_SPAWN, tmp_path / "stream.jsonl")
    first = _leg1_case("ok", tmp_path)
    second = _leg1_case("ok", tmp_path)
    assert first.returncode == second.returncode == MATCH


# --- availability text classification (diagnostic surface) ---------------------


@pytest.mark.parametrize(
    "fixture_name,expected",
    [
        ("http_402.txt", True),
        ("http_403.txt", True),
        ("http_404_unavailable.txt", True),
        ("rate_limit.txt", True),
        ("region_block.txt", True),
        ("quota.txt", True),
        ("benign_metadata.txt", False),
        ("plain_404.txt", False),
    ],
)
def test_availability_classification_kept(tmp_path: Path, fixture_name: str, expected: bool) -> None:
    """T8: stderr/provider-text classification is unchanged; benign fallbacks
    and bare 404s must not classify as availability failures."""
    message = (FIXTURES / "common" / "availability" / fixture_name).read_text(encoding="utf-8")
    assert matches_ere(availability_regex(), message) is expected


# --- live-harness behaviour (stubbed runtime, real probe + controller) --------

STUB_DIRENV = """\
#!/usr/bin/env bash
# Test stub: simulates the codex runtime without launching a model.
sleep 1
[[ -n "$STUB_TOUCH" ]] && touch "$STUB_TOUCH"
[[ -n "$STUB_STREAM" && -n "$STUB_LINES" ]] && cat "$STUB_LINES" >> "$STUB_STREAM"
[[ -n "$STUB_STDERR" && -n "$STUB_MSG" ]] && printf '%s\\n' "$STUB_MSG" >> "$STUB_STDERR"
[[ -n "$STUB_EXIT" ]] && exit "$STUB_EXIT"
sleep 30
"""


class ProbeRun:
    def __init__(self, tmp_path: Path) -> None:
        self.tmp = tmp_path
        self.bin = tmp_path / "bin"
        self.bin.mkdir()
        stub = self.bin / "direnv"
        stub.write_text(STUB_DIRENV, encoding="utf-8")
        stub.chmod(0o755)
        for d in ("logs", "sessions", "repo", "consumer", "codexhome"):
            (tmp_path / d).mkdir()
        (tmp_path / "prompt.txt").write_text("probe prompt\n", encoding="utf-8")

    def run(
        self,
        name: str,
        contract: str,
        *,
        deadline: int = 20,
        touch: Path | None = None,
        stream_lines: Path | None = None,
        stderr_msg: str | None = None,
        exit_after: str | None = None,
        extra: tuple[str, ...] = (),
        strip_jq: bool = False,
    ) -> tuple[int, dict | None]:
        env = dict(os.environ)
        if strip_jq:
            nojq = self.tmp / "bin-nojq"
            nojq.mkdir(exist_ok=True)
            for tool in ("bash", "dirname", "mkdir", "cp", "touch", "date", "tee", "grep", "direnv"):
                resolved = shutil.which(tool)
                if resolved:
                    link = nojq / tool
                    if not link.exists():
                        link.symlink_to(resolved)
            env["PATH"] = str(nojq)
        else:
            env["PATH"] = f"{self.bin}{os.pathsep}{os.environ['PATH']}"
        if touch:
            env["STUB_TOUCH"] = str(touch)
        if stream_lines:
            env["STUB_STREAM"] = str(self.tmp / "logs" / f"{name}.stream.jsonl")
            env["STUB_LINES"] = str(stream_lines)
        if stderr_msg:
            env["STUB_STDERR"] = str(self.tmp / "logs" / f"{name}.stderr.log")
            env["STUB_MSG"] = stderr_msg
        if exit_after is not None:
            env["STUB_EXIT"] = exit_after
        result = subprocess.run(
            [
                BASH,
                str(PROBE),
                "--name",
                name,
                "--prompt-file",
                str(self.tmp / "prompt.txt"),
                "--log-dir",
                str(self.tmp / "logs"),
                "--repo-root",
                str(self.tmp / "repo"),
                "--consumer-dir",
                str(self.tmp / "consumer"),
                "--codex-home",
                str(self.tmp / "codexhome"),
                "--evidence-contract",
                contract,
                "--deadline-seconds",
                str(deadline),
                *extra,
            ],
            capture_output=True,
            text=True,
            env=env,
            timeout=deadline + 40,
            check=False,
        )
        verdict_path = self.tmp / "logs" / f"{name}.verdict.json"
        import json

        verdict = json.loads(verdict_path.read_text(encoding="utf-8")) if verdict_path.exists() else None
        return result.returncode, verdict


def _probe_c2_setup(tmp: Path) -> None:
    shutil.copy(FIXTURES / "c2" / "child_rollout_ok.jsonl", tmp / "sessions" / "child.jsonl")
    shutil.copy(STREAM_SPAWN, tmp / "lines.jsonl")


def test_probe_passes_and_hard_stops_on_structured_evidence(tmp_path: Path) -> None:
    """Rules 1+2+3 on the real poll loop: the sleeping stub runtime is killed
    the moment the contract MATCHes, far before its own sleep ends."""
    run = ProbeRun(tmp_path)
    _probe_c2_setup(tmp_path)
    rc, verdict = run.run(
        "c2",
        "c2",
        deadline=60,
        touch=tmp_path / "sessions" / "child.jsonl",
        stream_lines=tmp_path / "lines.jsonl",
        extra=("--scan-dir", str(tmp_path / "sessions"), "--sentinel", SENTINEL),
    )
    assert rc == 0, verdict
    assert verdict is not None and verdict["verdict"] == "PASS_EVIDENCE"
    assert verdict["elapsed_seconds"] < 25, "hard stop must beat the stub's 30s sleep"


def test_probe_fail_no_evidence_on_clean_exit(tmp_path: Path) -> None:
    run = ProbeRun(tmp_path)
    rc, verdict = run.run("n1", "c1", exit_after="0")
    assert rc == 1
    assert verdict is not None and verdict["verdict"] == "FAIL_NO_EVIDENCE"


def test_probe_fail_malformed_evidence(tmp_path: Path) -> None:
    bad = tmp_path / "bad.jsonl"
    bad.write_text('{"broken json line\n', encoding="utf-8")
    run = ProbeRun(tmp_path)
    rc, verdict = run.run("m", "c1", stream_lines=bad, exit_after="0")
    assert rc == 1
    assert verdict is not None and verdict["verdict"] == "FAIL_MALFORMED_EVIDENCE"


def test_probe_harness_model_availability(tmp_path: Path) -> None:
    run = ProbeRun(tmp_path)
    rc, verdict = run.run("a", "c1", stderr_msg="error: HTTP 402 Payment Required", exit_after="0")
    assert rc == 1
    assert verdict is not None and verdict["verdict"] == "HARNESS_MODEL_AVAILABILITY"


def test_probe_fail_thread_mismatch(tmp_path: Path) -> None:
    wrong = tmp_path / "wrong.jsonl"
    shutil.copy(
        FIXTURES / "c3_leg2" / "stream_resume_wrong_thread.jsonl", wrong
    )
    run = ProbeRun(tmp_path)
    rc, verdict = run.run(
        "t",
        "c3-leg2",
        stream_lines=wrong,
        exit_after="0",
        extra=("--expect-thread", CHILD_A),
    )
    assert rc == 1
    assert verdict is not None and verdict["verdict"] == "FAIL_THREAD_MISMATCH"


def test_probe_harness_deadline(tmp_path: Path) -> None:
    run = ProbeRun(tmp_path)
    rc, verdict = run.run("d", "c1", deadline=3)
    assert rc == 1
    assert verdict is not None and verdict["verdict"] == "HARNESS_DEADLINE"
    assert verdict["elapsed_seconds"] <= 6


def test_probe_harness_prerequisite_without_jq(tmp_path: Path) -> None:
    """Missing jq fails fast before any model work and never falls back."""
    run = ProbeRun(tmp_path)
    rc, verdict = run.run("p", "c1", strip_jq=True)
    assert rc == 1
    assert verdict is not None and verdict["verdict"] == "HARNESS_PREREQUISITE"


def test_probe_rejects_removed_regex_flags() -> None:
    result = subprocess.run(
        ["bash", str(PROBE), "--name", "x", "--evidence-regex", "foo"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 2
    assert "unknown argument" in result.stderr
