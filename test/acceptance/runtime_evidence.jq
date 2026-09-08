# Checked-in jq predicates for the issue #16 runtime evidence contracts.
#
# Every predicate asserts STRUCTURED event fields on jq-parsed JSON/JSONL
# events, using the event shapes measured from the real codex-cli 0.153.x
# runtime during the PR #15 final acceptance run:
#
#   stream  (codex exec --json stdout):
#     {"type":"thread.started","thread_id":"<uuid>"}
#     {"type":"item.completed","item":{"type":"collab_tool_call",
#         "tool":"spawn_agent","receiver_thread_ids":["<child-uuid>"],...}}
#     {"type":"item.completed","item":{"type":"collab_tool_call","tool":"wait",
#         "receiver_thread_ids":["<child-uuid>"],
#         "agents_states":{"<child-uuid>":{"message":"<json-string>"}}}}
#     {"type":"item.completed","item":{"type":"agent_message","text":"..."}}
#     {"type":"item.completed","item":{"type":"error","message":"..."}}
#   rollout (CODEX_HOME/sessions/**/rollout-*.jsonl):
#     {"type":"session_meta","payload":{"id":"<thread-uuid>",...}}
#     {"type":"response_item","payload":{"type":"function_call","name":...,
#         "call_id":"call_...","arguments":"<json-string>",
#         "namespace":"mcp__zotero"        # native MCP calls only
#     }}
#     {"type":"response_item","payload":{"type":"function_call_output",
#         "call_id":"call_...","output": "<string>" | [{"text":...},...]}}
#
# Formal PASS semantics live ONLY in this file: callers may pass dynamic DATA
# (child/thread ids, the C2 fixture sentinel) but never a jq program. grep/ERE
# must never replace these predicates for JSON/JSONL event evidence.
#
# Contract constants (checked in, not caller-supplied):
def agent_name: "zotero-collection-cleaner";
def skill_token: "zotero-collection-cleaner/SKILL.md";
def native_tool: "get_collections";
def native_namespace: "mcp__zotero";
def shim_tool: "skill_mcp";
def exec_success_marker: "Process exited with code 0";

# --- shared helpers -------------------------------------------------------

# rollout response items
def items: [.[] | select(.type == "response_item") | .payload];

def parse_json($s):
  try ($s | fromjson) catch null;

