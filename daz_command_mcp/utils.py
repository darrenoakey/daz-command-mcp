#!/usr/bin/env python3
"""
Utility functions for DAZ Command MCP Server
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Any, Dict, Optional

from .models import SESSIONS_DIR, _active_session_name_lock, _active_session_name


# --- Path and Session Utilities ---
def ensure_sessions_dir() -> None:
    """Ensures the sessions directory exists."""
    SESSIONS_DIR.mkdir(parents=True, exist_ok=True)


def sanitize_session_name(name: str) -> str:
    """Convert session name to valid directory name"""
    # Replace invalid characters with underscores
    sanitized = "".join(c if c.isalnum() or c in "-_." else "_" for c in name)
    # Ensure it doesn't start with a dot
    if sanitized.startswith("."):
        sanitized = "_" + sanitized[1:]
    # Limit length
    return sanitized[:100]


def get_session_dir(session_name: str) -> Path:
    """Get session directory path from name"""
    return SESSIONS_DIR / sanitize_session_name(session_name)


def session_exists(session_name: str) -> bool:
    """Check if session exists"""
    return get_session_dir(session_name).exists()


# --- Session File Operations ---
def load_session_summary(session_name: str) -> str:
    """Load session summary; returns summary text or empty string"""
    summary_path = get_session_dir(session_name) / "summary.txt"
    if summary_path.exists():
        return summary_path.read_text(encoding="utf-8").strip()
    return ""


def save_session_summary(session_name: str, summary: str) -> None:
    """Save session summary"""
    session_dir = get_session_dir(session_name)
    session_dir.mkdir(parents=True, exist_ok=True)
    summary_path = session_dir / "summary.txt"
    summary_path.write_text(summary, encoding="utf-8")


def append_event_to_log(session_name: str, event: Dict[str, Any]) -> None:
    """Append event to event log (JSONL format)"""
    session_dir = get_session_dir(session_name)
    session_dir.mkdir(parents=True, exist_ok=True)
    log_path = session_dir / "event_log.json"
    
    # Append as JSON line
    with log_path.open("a", encoding="utf-8") as f:
        json.dump(event, f, ensure_ascii=False)
        f.write("\n")


def append_error_to_log(session_name: str, error: Dict[str, Any]) -> None:
    """Append error to errors log (JSONL format)"""
    try:
        session_dir = get_session_dir(session_name)
        session_dir.mkdir(parents=True, exist_ok=True)
        errors_path = session_dir / "errors.json"
        
        # Append as JSON line
        with errors_path.open("a", encoding="utf-8") as f:
            json.dump(error, f, ensure_ascii=False)
            f.write("\n")
    except Exception as e:
        # If we can't log the error, at least print it
        print(f"[error-log] failed to log error: {e}", file=sys.stderr)


# --- Active Session Management ---
def get_active_session_name() -> Optional[str]:
    """Returns the currently active session name or None."""
    with _active_session_name_lock:
        return _active_session_name


def set_active_session_name(session_name: Optional[str]) -> None:
    """Sets the currently active session name (or None)."""
    with _active_session_name_lock:
        global _active_session_name
        _active_session_name = session_name


# --- Text Processing ---
def truncate_with_indication(text: str, max_chars: int, from_end: bool = False) -> str:
    """Truncate text with indication if it was truncated"""
    if len(text) <= max_chars:
        return text
    
    if from_end:
        truncated = text[-max_chars:]
        return f"...(abridged from {len(text)} chars)...{truncated}"
    else:
        truncated = text[:max_chars]
        return f"{truncated}...(abridged from {len(text)} chars)..."
