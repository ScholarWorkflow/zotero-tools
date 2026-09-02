#!/bin/bash
# Usage: SID=$(bash <skill_dir>/scripts/new-session.sh)
# Creates a new MCP session with the Zotero plugin (cookjohn/zotero-mcp, port 23120)
# and prints the Mcp-Session-Id. Reuse the SID for subsequent tool calls;
# create a new one when a call times out or returns a session error.
HDR=$(mktemp)
curl -s -D "$HDR" -X POST http://127.0.0.1:23120/mcp \
  -H "Content-Type: application/json" -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-03-26","capabilities":{},"clientInfo":{"name":"zotero-read","version":"1"}}}' \
  -o /dev/null
grep -i 'Mcp-Session-Id' "$HDR" | tr -d '\r' | awk '{print $2}'
rm -f "$HDR"