# measured function_call_output payload shapes: a plain string (exec/spawn)
# or an array of {type:"input_text","text":...} objects (native MCP)
def output_texts($o):
  if ($o | type) == "array" then [$o[]? | (.text // "")] else [$o // ""] end;

def is_collab($ev; $tool):
  (($ev.type? // "") == "collab_tool_call") and (($ev.tool? // "") == $tool);

# true when a function_call_output with the same call_id exists whose output
# satisfies pred (call/response correlation, never two independent hits).
# pred must be a FILTER parameter (no $): a "$pred" value parameter would be
# evaluated eagerly at the call site against the wrong input.
def has_correlated_output($items; $call_id; pred):
  any($items[];
      (.type? == "function_call_output") and (.call_id? == $call_id)
      and pred);

# --- mode: derive-child-ids ----------------------------------------------
# Structured child ids from real spawn events only (receiver_thread_ids of
# item.completed spawn_agent events). Prompt/instruction JSON fragments can
# never produce a child id. item.started collab events carry empty
# receiver_thread_ids in the measured runtime, so they are ignored.
def derive_child_ids:
  [.[] | select(.type == "item.completed")
        | select(is_collab(.item; "spawn_agent"))
        | .item.receiver_thread_ids[]?] | unique
  | if length > 0 then .[] else false end;

# --- mode: derive-target-ids ----------------------------------------------
# Target-child identity confirmed from the PARENT ROLLOUT by structured
# correlation: a real spawn_agent function_call whose parsed arguments carry
# the exact producer-owned agent_type, correlated by call_id to a
# function_call_output whose parsed agent_id is the child id. A
# receiver_thread_ids entry without this correlation is a candidate, never a
# target — another child spawned in the same run must not be scoped in.
def target_child_ids:
  items as $it
  | [$it[]
     | select(.type? == "function_call" and .name? == "spawn_agent")
     | select((parse_json(.arguments? // "") | .agent_type? // "") == agent_name)
     | .call_id? // empty] as $target_calls
  | [$it[]
     | select(.type? == "function_call_output")
     | select(.call_id? as $cid | any($target_calls[]; . == $cid))
     | (parse_json(.output? // "") | .agent_id? // empty)]
  | map(select(type == "string" and length > 0)) | unique
  | if length > 0 then .[] else false end;

# --- mode: thread-ids -----------------------------------------------------
def thread_ids:
  [.[] | select(.type == "thread.started") | .thread_id? // empty]
  | if length > 0 then .[] else false end;

# --- contract c1: exact-name spawn + canonical skill read -----------------
# Parent-side proof: the rollout of the main thread (id from the stream's
# thread.started) contains a real spawn_agent function_call whose parsed
# arguments carry the exact producer-owned agent_type, correlated by call_id
# to a function_call_output whose parsed agent_id is the target child.
# Echoed agent names inside prompts/instructions never satisfy this.
def c1_spawn($child_id):
  items as $it
  | any($it[];
      (.type? == "function_call") and (.name? == "spawn_agent")
      and ((parse_json(.arguments? // "") | .agent_type? // "") == agent_name)
      and has_correlated_output($it; .call_id? // "";
            (parse_json(.output? // "") | .agent_id? // "") == $child_id));

# Child-side proof: inside the child's OWN rollout (scoped by session_meta
# payload id), a real exec_command function_call uses its structured `cmd`
# argument to run `cat` on the canonical skill path. Merely echoing or
# otherwise mentioning the path is not a read. The call must still be
# correlated by call_id to a successful execution output.
def c1_read:
  items as $it
  | any($it[];
      (.type? == "function_call")
      and (.name? == "exec_command")
      and (parse_json(.arguments? // "") as $args
           | ($args | type == "object")
           and (($args.cmd? // "") | type == "string")
           and (($args.cmd? // "")
                | test("(^|[;&|]{1,2})[[:space:]]*cat[[:space:]]+[^;&|]*" + skill_token)))
      and has_correlated_output($it; .call_id? // "";
            any(output_texts(.output)[]; contains(exec_success_marker))));

# --- contract c2: native Zotero MCP wiring --------------------------------
# A real native MCP function_call (exact tool name + native namespace) whose
# parsed arguments are a JSON object, correlated by call_id to a
# function_call_output containing the isolated fixture sentinel.
def c2_call($sentinel):
  items as $it
  | any($it[];
      (.type? == "function_call") and (.name? == native_tool)
      and (.namespace? == native_namespace)
      and ((parse_json(.arguments? // "") | type) == "object")
      and has_correlated_output($it; .call_id? // "";
            any(output_texts(.output)[]; contains($sentinel))));

# Structural negative gate: no real shim function_call event in the child
# rollout. The bare string "skill_mcp" inside instructions that forbid it is
# not a call and must not trip this gate.
def c2_no_shim:
  all(items[]; ((.type? == "function_call") and (.name? == shim_tool)) | not);

# --- contract c3 leg 1: needs_input envelope ------------------------------
# The stream's wait event must correlate to the target child both through
# receiver_thread_ids and the agents_states key, and the child's message —
# parsed as JSON with fromjson — must satisfy the interaction contract as
# OBJECT FIELDS: category root_selection, multiple true, a string question
# and a non-empty options array. Text hits for "needs_input" in prompts or
# prose are never evidence.
def needs_input_ok($msg):
  ($msg.control? == "needs_input")
  and ($msg.interaction.category? == "root_selection")
  and ($msg.interaction.multiple? == true)
  and (($msg.interaction.question? // null) | type == "string")
  and (($msg.interaction.options? // null) | type == "array")
  and (($msg.interaction.options? // []) | length > 0);

def c3_leg1($child_ids):
  any(.[] | select(.type == "item.completed");
      is_collab(.item; "wait")
      and (.item as $ev
          | any($child_ids[];
              . as $cid
              | (($ev.receiver_thread_ids? // []) | index($cid)) != null
              and (($ev.agents_states? // {}) | has($cid))
              and needs_input_ok(parse_json($ev.agents_states[$cid].message? // "")))));

# --- contract c3 leg 2: SAME-child resume ordering -------------------------
# PASS requires, in stream order: exactly one thread.started, its thread_id
# strictly equal to the expected (leg-1) child id, and a post-resume
# structured runtime event (agent message / tool call / reasoning) appearing
# AFTER it. A child-id string inside message text proves nothing; metadata
# error items between the two are tolerated (measured benign shape).
def resume_event_type($t):
  $t == "agent_message" or $t == "function_call"
  or $t == "reasoning" or $t == "collab_tool_call";

def c3_leg2($expected):
  . as $evs
  | ([$evs | to_entries[] | select(.value.type == "thread.started")]) as $ts
  | (($ts | length) == 1)
  and (($ts[0].value.thread_id? // "") == $expected)
  and any($evs | to_entries[];
      (.key > $ts[0].key)
      and (.value.type == "item.completed")
      and resume_event_type(.value.item.type? // ""));

# --- mode dispatch ---------------------------------------------------------
if $mode == "derive-child-ids" then derive_child_ids
elif $mode == "derive-target-ids" then target_child_ids
elif $mode == "thread-ids" then thread_ids
elif $mode == "c1-spawn" then c1_spawn($child_id)
elif $mode == "c1-read" then c1_read
elif $mode == "c2-call" then c2_call($sentinel)
elif $mode == "c2-no-shim" then c2_no_shim
elif $mode == "c3-leg1" then c3_leg1($child_ids_arr)
elif $mode == "c3-leg2" then c3_leg2($expected)
else error("runtime_evidence: unknown mode") end
