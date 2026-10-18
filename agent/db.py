import json
import os
from datetime import datetime
from pathlib import Path

from psycopg.types.json import Jsonb


def rds_configured() -> bool:
    return bool(os.getenv("RDS_HOST", "").strip())


class Database:
    """Notes and chat history in the RDS Postgres instance."""

    def __init__(self, notes_file: Path):
        self.conn = _connect()
        try:
            self._ensure_schema()
            self._import_notes_file(notes_file)
        except Exception:
            self.conn.close()
            raise
        self.notes = PostgresNotes(self)
        self.chat = ChatLog(self)

    def close(self) -> None:
        self.conn.close()

    def _ensure_schema(self) -> None:
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS notes (
                id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
                note_text text NOT NULL,
                saved_at timestamptz NOT NULL
            )
            """
        )
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS chat_messages (
                id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
                body jsonb NOT NULL
            )
            """
        )
        self.conn.commit()

    def _import_notes_file(self, path: Path) -> None:
        count = self.conn.execute("SELECT count(*) FROM notes").fetchone()[0]
        if count or not path.is_file():
            self.conn.commit()
            return
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, list):
            self.conn.commit()
            return
        for note in raw:
            if not isinstance(note, dict):
                continue
            text = str(note.get("text", "")).strip()
            if not text:
                continue
            saved = note.get("saved_at")
            try:
                when = datetime.fromisoformat(saved) if isinstance(saved, str) else None
            except ValueError:
                when = None
            self.conn.execute(
                "INSERT INTO notes (note_text, saved_at) VALUES (%s, %s)",
                (text, when or datetime.now().astimezone()),
            )
        self.conn.commit()


class PostgresNotes:
    def __init__(self, database: Database):
        self.database = database

    def remember(self, text: str) -> str:
        cleaned = text.strip()
        if not cleaned:
            raise ValueError("note text is empty")
        conn = self.database.conn
        conn.execute(
            "INSERT INTO notes (note_text, saved_at) VALUES (%s, %s)",
            (cleaned, datetime.now().astimezone()),
        )
        count = conn.execute("SELECT count(*) FROM notes").fetchone()[0]
        conn.commit()
        return f"Saved note {count}."

    def recall(self, query: str = "") -> str:
        needle = query.strip()
        conn = self.database.conn
        if needle:
            rows = conn.execute(
                """
                SELECT note_text, saved_at
                FROM (
                    SELECT note_text, saved_at, id
                    FROM notes
                    WHERE note_text ILIKE %s ESCAPE '\\'
                    ORDER BY id DESC
                    LIMIT 20
                ) recent
                ORDER BY id ASC
                """,
                (_like_pattern(needle),),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT note_text, saved_at
                FROM (
                    SELECT note_text, saved_at, id
                    FROM notes
                    ORDER BY id DESC
                    LIMIT 20
                ) recent
                ORDER BY id ASC
                """
            ).fetchall()
        conn.commit()
        if not rows:
            return "No matching notes."
        lines = []
        for note_text, saved_at in rows:
            when = saved_at.astimezone().isoformat(timespec="seconds")
            lines.append(f"{when}: {note_text}")
        return "\n".join(lines)


class ChatLog:
    def __init__(self, database: Database):
        self.database = database

    def load(self) -> list[dict]:
        conn = self.database.conn
        rows = conn.execute(
            "SELECT body FROM chat_messages ORDER BY id"
        ).fetchall()
        conn.commit()
        return [row[0] for row in rows]

    def save(self, messages: list[dict]) -> None:
        conn = self.database.conn
        try:
            with conn.transaction():
                conn.execute("DELETE FROM chat_messages")
                for message in messages:
                    conn.execute(
                        "INSERT INTO chat_messages (body) VALUES (%s)",
                        (Jsonb(message),),
                    )
        except Exception:
            conn.rollback()
            raise

    def clear(self) -> None:
        conn = self.database.conn
        conn.execute("DELETE FROM chat_messages")
        conn.commit()


def _connect():
    import psycopg

    return psycopg.connect(
        host=os.environ["RDS_HOST"].strip(),
        port=os.getenv("RDS_PORT", "5432").strip() or "5432",
        dbname=os.getenv("RDS_DB", "postgres").strip() or "postgres",
        user=os.getenv("RDS_USER", "postgres").strip() or "postgres",
        password=os.environ["RDS_PASSWORD"],
        sslmode="require",
        connect_timeout=10,
    )


def _like_pattern(query: str) -> str:
    escaped = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"
