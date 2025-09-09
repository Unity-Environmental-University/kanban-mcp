# Kanban MCP (SQLite)

Standalone MCP stdio server for a Kanban board backed by SQLite.
- Default agile columns seeded: backlog, current_sprint, in_progress, blocked, done, archived
- Tools: kanban_handshake, board_info, add_column, add_card, move_card, update_card, list_cards, search_cards, sync_from_story (optional)
- External linking: external_type=story, external_id=<story_id>

## Quickstart

```bash
python3 mcp_server.py
```

Output handling note
- When using `bin/kanban-mcp-call`, avoid piping directly to early‑exiting filters (e.g., `head`, `sed -n 1,2p`). Those can close the pipe early and cause a harmless BrokenPipeError upstream.
- Prefer capturing output and parsing the JSON string in `result.content[0].text`.

Claude/Code MCP config example:
```json
{
  "mcpServers": {
    "kanban-mcp": {
      "command": "python3",
      "args": ["/absolute/path/to/kanban-mcp/mcp_server.py"],
      "env": { "PYTHONUNBUFFERED": "1" }
    }
  }
}
```

## Environment
- `KANBAN_DB_PATH`: Path to SQLite DB (default: `.local_context/kanban.db` if present, else `kanban.db`).
- `KANBAN_SYNC_ENABLE`: If set (any value), enables `sync_from_story` to read `.local_context/story_state.json` and `.local_context/story_links.json`.

## Blocked Workflow
- Moving a card into the `blocked` column requires metadata:
  - `blocked_by`: username or owner responsible for unblocking
  - `blocked_reason`: short reason for the block
  - The system records `blocked_since` automatically.

- Tool contract update: `move_card`
  - Arguments: `user_key`, `card_id`, `target_column`, plus optional `blocked_by`, `blocked_reason`.
  - When `target_column == 'blocked'`, both `blocked_by` and `blocked_reason` are required; moving out of `blocked` clears the blocked fields.

- Example (tools/call):
```json
{
  "jsonrpc": "2.0",
  "id": 2,
  "method": "tools/call",
  "params": {
    "name": "move_card",
    "arguments": {
      "user_key": "dev123",
      "card_id": "<id>",
      "target_column": "blocked",
      "blocked_by": "hallie",
      "blocked_reason": "Waiting on API key"
    }
  }
}
```

- Listing blocked cards now includes: `blocked_by`, `blocked_reason`, `blocked_since`.

### Helper script
- `bin/kanban-block-card`: prompts or accepts args to move a card to `blocked` with required metadata.
