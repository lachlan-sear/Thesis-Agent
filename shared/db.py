"""
SQLite persistence layer.
Tracks seen companies, signals, evaluations, and run history.
"""

import sqlite3
import json
from pathlib import Path
from datetime import datetime
from typing import Optional


DB_PATH = Path(__file__).parent.parent / "data" / "thesis_radar.db"


def get_connection() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """Create tables if they don't exist."""
    conn = get_connection()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS seen_companies (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            url TEXT,
            source TEXT,
            first_seen TEXT NOT NULL,
            last_seen TEXT NOT NULL,
            composite_score REAL,
            action TEXT,
            UNIQUE(name COLLATE NOCASE)
        );

        CREATE TABLE IF NOT EXISTS evaluations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            company_name TEXT NOT NULL,
            evaluation_json TEXT NOT NULL,
            evaluated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS signals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            type TEXT NOT NULL,
            source TEXT,
            company TEXT,
            vertical TEXT,
            summary TEXT NOT NULL,
            thesis_implication TEXT,
            urgency TEXT DEFAULT 'normal',
            detected_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS run_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            agent TEXT NOT NULL,
            started_at TEXT NOT NULL,
            completed_at TEXT,
            raw_count INTEGER DEFAULT 0,
            passed_count INTEGER DEFAULT 0,
            output_path TEXT,
            status TEXT DEFAULT 'running'
        );
    """)
    conn.commit()
    conn.close()


def is_seen(company_name: str) -> bool:
    """Check if we've already evaluated this company."""
    conn = get_connection()
    row = conn.execute(
        "SELECT 1 FROM seen_companies WHERE name = ? COLLATE NOCASE",
        (company_name,),
    ).fetchone()
    conn.close()
    return row is not None


def mark_seen(
    company_name: str,
    url: Optional[str] = None,
    source: str = "",
    composite_score: Optional[float] = None,
    action: str = "skip",
):
    """Record that we've seen and evaluated this company."""
    conn = get_connection()
    now = datetime.utcnow().isoformat()
    conn.execute(
        """INSERT INTO seen_companies (name, url, source, first_seen, last_seen, composite_score, action)
           VALUES (?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(name) DO UPDATE SET
               last_seen = excluded.last_seen,
               composite_score = COALESCE(excluded.composite_score, composite_score),
               action = excluded.action
        """,
        (company_name, url, source, now, now, composite_score, action),
    )
    conn.commit()
    conn.close()


def save_evaluation(company_name: str, evaluation_dict: dict):
    """Store a full evaluation for audit trail."""
    conn = get_connection()
    conn.execute(
        "INSERT INTO evaluations (company_name, evaluation_json, evaluated_at) VALUES (?, ?, ?)",
        (company_name, json.dumps(evaluation_dict), datetime.utcnow().isoformat()),
    )
    conn.commit()
    conn.close()


def save_signal(signal_dict: dict):
    """Store a market signal."""
    conn = get_connection()
    conn.execute(
        """INSERT INTO signals (type, source, company, vertical, summary, thesis_implication, urgency, detected_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            signal_dict.get("type", ""),
            signal_dict.get("source", ""),
            signal_dict.get("company"),
            signal_dict.get("vertical", ""),
            signal_dict.get("summary", ""),
            signal_dict.get("thesis_implication"),
            signal_dict.get("urgency", "normal"),
            datetime.utcnow().isoformat(),
        ),
    )
    conn.commit()
    conn.close()


def log_run(agent: str, raw_count: int = 0, passed_count: int = 0, output_path: str = ""):
    """Log a completed agent run."""
    conn = get_connection()
    now = datetime.utcnow().isoformat()
    conn.execute(
        """INSERT INTO run_history (agent, started_at, completed_at, raw_count, passed_count, output_path, status)
           VALUES (?, ?, ?, ?, ?, ?, 'completed')""",
        (agent, now, now, raw_count, passed_count, output_path),
    )
    conn.commit()
    conn.close()


def get_recent_signals(days: int = 7, signal_type: Optional[str] = None) -> list[dict]:
    """Retrieve recent signals for cross-referencing."""
    conn = get_connection()
    query = "SELECT * FROM signals WHERE detected_at > datetime('now', ?)"
    params = [f"-{days} days"]

    if signal_type:
        query += " AND type = ?"
        params.append(signal_type)

    query += " ORDER BY detected_at DESC"
    rows = conn.execute(query, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_all_seen(action_filter: Optional[str] = None) -> list[dict]:
    """Get all seen companies, optionally filtered by action."""
    conn = get_connection()
    if action_filter:
        rows = conn.execute(
            "SELECT * FROM seen_companies WHERE action = ? ORDER BY last_seen DESC",
            (action_filter,),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM seen_companies ORDER BY last_seen DESC"
        ).fetchall()
    conn.close()
    return [dict(r) for r in rows]
