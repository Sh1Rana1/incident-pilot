"""V12.1.1 本地持久化：Checkpoint、会话、补丁提案与事故记忆。"""

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal
from uuid import uuid4

from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.checkpoint.sqlite import SqliteSaver
from pydantic import Field

from memory import rank_memories
from models import (
    AgentRunResult,
    HumanReviewRequest,
    IncidentMemory,
    IncidentMemoryMatch,
    MemoryStatus,
    StrictModel,
)


ROOT = Path(__file__).resolve().parent
DEFAULT_STATE_DIR = ROOT / ".incident_state"
DEFAULT_DATABASE_PATH = DEFAULT_STATE_DIR / "incident_pilot.sqlite3"

SessionStatus = Literal[
    "running",
    "waiting_for_runtime_approval",
    "waiting_for_patch_approval",
    "waiting_for_human_review",
    "completed",
    "cancelled",
    "failed",
]


class SessionRecord(StrictModel):
    thread_id: str
    question: str
    status: SessionStatus
    tool_profile: str
    runtime_tools_enabled: bool
    created_at: str
    updated_at: str
    compute_duration_ms: float = 0.0
    pending_review: HumanReviewRequest | None = None
    result: AgentRunResult | None = None
    last_error: str | None = None
    recalled_memory_ids: list[str] = Field(default_factory=list)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class SessionStore:
    """共享一个 SQLite 连接，保存图 Checkpoint 和用户可查询的会话索引。"""

    def __init__(self, database_path: Path = DEFAULT_DATABASE_PATH):
        self.database_path = database_path.resolve()
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(
            self.database_path,
            check_same_thread=False,
        )
        self.connection.row_factory = sqlite3.Row
        # 不启用 pickle；MsgPack 只允许 LangGraph 内置安全类型。数据库若被
        # 外部篡改，反序列化器不会任意导入并实例化 Python 类。
        serializer = JsonPlusSerializer(
            pickle_fallback=False,
            allowed_msgpack_modules=None,
        )
        self.checkpointer = SqliteSaver(self.connection, serde=serializer)
        self.checkpointer.setup()
        self._setup_sessions()
        self._setup_memories()

    def _setup_sessions(self) -> None:
        with self.connection:
            self.connection.execute(
                """
                CREATE TABLE IF NOT EXISTS incident_sessions (
                    thread_id TEXT PRIMARY KEY,
                    question TEXT NOT NULL,
                    status TEXT NOT NULL,
                    tool_profile TEXT NOT NULL,
                    runtime_tools_enabled INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    compute_duration_ms REAL NOT NULL DEFAULT 0,
                    pending_review_json TEXT,
                    result_json TEXT,
                    last_error TEXT
                )
                """
            )
            self.connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_incident_sessions_updated "
                "ON incident_sessions(updated_at DESC)"
            )
            columns = {
                row["name"]
                for row in self.connection.execute(
                    "PRAGMA table_info(incident_sessions)"
                ).fetchall()
            }
            if "recalled_memory_ids_json" not in columns:
                self.connection.execute(
                    "ALTER TABLE incident_sessions "
                    "ADD COLUMN recalled_memory_ids_json TEXT NOT NULL DEFAULT '[]'"
                )

    def _setup_memories(self) -> None:
        with self.connection:
            self.connection.execute(
                """
                CREATE TABLE IF NOT EXISTS incident_memories (
                    memory_id TEXT PRIMARY KEY,
                    source_thread_id TEXT NOT NULL UNIQUE,
                    status TEXT NOT NULL,
                    exception_types_json TEXT NOT NULL,
                    symbols_json TEXT NOT NULL,
                    files_json TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    root_cause TEXT NOT NULL,
                    resolution_json TEXT NOT NULL,
                    source_confidence TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    approved_at TEXT
                )
                """
            )
            self.connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_incident_memories_status_updated "
                "ON incident_memories(status, updated_at DESC)"
            )

    def close(self) -> None:
        self.connection.close()

    def __enter__(self) -> "SessionStore":
        return self

    def __exit__(self, _exc_type, _exc, _traceback) -> None:
        self.close()

    def create(
        self,
        thread_id: str,
        question: str,
        tool_profile: str,
        runtime_tools_enabled: bool,
        recalled_memory_ids: list[str] | None = None,
    ) -> SessionRecord:
        timestamp = _now()
        try:
            with self.connection:
                self.connection.execute(
                    """
                    INSERT INTO incident_sessions (
                        thread_id, question, status, tool_profile,
                        runtime_tools_enabled, created_at, updated_at,
                        recalled_memory_ids_json
                    ) VALUES (?, ?, 'running', ?, ?, ?, ?, ?)
                    """,
                    (
                        thread_id,
                        question,
                        tool_profile,
                        int(runtime_tools_enabled),
                        timestamp,
                        timestamp,
                        json.dumps(recalled_memory_ids or [], ensure_ascii=False),
                    ),
                )
        except sqlite3.IntegrityError as exc:
            raise ValueError(f"Thread ID 已存在: {thread_id}") from exc
        return self.get(thread_id)

    def get(self, thread_id: str) -> SessionRecord:
        row = self.connection.execute(
            "SELECT * FROM incident_sessions WHERE thread_id = ?",
            (thread_id,),
        ).fetchone()
        if row is None:
            raise ValueError(f"找不到调查会话: {thread_id}")
        return self._record(row)

    def list(self, limit: int = 20) -> list[SessionRecord]:
        rows = self.connection.execute(
            "SELECT * FROM incident_sessions ORDER BY updated_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [self._record(row) for row in rows]

    def add_compute_duration(self, thread_id: str, duration_ms: float) -> None:
        with self.connection:
            self.connection.execute(
                """
                UPDATE incident_sessions
                SET compute_duration_ms = compute_duration_ms + ?, updated_at = ?
                WHERE thread_id = ?
                """,
                (round(duration_ms, 2), _now(), thread_id),
            )

    def mark_waiting(
        self,
        thread_id: str,
        request: HumanReviewRequest,
    ) -> SessionRecord:
        if request.reason == "runtime_execution":
            status: SessionStatus = "waiting_for_runtime_approval"
        elif request.reason == "patch_verification":
            status = "waiting_for_patch_approval"
        else:
            status = "waiting_for_human_review"
        with self.connection:
            self.connection.execute(
                """
                UPDATE incident_sessions
                SET status = ?, pending_review_json = ?, last_error = NULL,
                    updated_at = ?
                WHERE thread_id = ?
                """,
                (status, request.model_dump_json(), _now(), thread_id),
            )
        return self.get(thread_id)

    def mark_completed(
        self,
        thread_id: str,
        result: AgentRunResult,
    ) -> SessionRecord:
        status: SessionStatus = (
            "cancelled" if result.metrics.stop_reason == "cancelled" else "completed"
        )
        with self.connection:
            self.connection.execute(
                """
                UPDATE incident_sessions
                SET status = ?, pending_review_json = NULL, result_json = ?,
                    last_error = NULL, updated_at = ?
                WHERE thread_id = ?
                """,
                (status, result.model_dump_json(), _now(), thread_id),
            )
        return self.get(thread_id)

    def mark_failed(self, thread_id: str, error: str) -> SessionRecord:
        with self.connection:
            self.connection.execute(
                """
                UPDATE incident_sessions
                SET status = 'failed', pending_review_json = NULL,
                    last_error = ?, updated_at = ?
                WHERE thread_id = ?
                """,
                (error[:2000], _now(), thread_id),
            )
        return self.get(thread_id)

    def create_memory_candidate(
        self,
        source_thread_id: str,
        fields: dict,
    ) -> IncidentMemory:
        """每次调查最多产生一条待审批记忆，重试不会重复插入。"""
        existing = self.connection.execute(
            "SELECT * FROM incident_memories WHERE source_thread_id = ?",
            (source_thread_id,),
        ).fetchone()
        if existing is not None:
            return self._memory(existing)
        timestamp = _now()
        memory_id = f"mem-{uuid4().hex[:12]}"
        with self.connection:
            self.connection.execute(
                """
                INSERT INTO incident_memories (
                    memory_id, source_thread_id, status,
                    exception_types_json, symbols_json, files_json,
                    summary, root_cause, resolution_json, source_confidence,
                    created_at, updated_at
                ) VALUES (?, ?, 'pending', ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    memory_id,
                    source_thread_id,
                    json.dumps(fields["exception_types"], ensure_ascii=False),
                    json.dumps(fields["symbols"], ensure_ascii=False),
                    json.dumps(fields["files"], ensure_ascii=False),
                    fields["summary"],
                    fields["root_cause"],
                    json.dumps(fields["resolution"], ensure_ascii=False),
                    fields["source_confidence"],
                    timestamp,
                    timestamp,
                ),
            )
        return self.get_memory(memory_id)

    def get_memory(self, memory_id: str) -> IncidentMemory:
        row = self.connection.execute(
            "SELECT * FROM incident_memories WHERE memory_id = ?",
            (memory_id,),
        ).fetchone()
        if row is None:
            raise ValueError(f"找不到事故记忆: {memory_id}")
        return self._memory(row)

    def get_memory_for_thread(self, thread_id: str) -> IncidentMemory | None:
        row = self.connection.execute(
            "SELECT * FROM incident_memories WHERE source_thread_id = ?",
            (thread_id,),
        ).fetchone()
        return self._memory(row) if row is not None else None

    def list_memories(
        self,
        status: MemoryStatus | None = None,
        limit: int = 50,
    ) -> list[IncidentMemory]:
        if limit < 1:
            raise ValueError("limit 必须大于等于 1")
        if status is None:
            rows = self.connection.execute(
                "SELECT * FROM incident_memories ORDER BY updated_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        else:
            rows = self.connection.execute(
                "SELECT * FROM incident_memories WHERE status = ? "
                "ORDER BY updated_at DESC LIMIT ?",
                (status, limit),
            ).fetchall()
        return [self._memory(row) for row in rows]

    def set_memory_status(
        self,
        memory_id: str,
        status: MemoryStatus,
    ) -> IncidentMemory:
        if status not in {"pending", "approved", "rejected"}:
            raise ValueError(f"不支持的 Memory 状态: {status}")
        self.get_memory(memory_id)
        timestamp = _now()
        with self.connection:
            self.connection.execute(
                """
                UPDATE incident_memories
                SET status = ?, updated_at = ?, approved_at = ?
                WHERE memory_id = ?
                """,
                (
                    status,
                    timestamp,
                    timestamp if status == "approved" else None,
                    memory_id,
                ),
            )
        return self.get_memory(memory_id)

    def delete_memory(self, memory_id: str) -> None:
        self.get_memory(memory_id)
        with self.connection:
            self.connection.execute(
                "DELETE FROM incident_memories WHERE memory_id = ?",
                (memory_id,),
            )

    def recall_memories(
        self,
        query: str,
        limit: int = 3,
    ) -> list[IncidentMemoryMatch]:
        # 数据量较小时用本地可解释词法排序，不为召回额外调用模型。
        approved = self.list_memories(status="approved", limit=500)
        return rank_memories(query, approved, limit=limit)

    @staticmethod
    def _record(row: sqlite3.Row) -> SessionRecord:
        pending = (
            HumanReviewRequest.model_validate_json(row["pending_review_json"])
            if row["pending_review_json"]
            else None
        )
        result = (
            AgentRunResult.model_validate_json(row["result_json"])
            if row["result_json"]
            else None
        )
        return SessionRecord(
            thread_id=row["thread_id"],
            question=row["question"],
            status=row["status"],
            tool_profile=row["tool_profile"],
            runtime_tools_enabled=bool(row["runtime_tools_enabled"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            compute_duration_ms=float(row["compute_duration_ms"]),
            pending_review=pending,
            result=result,
            last_error=row["last_error"],
            recalled_memory_ids=json.loads(row["recalled_memory_ids_json"] or "[]"),
        )

    @staticmethod
    def _memory(row: sqlite3.Row) -> IncidentMemory:
        return IncidentMemory(
            memory_id=row["memory_id"],
            source_thread_id=row["source_thread_id"],
            status=row["status"],
            exception_types=json.loads(row["exception_types_json"]),
            symbols=json.loads(row["symbols_json"]),
            files=json.loads(row["files_json"]),
            summary=row["summary"],
            root_cause=row["root_cause"],
            resolution=json.loads(row["resolution_json"]),
            source_confidence=row["source_confidence"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            approved_at=row["approved_at"],
        )
