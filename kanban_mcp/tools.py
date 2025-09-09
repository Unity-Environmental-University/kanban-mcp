import json, os
from typing import Any, Dict, List
from .db import KanbanDB

class Tools:
    def __init__(self, db: KanbanDB):
        self.db = db
    @staticmethod
    def schemas() -> List[Dict[str, Any]]:
        return [
            {"name": "kanban_handshake", "description": "Ensure board for user and seed defaults", "inputSchema": {"type": "object", "properties": {"user_key": {"type": "string"}, "name": {"type": "string"}, "board_key": {"type": "string"}}, "required": ["user_key"]}},
            {"name": "board_info", "description": "List columns and counts for board", "inputSchema": {"type": "object", "properties": {"user_key": {"type": "string"}, "board_key": {"type": "string"}}, "required": ["user_key"]}},
            {"name": "add_column", "description": "Add a column", "inputSchema": {"type": "object", "properties": {"user_key": {"type": "string"}, "board_key": {"type": "string"}, "name": {"type": "string"}, "wip_limit": {"type": "integer"}}, "required": ["user_key","name"]}},
            {"name": "add_card", "description": "Create a card", "inputSchema": {"type": "object", "properties": {"user_key": {"type": "string"}, "board_key": {"type": "string"}, "title": {"type": "string"}, "column": {"type": "string"}, "description": {"type": "string"}, "assignee": {"type": "string"}, "priority": {"type": "string"}, "external_type": {"type": "string"}, "external_id": {"type": "string"}}, "required": ["user_key","title","column"]}},
            {"name": "move_card", "description": "Move card to column (moving to 'blocked' requires blocked_by and blocked_reason)", "inputSchema": {"type": "object", "properties": {"user_key": {"type": "string"}, "board_key": {"type": "string"}, "card_id": {"type": "string"}, "target_column": {"type": "string"}, "blocked_by": {"type": "string"}, "blocked_reason": {"type": "string"}}, "required": ["user_key","card_id","target_column"]}},
            {"name": "update_card", "description": "Update card fields", "inputSchema": {"type": "object", "properties": {"user_key": {"type": "string"}, "board_key": {"type": "string"}, "card_id": {"type": "string"}, "fields": {"type": "object"}}, "required": ["user_key","card_id","fields"]}},
            {"name": "list_cards", "description": "List cards (optional column)", "inputSchema": {"type": "object", "properties": {"user_key": {"type": "string"}, "board_key": {"type": "string"}, "column": {"type": "string"}}, "required": ["user_key"]}},
            {"name": "search_cards", "description": "Search cards by text", "inputSchema": {"type": "object", "properties": {"user_key": {"type": "string"}, "board_key": {"type": "string"}, "query": {"type": "string"}}, "required": ["user_key","query"]}},
            {"name": "sync_from_story", "description": "Optional file-based sync from story files", "inputSchema": {"type": "object", "properties": {"user_key": {"type": "string"}, "board_key": {"type": "string"}}, "required": ["user_key"]}},
            # Event bus tools
            {"name": "register_listener", "description": "Register event listener (command or http)", "inputSchema": {"type": "object", "properties": {"user_key": {"type": "string"}, "board_key": {"type": "string"}, "event": {"type": "string"}, "kind": {"type": "string"}, "target": {"type": "string"}, "filter": {"type": "object"}}, "required": ["user_key","event","kind","target"]}},
            {"name": "list_listeners", "description": "List listeners for the board", "inputSchema": {"type": "object", "properties": {"user_key": {"type": "string"}, "board_key": {"type": "string"}}, "required": ["user_key"]}},
            {"name": "remove_listener", "description": "Deactivate a listener by id", "inputSchema": {"type": "object", "properties": {"user_key": {"type": "string"}, "board_key": {"type": "string"}, "listener_id": {"type": "string"}}, "required": ["user_key","listener_id"]}},
            {"name": "list_events", "description": "List queued/failed/done events", "inputSchema": {"type": "object", "properties": {"user_key": {"type": "string"}, "board_key": {"type": "string"}, "status": {"type": "string"}, "limit": {"type": "integer"}}, "required": ["user_key"]}},
            {"name": "process_queue", "description": "Process queued events for board", "inputSchema": {"type": "object", "properties": {"user_key": {"type": "string"}, "board_key": {"type": "string"}, "execute": {"type": "boolean"}, "max_events": {"type": "integer"}}, "required": ["user_key"]}},
            {"name": "retry_event", "description": "Retry a failed event by id", "inputSchema": {"type": "object", "properties": {"user_key": {"type": "string"}, "board_key": {"type": "string"}, "event_id": {"type": "string"}}, "required": ["user_key","event_id"]}},
            {"name": "test_event", "description": "Enqueue a test event with payload", "inputSchema": {"type": "object", "properties": {"user_key": {"type": "string"}, "board_key": {"type": "string"}, "event": {"type": "string"}, "payload": {"type": "object"}}, "required": ["user_key","event"]}},
        ]
    def _res_text(self, text: str) -> Dict[str, Any]:
        return {"content": [{"type": "text", "text": text}]}
    def call(self, name: str, args: Dict[str, Any]) -> Dict[str, Any]:
        if name == 'kanban_handshake':
            user_key = args.get('user_key','')
            board_key = args.get('board_key') or 'default'
            board = self.db.ensure_board(user_key, board_key)
            self.db.seed_defaults_for_board(board['id'])
            return self._res_text(json.dumps({"db": self.db.path, "board_id": board['id'], "user_key": user_key, "board_key": board_key}))
        if name == 'board_info':
            user_key = args.get('user_key','')
            board_key = args.get('board_key') or 'default'
            board = self.db.ensure_board(user_key, board_key)
            cols = self.db.columns(board['id'])
            info = []
            for c in cols:
                cnt = len(self.db.list_cards(board['id'], c['name']))
                info.append({"column": c['name'], "wip_limit": c['wip_limit'], "count": cnt})
            return self._res_text(json.dumps(info, ensure_ascii=False))
        if name == 'add_column':
            board = self.db.ensure_board(args.get('user_key',''), args.get('board_key') or 'default')
            col = self.db.add_column(board['id'], args.get('name',''), args.get('wip_limit'))
            # enqueue event
            try:
                self.db.enqueue_event(board['id'], 'column_created', {"column": col})
            except Exception:
                pass
            return self._res_text(json.dumps(col))
        if name == 'add_card':
            board = self.db.ensure_board(args.get('user_key',''), args.get('board_key') or 'default')
            card = self.db.add_card(
                board_id=board['id'],
                title=args.get('title',''),
                column=args.get('column',''),
                description=args.get('description','') or '',
                assignee=args.get('assignee','') or '',
                priority=args.get('priority','') or '',
                external_type=args.get('external_type','') or '',
                external_id=args.get('external_id','') or ''
            )
            try:
                self.db.enqueue_event(board['id'], 'card_created', card)
            except Exception:
                pass
            return self._res_text(json.dumps(card))
        if name == 'move_card':
            board = self.db.ensure_board(args.get('user_key',''), args.get('board_key') or 'default')
            res = self.db.move_card(
                board['id'],
                args.get('card_id',''),
                args.get('target_column',''),
                args.get('blocked_by'),
                args.get('blocked_reason')
            )
            try:
                self.db.enqueue_event(board['id'], 'card_moved', res)
            except Exception:
                pass
            return self._res_text(json.dumps(res))
        if name == 'update_card':
            res = self.db.update_card(args.get('card_id',''), args.get('fields') or {})
            try:
                self.db.enqueue_event(self.db.ensure_board(args.get('user_key',''), args.get('board_key') or 'default')['id'], 'card_updated', {"id": args.get('card_id',''), "fields": args.get('fields') or {}})
            except Exception:
                pass
            return self._res_text(json.dumps(res))
        if name == 'list_cards':
            board = self.db.ensure_board(args.get('user_key',''), args.get('board_key') or 'default')
            cards = self.db.list_cards(board['id'], args.get('column'))
            return self._res_text(json.dumps(cards, ensure_ascii=False))
        if name == 'search_cards':
            board = self.db.ensure_board(args.get('user_key',''), args.get('board_key') or 'default')
            res = self.db.search_cards(board['id'], args.get('query',''))
            return self._res_text(json.dumps(res, ensure_ascii=False))
        if name == 'sync_from_story':
            if not os.environ.get('KANBAN_SYNC_ENABLE'):
                return self._res_text("sync disabled")
            try:
                board = self.db.ensure_board(args.get('user_key',''), args.get('board_key') or 'default')
                if os.path.exists('.local_context/story_state.json') and os.path.exists('.local_context/story_links.json'):
                    with open('.local_context/story_state.json','r') as f:
                        state=json.load(f)
                    with open('.local_context/story_links.json','r') as f:
                        links=json.load(f)
                    created=0
                    mapping = {
                        'ideating': 'backlog',
                        'developing': 'in_progress',
                        'validating': 'current_sprint',
                        'done': 'done',
                    }
                    for sid, s in state.items():
                        column = mapping.get(s.get('phase',''), 'backlog')
                        try:
                            self.db.add_card(board_id=board['id'], title=f"Story {sid}", column=column, external_type='story', external_id=sid)
                            try:
                                self.db.enqueue_event(board['id'], 'card_created', {"external_type": 'story', "external_id": sid, "column": column})
                            except Exception:
                                pass
                            created+=1
                        except Exception:
                            pass
                    return self._res_text(f"synced {created} stories")
                return self._res_text("no story files found")
            except Exception as e:
                return self._res_text(f"sync error: {e}")
        # Event bus tools
        if name == 'register_listener':
            board = self.db.ensure_board(args.get('user_key',''), args.get('board_key') or 'default')
            lst = self.db.add_listener(board['id'], args.get('event','*'), args.get('kind','command'), args.get('target',''), args.get('filter') or {})
            return self._res_text(json.dumps(lst))
        if name == 'list_listeners':
            board = self.db.ensure_board(args.get('user_key',''), args.get('board_key') or 'default')
            lst = self.db.list_listeners(board['id'])
            return self._res_text(json.dumps(lst, ensure_ascii=False))
        if name == 'remove_listener':
            res = self.db.remove_listener(args.get('listener_id',''))
            return self._res_text(json.dumps(res))
        if name == 'list_events':
            board = self.db.ensure_board(args.get('user_key',''), args.get('board_key') or 'default')
            evs = self.db.list_events(board['id'], args.get('status'), int(args.get('limit', 100) or 100))
            return self._res_text(json.dumps(evs, ensure_ascii=False))
        if name == 'process_queue':
            board = self.db.ensure_board(args.get('user_key',''), args.get('board_key') or 'default')
            res = self.db.process_queue(board['id'], bool(args.get('execute', False)), int(args.get('max_events', 25) or 25))
            return self._res_text(json.dumps(res))
        if name == 'retry_event':
            res = self.db.retry_event(args.get('event_id',''))
            return self._res_text(json.dumps(res))
        if name == 'test_event':
            board = self.db.ensure_board(args.get('user_key',''), args.get('board_key') or 'default')
            res = self.db.enqueue_event(board['id'], args.get('event','test'), args.get('payload') or {"hello": "world"})
            return self._res_text(json.dumps(res))
        raise ValueError(f"Unknown tool: {name}")
