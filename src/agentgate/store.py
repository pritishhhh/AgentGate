import hashlib
import hmac
import json
import secrets
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path

from .dlp import redact
from .models import Principal


def canonical(value) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def digest(value) -> str:
    return hashlib.sha256(canonical(value).encode()).hexdigest()


class Store:
    def __init__(self, directory: Path):
        self.directory = directory
        directory.mkdir(parents=True, exist_ok=True)
        self.path = directory / "agentgate.sqlite3"
        self.key_path = directory / "audit.key"
        if not self.key_path.exists():
            try:
                with self.key_path.open("xb") as f:
                    f.write(secrets.token_bytes(32))
            except FileExistsError:
                pass
        self.audit_key = self.key_path.read_bytes()
        with self.connect() as db:
            db.executescript("""
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS principals(
                    id TEXT PRIMARY KEY, name TEXT NOT NULL, role TEXT NOT NULL,
                    tenant TEXT NOT NULL, active INTEGER NOT NULL, token_hash TEXT UNIQUE NOT NULL);
                CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS documents(
                    id TEXT PRIMARY KEY, tenant TEXT NOT NULL, classification TEXT NOT NULL,
                    title TEXT NOT NULL, content TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS records(
                    id INTEGER PRIMARY KEY, tenant TEXT NOT NULL, dataset TEXT NOT NULL, content TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS approvals(
                    id TEXT PRIMARY KEY, principal_id TEXT NOT NULL, request_hash TEXT NOT NULL,
                    tool TEXT NOT NULL, arguments TEXT NOT NULL, status TEXT NOT NULL,
                    expires REAL NOT NULL, decided_by TEXT);
                CREATE TABLE IF NOT EXISTS exports(
                    id TEXT PRIMARY KEY, principal_id TEXT NOT NULL, filename TEXT NOT NULL, created REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS audit(
                    seq INTEGER PRIMARY KEY AUTOINCREMENT, principal_id TEXT NOT NULL,
                    event TEXT NOT NULL, previous_hash TEXT NOT NULL, hash TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS rate_limits(principal_id TEXT NOT NULL, at REAL NOT NULL);
                CREATE INDEX IF NOT EXISTS audit_principal ON audit(principal_id,seq);
                CREATE INDEX IF NOT EXISTS rate_at ON rate_limits(at);
            """)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def issue(self, name: str, role: str, tenant: str) -> tuple[Principal, str]:
        token = "ag_" + secrets.token_urlsafe(32)
        principal = Principal(id=secrets.token_hex(12), name=name, role=role, tenant=tenant)
        with self.connect() as db:
            db.execute(
                "INSERT INTO principals VALUES(?,?,?,?,?,?)",
                (principal.id, name, role, tenant, 1, hashlib.sha256(token.encode()).hexdigest()),
            )
        return principal, token

    def authenticate(self, token: str) -> Principal | None:
        with self.connect() as db:
            row = db.execute(
                "SELECT * FROM principals WHERE token_hash=? AND active=1",
                (hashlib.sha256(token.encode()).hexdigest(),),
            ).fetchone()
        return self._principal(row) if row else None

    @staticmethod
    def _principal(row):
        return Principal(
            **{
                k: bool(row[k]) if k == "active" else row[k]
                for k in ("id", "name", "role", "tenant", "active")
            }
        )

    def principals(self):
        with self.connect() as db:
            return [self._principal(r).model_dump() for r in db.execute("SELECT * FROM principals")]

    def revoke(self, principal_id: str) -> bool:
        with self.connect() as db:
            return db.execute("UPDATE principals SET active=0 WHERE id=?", (principal_id,)).rowcount == 1

    def get_setting(self, key: str):
        with self.connect() as db:
            row = db.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return json.loads(row[0]) if row else None

    def set_policy(self, policy: dict, expected_version: int | None = None) -> bool:
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            current = db.execute("SELECT value FROM settings WHERE key='policy'").fetchone()
            if expected_version is not None and (
                not current or json.loads(current[0])["version"] != expected_version
            ):
                return False
            db.execute("INSERT OR REPLACE INTO settings VALUES('policy',?)", (canonical(policy),))
        return True

    def rate_allowed(self, principal_id: str, limit: int) -> bool:
        now = time.time()
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("DELETE FROM rate_limits WHERE at < ?", (now - 60,))
            count = db.execute(
                "SELECT count(*) FROM rate_limits WHERE principal_id=?", (principal_id,)
            ).fetchone()[0]
            if count >= limit:
                return False
            db.execute("INSERT INTO rate_limits VALUES(?,?)", (principal_id, now))
        return True

    def document(self, document_id: str):
        with self.connect() as db:
            row = db.execute("SELECT * FROM documents WHERE id=?", (document_id,)).fetchone()
        return dict(row) if row else None

    def search(self, principal: Principal, labels: list[str], query: str, limit: int):
        if not labels:
            return []
        placeholders = ",".join("?" for _ in labels)
        # Escape LIKE wildcard characters: caller strings cannot widen the query.
        escaped = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        with self.connect() as db:
            rows = db.execute(
                f"""SELECT id,title,classification,substr(content,1,600) AS excerpt
                FROM documents WHERE tenant=? AND classification IN ({placeholders})
                AND (title LIKE ? ESCAPE '\\' OR content LIKE ? ESCAPE '\\') LIMIT ?""",
                (principal.tenant, *labels, f"%{escaped}%", f"%{escaped}%", limit),
            ).fetchall()
        return [dict(r) for r in rows]

    def records(self, tenant: str, dataset: str, limit: int):
        with self.connect() as db:
            rows = db.execute(
                "SELECT content FROM records WHERE tenant=? AND dataset=? ORDER BY id LIMIT ?",
                (tenant, dataset, limit),
            ).fetchall()
        return [json.loads(r[0]) for r in rows]

    def pending(self, principal_id: str, tool: str, arguments: dict):
        request_hash = digest({"principal_id": principal_id, "tool": tool, "arguments": arguments})
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            existing = db.execute(
                """SELECT id FROM approvals WHERE principal_id=? AND request_hash=?
                AND status='pending' AND expires>?""",
                (principal_id, request_hash, time.time()),
            ).fetchone()
            if existing:
                return existing[0]
            ticket = secrets.token_hex(16)
            db.execute(
                "INSERT INTO approvals VALUES(?,?,?,?,?,?,?,?)",
                (
                    ticket,
                    principal_id,
                    request_hash,
                    tool,
                    canonical(redact(arguments)[0]),
                    "pending",
                    time.time() + 600,
                    None,
                ),
            )
        return ticket

    def approvals(self, principal: Principal):
        with self.connect() as db:
            query = "SELECT * FROM approvals"
            rows = db.execute(
                query if principal.role == "admin" else query + " WHERE principal_id=?",
                () if principal.role == "admin" else (principal.id,),
            ).fetchall()
        return [{**dict(r), "arguments": json.loads(r["arguments"])} for r in rows]

    def decide(self, ticket: str, admin_id: str, status: str) -> bool:
        with self.connect() as db:
            return (
                db.execute(
                    """UPDATE approvals SET status=?,decided_by=? WHERE id=?
                AND status='pending' AND expires>?""",
                    (status, admin_id, ticket, time.time()),
                ).rowcount
                == 1
            )

    def consume(self, ticket: str, principal_id: str, tool: str, arguments: dict) -> bool:
        request_hash = digest({"principal_id": principal_id, "tool": tool, "arguments": arguments})
        with self.connect() as db:
            return (
                db.execute(
                    """UPDATE approvals SET status='consumed' WHERE id=? AND principal_id=?
                AND request_hash=? AND status='approved' AND expires>?""",
                    (ticket, principal_id, request_hash, time.time()),
                ).rowcount
                == 1
            )

    def add_export(self, export_id: str, principal_id: str, filename: str):
        with self.connect() as db:
            db.execute(
                "INSERT INTO exports VALUES(?,?,?,?)", (export_id, principal_id, filename, time.time())
            )

    def get_export(self, export_id: str, principal_id: str):
        with self.connect() as db:
            row = db.execute(
                "SELECT * FROM exports WHERE id=? AND principal_id=?", (export_id, principal_id)
            ).fetchone()
        return dict(row) if row else None

    def audit(self, principal_id: str, event: dict):
        event = {**event, "principal_id": principal_id, "at": time.time()}
        raw = canonical(event)
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            previous = db.execute("SELECT hash FROM audit ORDER BY seq DESC LIMIT 1").fetchone()
            previous_hash = previous[0] if previous else "0" * 64
            chain_hash = hmac.new(self.audit_key, (previous_hash + raw).encode(), hashlib.sha256).hexdigest()
            db.execute(
                "INSERT INTO audit(principal_id,event,previous_hash,hash) VALUES(?,?,?,?)",
                (principal_id, raw, previous_hash, chain_hash),
            )

    def events(self, principal: Principal, after: int = 0, limit: int = 100):
        with self.connect() as db:
            rows = db.execute(
                "SELECT * FROM audit WHERE seq>?"
                + ("" if principal.role == "admin" else " AND principal_id=?")
                + " ORDER BY seq LIMIT ?",
                (after, limit) if principal.role == "admin" else (after, principal.id, limit),
            ).fetchall()
        return [{"seq": r["seq"], **json.loads(r["event"]), "hash": r["hash"]} for r in rows]

    def verify_audit(self):
        previous = "0" * 64
        count = 0
        with self.connect() as db:
            for row in db.execute("SELECT * FROM audit ORDER BY seq"):
                expected = hmac.new(
                    self.audit_key, (previous + row["event"]).encode(), hashlib.sha256
                ).hexdigest()
                if row["previous_hash"] != previous or not hmac.compare_digest(expected, row["hash"]):
                    return {"valid": False, "checked": count, "failed_at": row["seq"]}
                previous = row["hash"]
                count += 1
        return {"valid": True, "checked": count, "head": previous}
