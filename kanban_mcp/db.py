import sqlite3, os, time, json, subprocess, urllib.request, urllib.error
from typing import List, Dict, Any, Optional, Tuple

DEFAULT_COLUMNS = [
    ('backlog', None),
    ('current_sprint', None),
    ('in_progress', None),
    ('blocked', None),
    ('done', None),
    ('archived', None),
]

class KanbanDB:
    def __init__(self, path: str):
        self.path = path
        os.makedirs(os.path.dirname(path) or '.', exist_ok=True)
    def conn(self):
        return sqlite3.connect(self.path)
    def init(self):
        with self.conn() as c:
            c.execute("PRAGMA journal_mode=WAL;")
            c.execute("CREATE TABLE IF NOT EXISTS boards (id TEXT PRIMARY KEY, user_key TEXT NOT NULL, board_key TEXT NOT NULL, created_at TEXT, UNIQUE(user_key, board_key))")
            c.execute("CREATE TABLE IF NOT EXISTS columns (id TEXT PRIMARY KEY, board_id TEXT NOT NULL, name TEXT NOT NULL, wip_limit INTEGER, position INTEGER, UNIQUE(board_id, name))")
            c.execute("CREATE TABLE IF NOT EXISTS cards (id TEXT PRIMARY KEY, board_id TEXT NOT NULL, title TEXT NOT NULL, description TEXT, assignee TEXT, priority TEXT, column_id TEXT NOT NULL, created_at TEXT, updated_at TEXT, external_type TEXT, external_id TEXT, UNIQUE(board_id, external_type, external_id))")
            c.execute("CREATE INDEX IF NOT EXISTS idx_cards_title ON cards(title)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_cards_desc ON cards(description)")
            # Add blocked metadata columns if missing
            try:
                c.execute("ALTER TABLE cards ADD COLUMN blocked_by TEXT")
            except Exception:
                pass
            try:
                c.execute("ALTER TABLE cards ADD COLUMN blocked_reason TEXT")
            except Exception:
                pass
            try:
                c.execute("ALTER TABLE cards ADD COLUMN blocked_since TEXT")
            except Exception:
                pass
            # Event bus tables
            c.execute("""
            CREATE TABLE IF NOT EXISTS listeners (
                id TEXT PRIMARY KEY,
                board_id TEXT NOT NULL,
                event TEXT NOT NULL,
                kind TEXT NOT NULL,           -- 'command' | 'http'
                target TEXT NOT NULL,         -- shell command or URL
                filter_json TEXT,             -- optional JSON for future filtering
                active INTEGER DEFAULT 1,
                created_at TEXT,
                updated_at TEXT
            )
            """)
            c.execute("""
            CREATE TABLE IF NOT EXISTS events (
                id TEXT PRIMARY KEY,
                board_id TEXT NOT NULL,
                event TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                status TEXT NOT NULL,         -- 'queued' | 'processing' | 'done' | 'failed'
                retry_count INTEGER DEFAULT 0,
                last_error TEXT,
                created_at TEXT,
                updated_at TEXT
            )
            """)
            c.commit()
    def uid(self) -> str:
        return hex(int(time.time()*1000000))[2:][-8:]
    def ensure_board(self, user_key: str, board_key: str = 'default') -> Dict[str, Any]:
        now = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
        with self.conn() as c:
            row = c.execute("SELECT id,user_key,board_key,created_at FROM boards WHERE user_key=? AND board_key=?", (user_key, board_key)).fetchone()
            if row:
                return {"id": row[0], "user_key": row[1], "board_key": row[2], "created_at": row[3]}
            bid = self.uid()
            c.execute("INSERT INTO boards(id,user_key,board_key,created_at) VALUES(?,?,?,?)", (bid, user_key, board_key, now))
            c.commit()
            return {"id": bid, "user_key": user_key, "board_key": board_key, "created_at": now}
    def seed_defaults_for_board(self, board_id: str) -> None:
        with self.conn() as c:
            cnt = c.execute("SELECT COUNT(1) FROM columns WHERE board_id=?", (board_id,)).fetchone()[0]
            if cnt == 0:
                pos = 0
                for name, wip in DEFAULT_COLUMNS:
                    cid = self.uid()
                    c.execute("INSERT INTO columns(id,board_id,name,wip_limit,position) VALUES(?,?,?,?,?)", (cid, board_id, name, wip, pos))
                    pos += 1
                c.commit()
    def column_by_name(self, board_id: str, name: str) -> Optional[Dict[str, Any]]:
        with self.conn() as c:
            row = c.execute("SELECT id,name,wip_limit,position FROM columns WHERE board_id=? AND name=?", (board_id, name)).fetchone()
            if row:
                return {"id": row[0], "name": row[1], "wip_limit": row[2], "position": row[3]}
            return None
    def columns(self, board_id: str) -> List[Dict[str, Any]]:
        with self.conn() as c:
            cur = c.execute("SELECT id,name,wip_limit,position FROM columns WHERE board_id=? ORDER BY position ASC", (board_id,))
            return [{"id": r[0], "name": r[1], "wip_limit": r[2], "position": r[3]} for r in cur.fetchall()]
    def add_column(self, board_id: str, name: str, wip_limit: Optional[int] = None) -> Dict[str, Any]:
        with self.conn() as c:
            pos = c.execute("SELECT COALESCE(MAX(position), -1)+1 FROM columns WHERE board_id=?", (board_id,)).fetchone()[0]
            cid = self.uid()
            c.execute("INSERT OR IGNORE INTO columns(id,board_id,name,wip_limit,position) VALUES(?,?,?,?,?)", (cid, board_id, name, wip_limit, pos))
            c.commit()
            return {"id": cid, "name": name, "wip_limit": wip_limit, "position": pos}
    def ensure_column(self, board_id: str, name: str) -> Dict[str, Any]:
        col = self.column_by_name(board_id, name)
        return col or self.add_column(board_id, name)
    def add_card(self, board_id: str, title: str, column: str, description: str = '', assignee: str = '', priority: str = '', external_type: str = '', external_id: str = '') -> Dict[str, Any]:
        col = self.ensure_column(board_id, column)
        with self.conn() as c:
            cid = self.uid()
            now = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
            c.execute("INSERT INTO cards(id,board_id,title,description,assignee,priority,column_id,created_at,updated_at,external_type,external_id) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                      (cid, board_id, title, description, assignee, priority, col['id'], now, now, external_type, external_id))
            c.commit()
            return {"id": cid, "title": title, "column": col['name']}
    def _current_card_column(self, card_id: str) -> Optional[str]:
        with self.conn() as c:
            row = c.execute(
                "SELECT columns.name FROM cards JOIN columns ON cards.column_id = columns.id WHERE cards.id=?",
                (card_id,),
            ).fetchone()
            return row[0] if row else None
    def move_card(self, board_id: str, card_id: str, target_column: str, blocked_by: Optional[str] = None, blocked_reason: Optional[str] = None) -> Dict[str, Any]:
        prev_col = self._current_card_column(card_id)
        col = self.ensure_column(board_id, target_column)
        with self.conn() as c:
            now = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
            if col['name'] == 'blocked':
                if not (blocked_by and (blocked_reason or '').strip()):
                    raise ValueError("moving to 'blocked' requires blocked_by and blocked_reason")
                c.execute(
                    "UPDATE cards SET column_id=?, updated_at=?, blocked_by=?, blocked_reason=?, blocked_since=? WHERE id=?",
                    (col['id'], now, blocked_by, blocked_reason, now, card_id),
                )
            else:
                c.execute(
                    "UPDATE cards SET column_id=?, updated_at=?, blocked_by=NULL, blocked_reason=NULL, blocked_since=NULL WHERE id=?",
                    (col['id'], now, card_id),
                )
            c.commit()
            return {"id": card_id, "from": prev_col, "to": col['name']}
    def update_card(self, card_id: str, fields: Dict[str, Any]) -> Dict[str, Any]:
        allowed = {k:v for k,v in fields.items() if k in ('title','description','assignee','priority')}
        if not allowed:
            return {"updated": 0}
        sets = ",".join([f"{k}=?" for k in allowed.keys()])
        vals = list(allowed.values())
        with self.conn() as c:
            c.execute(f"UPDATE cards SET {sets}, updated_at=? WHERE id=?", (*vals, time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), card_id))
            c.commit()
            return {"updated": 1}
    def list_cards(self, board_id: str, column: Optional[str] = None) -> List[Dict[str, Any]]:
        with self.conn() as c:
            if column:
                col = self.column_by_name(board_id, column)
                if not col:
                    return []
                cur = c.execute("SELECT id,title,description,assignee,priority,external_type,external_id,blocked_by,blocked_reason,blocked_since FROM cards WHERE board_id=? AND column_id=? ORDER BY created_at ASC", (board_id, col['id']))
            else:
                cur = c.execute("SELECT id,title,description,assignee,priority,external_type,external_id,blocked_by,blocked_reason,blocked_since FROM cards WHERE board_id=? ORDER BY created_at ASC", (board_id,))
            rows = cur.fetchall()
            out = []
            for r in rows:
                out.append({
                    "id": r[0],
                    "title": r[1],
                    "description": r[2],
                    "assignee": r[3],
                    "priority": r[4],
                    "external_type": r[5],
                    "external_id": r[6],
                    "blocked_by": r[7],
                    "blocked_reason": r[8],
                    "blocked_since": r[9],
                })
            return out
    def search_cards(self, board_id: str, query: str) -> List[Dict[str, Any]]:
        like = f"%{query}%"
        with self.conn() as c:
            cur = c.execute("SELECT id,title,description FROM cards WHERE board_id=? AND (title LIKE ? OR description LIKE ?) ORDER BY created_at DESC LIMIT 50", (board_id, like, like))
            return [{"id": r[0], "title": r[1], "description": r[2]} for r in cur.fetchall()]

    # --- Event bus APIs ---
    def add_listener(self, board_id: str, event: str, kind: str, target: str, filter_json: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        now = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
        lid = self.uid()
        with self.conn() as c:
            c.execute(
                "INSERT INTO listeners(id,board_id,event,kind,target,filter_json,active,created_at,updated_at) VALUES(?,?,?,?,?,?,1,?,?)",
                (lid, board_id, event, kind, target, json.dumps(filter_json or {}), now, now),
            )
            c.commit()
            return {"id": lid, "event": event, "kind": kind, "target": target}
    def list_listeners(self, board_id: str) -> List[Dict[str, Any]]:
        with self.conn() as c:
            cur = c.execute(
                "SELECT id,event,kind,target,active,created_at FROM listeners WHERE board_id=? ORDER BY created_at ASC",
                (board_id,),
            )
            return [
                {"id": r[0], "event": r[1], "kind": r[2], "target": r[3], "active": r[4], "created_at": r[5]}
                for r in cur.fetchall()
            ]
    def remove_listener(self, listener_id: str) -> Dict[str, Any]:
        with self.conn() as c:
            c.execute("UPDATE listeners SET active=0, updated_at=? WHERE id=?", (time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), listener_id))
            c.commit()
            return {"removed": 1}
    def enqueue_event(self, board_id: str, event: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        now = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
        eid = self.uid()
        with self.conn() as c:
            c.execute(
                "INSERT INTO events(id,board_id,event,payload_json,status,retry_count,created_at,updated_at) VALUES(?,?,?,?,?,0,?,?)",
                (eid, board_id, event, json.dumps(payload, ensure_ascii=False), 'queued', now, now),
            )
            c.commit()
            return {"id": eid, "event": event}
    def list_events(self, board_id: str, status: Optional[str] = None, limit: int = 100) -> List[Dict[str, Any]]:
        with self.conn() as c:
            if status:
                cur = c.execute(
                    "SELECT id,event,status,retry_count,created_at FROM events WHERE board_id=? AND status=? ORDER BY created_at ASC LIMIT ?",
                    (board_id, status, limit),
                )
            else:
                cur = c.execute(
                    "SELECT id,event,status,retry_count,created_at FROM events WHERE board_id=? ORDER BY created_at ASC LIMIT ?",
                    (board_id, limit),
                )
            return [
                {"id": r[0], "event": r[1], "status": r[2], "retry_count": r[3], "created_at": r[4]}
                for r in cur.fetchall()
            ]
    def _matching_listeners(self, board_id: str, event: str) -> List[Dict[str, Any]]:
        with self.conn() as c:
            cur = c.execute(
                "SELECT id,event,kind,target,filter_json FROM listeners WHERE board_id=? AND active=1 AND (event=? OR event='*')",
                (board_id, event),
            )
            out = []
            for r in cur.fetchall():
                out.append({
                    "id": r[0],
                    "event": r[1],
                    "kind": r[2],
                    "target": r[3],
                    "filter": json.loads(r[4] or '{}')
                })
            return out
    def _deliver(self, kind: str, target: str, payload: Dict[str, Any]) -> Tuple[bool, str]:
        data = json.dumps(payload).encode('utf-8')
        try:
            if kind == 'command':
                # Execute shell command, send JSON on stdin
                proc = subprocess.run(target, input=data, shell=True, capture_output=True)
                if proc.returncode != 0:
                    return False, (proc.stderr.decode() or proc.stdout.decode() or f"exit {proc.returncode}")[:500]
                return True, proc.stdout.decode()[:500]
            elif kind == 'http':
                req = urllib.request.Request(target, data=data, headers={'Content-Type': 'application/json'}, method='POST')
                with urllib.request.urlopen(req, timeout=10) as resp:
                    _ = resp.read()
                return True, 'ok'
            else:
                return False, f'unknown kind {kind}'
        except Exception as e:
            return False, str(e)[:500]
    def process_queue(self, board_id: str, execute: bool = False, max_events: int = 25) -> Dict[str, Any]:
        now = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
        processed = 0
        failed = 0
        with self.conn() as c:
            rows = c.execute(
                "SELECT id,event,payload_json FROM events WHERE board_id=? AND status='queued' ORDER BY created_at ASC LIMIT ?",
                (board_id, max_events),
            ).fetchall()
        for eid, ev, payload_json in rows:
            listeners = self._matching_listeners(board_id, ev)
            status = 'done'
            last_error = None
            if execute and listeners:
                payload = json.loads(payload_json)
                for ln in listeners:
                    ok, info = self._deliver(ln['kind'], ln['target'], {"event": ev, "payload": payload})
                    if not ok:
                        status = 'failed'
                        last_error = info
                        failed += 1
                        break
            # update event status
            with self.conn() as c:
                c.execute(
                    "UPDATE events SET status=?, updated_at=?, last_error=? WHERE id=?",
                    (status, now, last_error, eid),
                )
                c.commit()
            processed += 1
        return {"processed": processed, "failed": failed}
    def retry_event(self, event_id: str) -> Dict[str, Any]:
        with self.conn() as c:
            c.execute(
                "UPDATE events SET status='queued', retry_count=retry_count+1, updated_at=? WHERE id=?",
                (time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), event_id),
            )
            c.commit()
            return {"queued": 1}
