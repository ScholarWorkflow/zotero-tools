#!/bin/bash
# Usage: SID=$(bash <skill_dir>/scripts/new-session.sh)
# Creates a new MCP session with the Zotero plugin (cookjohn/zotero-mcp)
# and prints the Mcp-Session-Id. Reuse the SID for subsequent tool calls;
# create a new one when a call times out or returns a session error.
#
# Endpoint contract: ZOTERO_MCP_URL is the FULL MCP endpoint URL (it already
# includes /mcp — never append /mcp again). Unset/empty -> production default.
ZOTERO_MCP_URL="${ZOTERO_MCP_URL:-http://127.0.0.1:23120/mcp}"
ZOTERO_MCP_URL="${ZOTERO_MCP_URL%/}"
HDR=$(mktemp)
curl -s -D "$HDR" -X POST "$ZOTERO_MCP_URL" \
  -H "Content-Type: application/json" -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-03-26","capabilities":{},"clientInfo":{"name":"zotero-read","version":"1"}}}' \
  -o /dev/null
grep -i 'Mcp-Session-Id' "$HDR" | tr -d '\r' | awk '{print $2}'
rm -f "$HDR"
