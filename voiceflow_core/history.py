"""Durable, thread-safe transcript history for VoiceFlow.

The desktop app performs recording, transcription, and paste work on background
threads.  Each database operation therefore opens its own SQLite connection
instead of sharing a connection across threads.
"""

from __future__ import annotations

import json
import os
import sqlite3
import uuid
import wave
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Optional


class DictationStatus(str, Enum):
    CREATED = "created"
    LISTENING = "listening"
    TRANSCRIBING = "transcribing"
    POLISHING = "polishing"
    PASTING = "pasting"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


_ALLOWED_TRANSITIONS = {
    DictationStatus.CREATED: {DictationStatus.LISTENING, DictationStatus.TRANSCRIBING, DictationStatus.FAILED, DictationStatus.CANCELLED},
    DictationStatus.LISTENING: {DictationStatus.TRANSCRIBING, DictationStatus.FAILED, DictationStatus.CANCELLED},
    DictationStatus.TRANSCRIBING: {DictationStatus.POLISHING, DictationStatus.PASTING, DictationStatus.COMPLETED, DictationStatus.FAILED},
    DictationStatus.POLISHING: {DictationStatus.PASTING, DictationStatus.COMPLETED, DictationStatus.FAILED},
    DictationStatus.PASTING: {DictationStatus.COMPLETED, DictationStatus.FAILED},
    DictationStatus.COMPLETED: set(),
    DictationStatus.FAILED: {DictationStatus.TRANSCRIBING},
    DictationStatus.CANCELLED: set(),
}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def default_database_path() -> Path:
    data_root = os.environ.get("VOICEFLOW_DATA_DIR")
    if data_root:
        return Path(data_root).expanduser() / "voiceflow.db"
    return Path.home() / ".voiceflow" / "voiceflow.db"


