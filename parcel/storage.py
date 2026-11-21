"""Per-task SQLite persistence; runtime customer records stay out of Git."""
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
import uuid


class Store:
    def __init__(self,path):
        self.path=Path(path); self.path.parent.mkdir(parents=True,exist_ok=True)
        with self.connect() as conn:
            conn.execute("CREATE TABLE IF NOT EXISTS tasks(id TEXT PRIMARY KEY, body TEXT NOT NULL, updated TEXT NOT NULL)")

    def connect(self):
        conn=sqlite3.connect(self.path,timeout=15)
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def create(self, demo=False):
        task={"id":uuid.uuid4().hex,"version":0,"fields":{},"messages":[],"quote":None,"checks":None,"tracking":None,"selected_service":None,"is_demo":bool(demo)}
        self.save(task); return task

    def get(self,task_id):
        with self.connect() as conn: row=conn.execute("SELECT body FROM tasks WHERE id=?",(task_id,)).fetchone()
        if not row: raise KeyError("运输任务不存在。")
        task=json.loads(row[0]);task.setdefault('selected_service',None);task.setdefault('is_demo',False)
        return task

    def save(self,task):
        task["updated_at"]=datetime.now(timezone.utc).isoformat()
        with self.connect() as conn:
            conn.execute("INSERT INTO tasks VALUES(?,?,?) ON CONFLICT(id) DO UPDATE SET body=excluded.body, updated=excluded.updated",(task["id"],json.dumps(task,ensure_ascii=False),task["updated_at"]))

    def list(self):
        with self.connect() as conn: rows=conn.execute("SELECT body FROM tasks ORDER BY updated DESC LIMIT 30").fetchall()
        return [self.history_row(json.loads(row[0])) for row in rows]

    @staticmethod
    def history_row(task):
        fields=task["fields"]
        tracking=task.get("tracking") or {}
        return {"id":task["id"],"updated_at":task["updated_at"],"version":task["version"],
                "goods":fields.get("goods"),"city":fields.get("destination_city"),"origin":fields.get("origin_province"),
                "destination_zip":fields.get("destination_zip"),"weight_kg":fields.get("weight_kg"),
                "selected_service":(task.get("selected_service") or {}).get("service"),"is_demo":task.get("is_demo",False),
                "tracking":({"number":tracking.get("tracking_number"),"status":tracking.get("status"),"queried_at":tracking.get("queried_at")}
                            if tracking.get("data_type")=="live_api" else None)}
