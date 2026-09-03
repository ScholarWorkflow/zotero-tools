#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
WORK_DIR="${RUNNER_TEMP:-/tmp}/zotero-mcp-ci"
DOWNLOAD_DIR="${RUNNER_TEMP:-/tmp}/zotero-ci-downloads"
HOME_DIR="$WORK_DIR/home"
PROFILE_DIR="$WORK_DIR/profile"
DATA_DIR="$WORK_DIR/data"
OUTPUT_DIR="$WORK_DIR/exported"
ZOTERO_ARCHIVE="$DOWNLOAD_DIR/Zotero-${ZOTERO_VERSION}_linux-x86_64.tar.xz"
MCP_XPI="$DOWNLOAD_DIR/zotero-mcp-plugin-${MCP_VERSION}.xpi"
ZOTERO_URL="https://download.zotero.org/client/release/${ZOTERO_VERSION}/Zotero-${ZOTERO_VERSION}_linux-x86_64.tar.xz"
MCP_URL="https://github.com/cookjohn/zotero-mcp/releases/download/v${MCP_VERSION}/zotero-mcp-plugin-${MCP_VERSION}.xpi"
SENTINEL="CI_SENTINEL_ABSTRACT_DO_NOT_PRINT_7f43a1"
ZOTERO_PID=""

mkdir -p "$DOWNLOAD_DIR"
rm -rf "$WORK_DIR"
mkdir -p "$HOME_DIR" "$PROFILE_DIR/extensions" "$DATA_DIR" "$OUTPUT_DIR"

redact_logs() {
  for log in "$WORK_DIR/zotero.stdout.log" "$WORK_DIR/zotero.stderr.log" "$WORK_DIR/probe.log"; do
    if [[ -f "$log" ]]; then
      sed -i "s/${SENTINEL}/[REDACTED_ABSTRACT]/g" "$log" || true
    fi
  done
}

cleanup() {
  local status=$?
  if [[ -n "$ZOTERO_PID" ]] && kill -0 "$ZOTERO_PID" 2>/dev/null; then
    kill "$ZOTERO_PID" 2>/dev/null || true
    for _ in {1..10}; do
      kill -0 "$ZOTERO_PID" 2>/dev/null || break
      sleep 1
    done
    kill -9 "$ZOTERO_PID" 2>/dev/null || true
  fi
  redact_logs
  exit "$status"
}
trap cleanup EXIT INT TERM

fetch_checked() {
  local url=$1
  local path=$2
  local algorithm=$3
  local digest=$4
  local checker
  if [[ "$algorithm" == "sha512" ]]; then
    checker=sha512sum
  else
    checker=sha256sum
  fi

  if [[ -f "$path" ]] && printf '%s  %s\n' "$digest" "$path" | "$checker" -c - >/dev/null 2>&1; then
    echo "Using cached $(basename "$path")"
    return
  fi
  rm -f "$path"
  curl --fail --location --retry 3 --retry-delay 2 --silent --show-error "$url" --output "$path"
  printf '%s  %s\n' "$digest" "$path" | "$checker" -c -
}

fetch_checked "$ZOTERO_URL" "$ZOTERO_ARCHIVE" sha512 "$ZOTERO_SHA512"
fetch_checked "$MCP_URL" "$MCP_XPI" sha256 "$MCP_SHA256"

tar -xJf "$ZOTERO_ARCHIVE" -C "$WORK_DIR"
ZOTERO_DIR="$WORK_DIR/Zotero_linux-x86_64"
if [[ ! -x "$ZOTERO_DIR/zotero" ]]; then
  echo "Pinned Zotero archive did not contain the expected launcher" >&2
  exit 1
fi

cp "$MCP_XPI" "$PROFILE_DIR/extensions/zotero-mcp-plugin@autoagent.my.xpi"
cat >"$PROFILE_DIR/prefs.js" <<EOF
user_pref("extensions.autoDisableScopes", 0);
user_pref("extensions.enabledScopes", 15);
user_pref("extensions.zotero.useDataDir", true);
user_pref("extensions.zotero.dataDir", "${DATA_DIR}");
user_pref("extensions.zotero.warnOnUnsafeDataDir", false);
user_pref("extensions.zotero.zotero-mcp-plugin.mcp.server.enabled", true);
user_pref("extensions.zotero.zotero-mcp-plugin.mcp.server.port", 23120);
user_pref("extensions.zotero.zotero-mcp-plugin.write.enabled", true);
EOF

export HOME="$HOME_DIR"
export MOZ_HEADLESS=1
cd "$ROOT_DIR"

