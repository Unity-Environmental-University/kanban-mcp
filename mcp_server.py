#!/usr/bin/env python3
import json, sys, os
from typing import Any, Dict
from kanban_mcp.db import KanbanDB
from kanban_mcp.tools import Tools

def list_tools() -> Dict[str, Any]:
    return {"tools": Tools.schemas()}

def db_path() -> str:
    if os.path.isdir('.local_context'):
        return os.environ.get('KANBAN_DB_PATH', os.path.join('.local_context','kanban.db'))
    return os.environ.get('KANBAN_DB_PATH', 'kanban.db')

def main():
    db = KanbanDB(db_path())
    db.init()
    tools = Tools(db)

    while True:
        line = sys.stdin.readline()
        if not line:
            break
        try:
            req = json.loads(line)
            _id = req.get('id')
            method = req.get('method')
            if method == 'initialize':
                resp = {"jsonrpc": "2.0", "id": _id, "result": {"serverInfo": {"name": "kanban-mcp", "version": "0.1.0"}}}
            elif method == 'tools/list':
                resp = {"jsonrpc": "2.0", "id": _id, "result": list_tools()}
            elif method == 'tools/call':
                p = req.get('params') or {}
                name = p.get('name')
                args = p.get('arguments') or {}
                try:
                    res = tools.call(name, args)
                    resp = {"jsonrpc": "2.0", "id": _id, "result": res}
                except Exception as e:
                    resp = {"jsonrpc": "2.0", "id": _id, "error": {"code": -32603, "message": f"Internal error: {e}"}}
            else:
                resp = {"jsonrpc": "2.0", "id": _id, "error": {"code": -32601, "message": "Method not found"}}
        except Exception as e:
            resp = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": f"Parse error: {e}"}}
        sys.stdout.write(json.dumps(resp) + "\n")
        sys.stdout.flush()

if __name__ == '__main__':
    main()
