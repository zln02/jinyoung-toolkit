"""shared.visitor_stats — 익명 접속/활동 집계.

개인정보(IP·식별자)는 저장하지 않는다. 세션 단위 접속 수와 활동(분석/크롤 실행)
횟수만 경량 SQLite에 누적해 집계 수치를 제공한다. 동시 세션을 고려해 락으로 보호한다.
"""

from __future__ import annotations

import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

from shared.config import get_settings
from shared.logger import get_logger

logger = get_logger(__name__)

_LOCK = threading.Lock()
_KST = timezone(timedelta(hours=9))


def _db_path() -> Path:
    base = get_settings().output_dir
    base.mkdir(parents=True, exist_ok=True)
    return base / "visitor_stats.db"


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(str(_db_path()), timeout=5)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS events ("
        "  id INTEGER PRIMARY KEY AUTOINCREMENT,"
        "  kind TEXT NOT NULL,"      # 'visit' | 'activity'
        "  action TEXT,"            # 활동 종류 (예: '리뷰 분석')
        "  day TEXT NOT NULL,"      # KST YYYY-MM-DD
        "  ts TEXT NOT NULL"        # ISO timestamp (KST)
        ")"
    )
    return conn


def _record(kind: str, action: str | None = None) -> None:
    now = datetime.now(_KST)
    try:
        with _LOCK, _connect() as conn:
            conn.execute(
                "INSERT INTO events(kind, action, day, ts) VALUES(?,?,?,?)",
                (kind, action, now.strftime("%Y-%m-%d"), now.isoformat()),
            )
    except Exception as exc:  # 집계 실패가 앱을 막지 않도록 best-effort
        logger.warning("방문 집계 기록 실패(%s): %s", kind, exc)


def record_visit() -> None:
    """신규 세션 접속 1건 기록(호출 측에서 세션당 1회 보장)."""
    _record("visit")


def record_activity(action: str = "분석") -> None:
    """활동(분석·크롤 실행) 1건 기록."""
    _record("activity", action)


def get_stats() -> dict[str, int]:
    """누적/오늘 접속·활동 집계. 실패 시 0으로 채워 반환."""
    today = datetime.now(_KST).strftime("%Y-%m-%d")
    stats = {
        "total_visits": 0,
        "today_visits": 0,
        "total_activities": 0,
        "today_activities": 0,
    }
    try:
        with _LOCK, _connect() as conn:
            cur = conn.cursor()
            stats["total_visits"] = cur.execute(
                "SELECT COUNT(*) FROM events WHERE kind='visit'"
            ).fetchone()[0]
            stats["today_visits"] = cur.execute(
                "SELECT COUNT(*) FROM events WHERE kind='visit' AND day=?", (today,)
            ).fetchone()[0]
            stats["total_activities"] = cur.execute(
                "SELECT COUNT(*) FROM events WHERE kind='activity'"
            ).fetchone()[0]
            stats["today_activities"] = cur.execute(
                "SELECT COUNT(*) FROM events WHERE kind='activity' AND day=?", (today,)
            ).fetchone()[0]
    except Exception as exc:
        logger.warning("방문 집계 조회 실패: %s", exc)
    return stats


def get_recent_activities(limit: int = 5) -> list[tuple[str, str]]:
    """최근 활동 (action, 'HH:MM') 목록. 실패 시 빈 리스트."""
    try:
        with _LOCK, _connect() as conn:
            rows = conn.execute(
                "SELECT action, ts FROM events WHERE kind='activity' "
                "ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        out: list[tuple[str, str]] = []
        for action, ts in rows:
            hhmm = ts[11:16] if isinstance(ts, str) and len(ts) >= 16 else ""
            out.append((action or "분석", hhmm))
        return out
    except Exception:
        return []