xvfb-run --auto-servernum --server-args="-screen 0 1280x1024x24" \
  "$ZOTERO_DIR/zotero" -profile "$PROFILE_DIR" -no-remote \
  >"$WORK_DIR/zotero.stdout.log" 2>"$WORK_DIR/zotero.stderr.log" &
ZOTERO_PID=$!

echo "Waiting for Zotero MCP endpoint on 127.0.0.1:23120" | tee "$WORK_DIR/probe.log"
ready=0
for attempt in {1..60}; do
  if ! kill -0 "$ZOTERO_PID" 2>/dev/null; then
    echo "Zotero exited before MCP became ready (attempt $attempt)" | tee -a "$WORK_DIR/probe.log"
    break
  fi
  http_code=$(curl --silent --output /dev/null --write-out '%{http_code}' --max-time 2 \
    -X POST http://127.0.0.1:23120/mcp \
    -H 'Content-Type: application/json' \
    -H 'Accept: application/json, text/event-stream' \
    -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-03-26","capabilities":{},"clientInfo":{"name":"zotero-tools-probe","version":"1"}}}' || true)
  echo "attempt=$attempt http_status=${http_code:-none}" >>"$WORK_DIR/probe.log"
  if [[ "$http_code" == "200" ]]; then
    ready=1
    break
  fi
  sleep 2
done

if [[ "$ready" != "1" ]]; then
  echo "MCP endpoint did not become ready within the bounded retry window" >&2
  tail -n 80 "$WORK_DIR/zotero.stderr.log" >&2 || true
  exit 1
fi

python test/integration/mcp_seed.py --output "$WORK_DIR/seed.json" >"$WORK_DIR/seed.status.json"

mapfile -t ITEM_KEYS < <(python - "$WORK_DIR/seed.json" <<'PY'
import json, sys
with open(sys.argv[1], encoding="utf-8") as handle:
    payload = json.load(handle)
for item in payload["items"]:
    print(item["item_key"])
PY
)

if [[ ${#ITEM_KEYS[@]} -ne 2 ]]; then
  echo "Expected exactly two seeded item keys" >&2
  exit 1
fi

uv run zotero-item-export "${ITEM_KEYS[0]}" --output "$OUTPUT_DIR/single.json" \
  >"$WORK_DIR/single.stdout.json"

uv run zotero-item-export \
  --item-key "${ITEM_KEYS[0]}" \
  --item-key "${ITEM_KEYS[1]}" \
  --output-dir "$OUTPUT_DIR/batch" \
  >"$WORK_DIR/batch.stdout.json"

python - "$WORK_DIR/seed.json" "$OUTPUT_DIR/single.json" "$OUTPUT_DIR/batch" \
  "$WORK_DIR/single.stdout.json" "$WORK_DIR/batch.stdout.json" <<'PY'
import json
import pathlib
import sys

seed_path, single_path, batch_dir, single_stdout_path, batch_stdout_path = sys.argv[1:]
with open(seed_path, encoding="utf-8") as handle:
    seed = json.load(handle)

sentinel = seed["sentinel"]
items = seed["items"]


def expected(item):
    return {
        "schema": 1,
        "kind": "paper-analysis-input",
        "level": "abstract",
        "source": "zotero",
        "item_key": item["item_key"],
        "metadata": {
            "title": item["title"],
            "authors": [
                " ".join(filter(None, (creator.get("firstName"), creator.get("lastName"))))
                for creator in item["creators"]
            ],
            "year": int(item["date"][:4]),
            "venue": item["publicationTitle"],
            "doi": item["DOI"],
        },
        "abstract": item["abstractNote"],
    }

with open(single_path, encoding="utf-8") as handle:
    single = json.load(handle)
assert single == expected(items[0]), single

batch_path = pathlib.Path(batch_dir)
for item in items:
    path = batch_path / f"{item['item_key']}.json"
    assert path.exists(), path
    with path.open(encoding="utf-8") as handle:
        assert json.load(handle) == expected(item)

for stdout_path in (single_stdout_path, batch_stdout_path):
    text = pathlib.Path(stdout_path).read_text(encoding="utf-8")
    assert sentinel not in text
    status = json.loads(text)
    assert status["status"] == "ok", status
    assert len(text) < 1000

single_status = json.loads(pathlib.Path(single_stdout_path).read_text(encoding="utf-8"))
assert set(single_status) == {"status", "output"}
batch_status = json.loads(pathlib.Path(batch_stdout_path).read_text(encoding="utf-8"))
assert batch_status["exported"] == 2
assert batch_status["failed"] == 0
assert set(batch_status) == {"status", "exported", "failed", "output_dir"}
PY

echo "Headless Zotero MCP integration passed"