class DictationHistory:
    """SQLite-backed record of dictation jobs and their recoverable text."""

    def __init__(self, database_path: Optional[os.PathLike[str] | str] = None):
        self.database_path = Path(database_path) if database_path else default_database_path()
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self.recovery_directory = self.database_path.parent / "recovery"
        self._migrate()
        self.recover_interrupted()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(str(self.database_path), timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA busy_timeout = 10000")
        return connection

    @contextmanager
    def _connection(self):
        connection = self._connect()
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def _migrate(self) -> None:
        with self._connection() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    version INTEGER PRIMARY KEY,
                    applied_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS dictations (
                    id TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    mode TEXT NOT NULL,
                    status TEXT NOT NULL,
                    raw_text TEXT NOT NULL DEFAULT '',
                    final_text TEXT NOT NULL DEFAULT '',
                    language TEXT,
                    transcription_engine TEXT,
                    duration_ms INTEGER NOT NULL DEFAULT 0,
                    error_code TEXT,
                    error_message TEXT,
                    audio_path TEXT,
                    metadata_json TEXT NOT NULL DEFAULT '{}'
                );

                CREATE INDEX IF NOT EXISTS idx_dictations_created_at
                    ON dictations(created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_dictations_status
                    ON dictations(status);
                """
            )
            connection.execute(
                "INSERT OR IGNORE INTO schema_migrations(version, applied_at) VALUES(1, ?)",
                (_utc_now(),),
            )
            columns = {row[1] for row in connection.execute("PRAGMA table_info(dictations)").fetchall()}
            if "audio_path" not in columns:
                connection.execute("ALTER TABLE dictations ADD COLUMN audio_path TEXT")
            connection.execute(
                "INSERT OR IGNORE INTO schema_migrations(version, applied_at) VALUES(2, ?)",
                (_utc_now(),),
            )

    @staticmethod
    def _as_status(value: DictationStatus | str) -> DictationStatus:
        return value if isinstance(value, DictationStatus) else DictationStatus(value)

    @staticmethod
    def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
        item = dict(row)
        try:
            item["metadata"] = json.loads(item.pop("metadata_json") or "{}")
        except (TypeError, json.JSONDecodeError):
            item["metadata"] = {}
            item.pop("metadata_json", None)
        return item

    def create(
        self,
        *,
        mode: str = "dictation",
        status: DictationStatus | str = DictationStatus.CREATED,
        language: Optional[str] = None,
        transcription_engine: Optional[str] = None,
        metadata: Optional[dict[str, Any]] = None,
    ) -> str:
        job_id = str(uuid.uuid4())
        now = _utc_now()
        status_value = self._as_status(status).value
        with self._connection() as connection:
            connection.execute(
                """
                INSERT INTO dictations(
                    id, created_at, updated_at, mode, status, language,
                    transcription_engine, metadata_json
                ) VALUES(?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    job_id,
                    now,
                    now,
                    mode,
                    status_value,
                    language,
                    transcription_engine,
                    json.dumps(metadata or {}, ensure_ascii=False),
                ),
            )
        return job_id

    def transition(self, job_id: str, status: DictationStatus | str, **fields: Any) -> dict[str, Any]:
        next_status = self._as_status(status)
        current = self.get(job_id)
        if not current:
            raise KeyError(f"Unknown dictation job: {job_id}")

        current_status = self._as_status(current["status"])
        if next_status != current_status and next_status not in _ALLOWED_TRANSITIONS[current_status]:
            raise ValueError(f"Invalid dictation transition: {current_status.value} -> {next_status.value}")

        allowed_fields = {
            "raw_text",
            "final_text",
            "language",
            "transcription_engine",
            "duration_ms",
            "error_code",
            "error_message",
            "audio_path",
        }
        unknown = set(fields) - allowed_fields - {"metadata"}
        if unknown:
            raise ValueError(f"Unsupported dictation fields: {', '.join(sorted(unknown))}")

        assignments = ["status = ?", "updated_at = ?"]
        values: list[Any] = [next_status.value, _utc_now()]
        for key, value in fields.items():
            column = "metadata_json" if key == "metadata" else key
            assignments.append(f"{column} = ?")
            values.append(json.dumps(value or {}, ensure_ascii=False) if key == "metadata" else value)
        values.append(job_id)

        with self._connection() as connection:
            connection.execute(
                f"UPDATE dictations SET {', '.join(assignments)} WHERE id = ?",
                values,
            )
        return self.get(job_id)  # type: ignore[return-value]

    def complete(self, job_id: str, final_text: str, **fields: Any) -> dict[str, Any]:
        return self.transition(job_id, DictationStatus.COMPLETED, final_text=final_text, **fields)

    def fail(self, job_id: str, message: str, code: str = "processing_failed", **fields: Any) -> dict[str, Any]:
        return self.transition(
            job_id,
            DictationStatus.FAILED,
            error_code=code,
            error_message=message,
            **fields,
        )

    def get(self, job_id: str) -> Optional[dict[str, Any]]:
        with self._connection() as connection:
            row = connection.execute("SELECT * FROM dictations WHERE id = ?", (job_id,)).fetchone()
        return self._row_to_dict(row) if row else None

    def list(self, *, limit: int = 100, offset: int = 0, query: str = "") -> list[dict[str, Any]]:
        limit = max(1, min(int(limit), 500))
        offset = max(0, int(offset))
        sql = "SELECT * FROM dictations"
        values: list[Any] = []
        if query.strip():
            sql += " WHERE raw_text LIKE ? OR final_text LIKE ?"
            needle = f"%{query.strip()}%"
            values.extend([needle, needle])
        sql += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
        values.extend([limit, offset])
        with self._connection() as connection:
            rows = connection.execute(sql, values).fetchall()
        return [self._row_to_dict(row) for row in rows]

    def latest(self) -> Optional[dict[str, Any]]:
        with self._connection() as connection:
            row = connection.execute(
                """
                SELECT * FROM dictations
                WHERE final_text != '' OR raw_text != ''
                ORDER BY created_at DESC LIMIT 1
                """
            ).fetchone()
        return self._row_to_dict(row) if row else None

    def delete(self, job_id: str) -> bool:
        with self._connection() as connection:
            cursor = connection.execute("DELETE FROM dictations WHERE id = ?", (job_id,))
        return cursor.rowcount > 0

    def clear(self) -> int:
        with self._connection() as connection:
            audio_paths = [row[0] for row in connection.execute(
                "SELECT audio_path FROM dictations WHERE audio_path IS NOT NULL AND audio_path != ''"
            ).fetchall()]
            cursor = connection.execute("DELETE FROM dictations")
        for audio_path in audio_paths:
            self.discard_recovery_audio(audio_path)
        return cursor.rowcount

    def purge_older_than(self, days: int) -> int:
        if days <= 0:
            return 0
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat(timespec="milliseconds")
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT id, audio_path FROM dictations WHERE created_at < ?",
                (cutoff,),
            ).fetchall()
            if rows:
                connection.executemany("DELETE FROM dictations WHERE id = ?", ((row[0],) for row in rows))
        for row in rows:
            self.discard_recovery_audio(row[1])
        return len(rows)

    def analytics(self) -> dict[str, int]:
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT final_text, raw_text FROM dictations WHERE status = ?",
                (DictationStatus.COMPLETED.value,),
            ).fetchall()
        return {
            "total_words": sum(len((row["final_text"] or row["raw_text"] or "").split()) for row in rows),
            "sessions": len(rows),
        }

    def recover_interrupted(self) -> int:
        """Mark jobs left mid-pipeline by a crash as recoverable failures."""
        nonterminal = tuple(
            status.value
            for status in DictationStatus
            if status not in {DictationStatus.COMPLETED, DictationStatus.FAILED, DictationStatus.CANCELLED}
        )
        placeholders = ",".join("?" for _ in nonterminal)
        with self._connection() as connection:
            cursor = connection.execute(
                f"""
                UPDATE dictations
                SET status = ?, updated_at = ?, error_code = ?, error_message = ?
                WHERE status IN ({placeholders})
                """,
                (
                    DictationStatus.FAILED.value,
                    _utc_now(),
                    "interrupted",
                    "VoiceFlow closed before this dictation finished. Retry is available when audio was recovered.",
                    *nonterminal,
                ),
            )
        return cursor.rowcount

    def save_recovery_audio(self, job_id: str, raw_audio: bytes, sample_rate: int) -> str:
        self.recovery_directory.mkdir(parents=True, exist_ok=True)
        destination = self.recovery_directory / f"{job_id}.wav"
        temporary = self.recovery_directory / f"{job_id}.tmp"
        with wave.open(str(temporary), "wb") as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(sample_rate)
            wav_file.writeframes(raw_audio)
        os.replace(temporary, destination)
        return str(destination)

    @staticmethod
    def discard_recovery_audio(path: Optional[str]) -> None:
        if not path:
            return
        try:
            Path(path).unlink(missing_ok=True)
        except OSError:
            pass
