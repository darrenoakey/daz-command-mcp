#!/usr/bin/env python3
"""
Session management functionality for DAZ Command MCP Server
"""

from __future__ import annotations

import shutil
import sys
import time
from pathlib import Path
from typing import Any, Dict, List

from .models import SESSIONS_DIR, Event
from .utils import (
    ensure_sessions_dir, get_session_dir, sanitize_session_name,
    load_session_summary, save_session_summary, append_event_to_log,
    append_error_to_log, get_active_session_name, set_active_session_name
)
from .summary_worker import enqueue_summary
from .history_manager import add_history_entry


def create_session_metadata(session_name: str) -> Dict[str, Any]:
    """Create session metadata dict for public view"""
    session_dir = get_session_dir(session_name)
    
    # Count events by counting lines in event_log.jsonl
    events_count = 0
    log_path = session_dir / "event_log.jsonl"
    if log_path.exists():
        try:
            with log_path.open("r", encoding="utf-8") as f:
                events_count = sum(1 for _ in f)
        except Exception:
            events_count = 0
    
    # Get creation and modification times
    created_at = session_dir.stat().st_ctime if session_dir.exists() else time.time()
    updated_at = session_dir.stat().st_mtime if session_dir.exists() else time.time()
    
    # Get current directory from summary if available
    summary = load_session_summary(session_name)
    current_directory = str(Path.cwd())  # Default fallback
    
    return {
        "id": sanitize_session_name(session_name),  # For compatibility
        "name": session_name,
        "description": "",  # Will be extracted from summary if needed
        "summary": summary[:200] + "..." if len(summary) > 200 else summary,  # Truncated for listing
        "progress": "",  # Not used in new structure
        "current_directory": current_directory,
        "events_count": events_count,
        "created_at": created_at,
        "updated_at": updated_at,
        "is_active": get_active_session_name() == session_name
    }


def create_session_record(name: str, description: str) -> Dict[str, Any]:
    """Creates a new session directory and initializes it."""
    ensure_sessions_dir()
    session_dir = get_session_dir(name)
    
    if session_dir.exists():
        raise ValueError(f"Session '{name}' already exists")
    
    session_dir.mkdir(parents=True, exist_ok=True)
    
    # Initialize summary with the description (the "why")
    initial_summary = f"Session Purpose: {description}\n\nStarted at: {Path.cwd()}\n\nSession Log:\n"
    save_session_summary(name, initial_summary)
    
    return create_session_metadata(name)


def rename_session(old_name: str, new_name: str) -> Dict[str, Any]:
    """Rename a session directory and update active session if needed."""
    ensure_sessions_dir()
    
    old_session_dir = get_session_dir(old_name)
    new_session_dir = get_session_dir(new_name)
    
    if not old_session_dir.exists():
        raise ValueError(f"Session '{old_name}' does not exist")
    
    if new_session_dir.exists():
        raise ValueError(f"Session '{new_name}' already exists")
    
    # Rename the directory
    old_session_dir.rename(new_session_dir)
    
    # If this was the active session, update the active session name
    if get_active_session_name() == old_name:
        set_active_session_name(new_name)
    
    return create_session_metadata(new_name)


def delete_session(session_name: str) -> Dict[str, Any]:
    """Move a session to deleted_sessions directory."""
    ensure_sessions_dir()
    
    session_dir = get_session_dir(session_name)
    
    if not session_dir.exists():
        raise ValueError(f"Session '{session_name}' does not exist")
    
    # Create deleted_sessions directory next to sessions directory
    deleted_sessions_dir = SESSIONS_DIR.parent / "deleted_sessions"
    deleted_sessions_dir.mkdir(parents=True, exist_ok=True)
    
    # Create target directory in deleted_sessions
    # Add timestamp to avoid conflicts if same session name deleted multiple times
    timestamp = int(time.time())
    target_dir = deleted_sessions_dir / f"{sanitize_session_name(session_name)}_{timestamp}"
    
    # Move the session directory
    shutil.move(str(session_dir), str(target_dir))
    
    # If this was the active session, clear the active session
    if get_active_session_name() == session_name:
        set_active_session_name(None)
    
    return {
        "success": True,
        "message": f"Session '{session_name}' moved to deleted_sessions",
        "deleted_session_name": session_name,
        "deleted_location": str(target_dir),
        "was_active": get_active_session_name() is None  # If we cleared it, it was active
    }


def list_session_views() -> List[Dict[str, Any]]:
    """Lists all sessions by looking at directory names only."""
    ensure_sessions_dir()
    out: List[Dict[str, Any]] = []
    
    # Only list directories, not files
    for item in sorted(SESSIONS_DIR.iterdir()):
        if item.is_dir():
            try:
                out.append(create_session_metadata(item.name))
            except Exception as e:
                print(f"[mcp] skipping session dir {item.name}: {e}", file=sys.stderr)
    
    return out


def append_event(session_name: str, event: Event) -> Dict[str, Any]:
    """Appends an event, adds to history (sync), and triggers async summary update."""
    try:
        # Get old summary before appending event
        old_summary = load_session_summary(session_name)
        
        # Append event to log
        append_event_to_log(session_name, event)
        
        # Add to history synchronously with debugging
        try:
            print(f"[DEBUG] Adding history entry for session: {session_name}", file=sys.stderr)
            add_history_entry(session_name, event)
            print(f"[DEBUG] History entry added successfully", file=sys.stderr)
        except Exception as history_error:
            print(f"[ERROR] Failed to add history entry: {history_error}", file=sys.stderr)
            import traceback
            traceback.print_exc(file=sys.stderr)
        
        # Trigger async summary update (keep existing summary system)
        enqueue_summary(session_name, old_summary, event)
        
        return create_session_metadata(session_name)
    
    except Exception as e:
        error_record = {
            "timestamp": time.time(),
            "type": "append_event_error",
            "error": str(e),
            "event": event
        }
        append_error_to_log(session_name, error_record)
        raise
