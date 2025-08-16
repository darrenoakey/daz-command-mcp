#!/usr/bin/env python3
"""
Simple History and Instructions management for DAZ Command MCP Server

Manages a history.json file that tracks recent session activities.
Manages an instructions.json file that contains session-specific instructions.
Keeps under 32k characters by removing oldest entries when needed.
Simple synchronous operation - no threads, no caching, just JSON files.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from .models import Event
from .utils import get_session_dir


# Maximum size for history.json in characters
MAX_HISTORY_SIZE = 32 * 1024  # 32k characters


def get_history_path(session_name: str) -> Path:
    """Get the path to the history.json file for a session"""
    session_dir = get_session_dir(session_name)
    return session_dir / "history.json"


def get_instructions_path(session_name: str) -> Path:
    """Get the path to the instructions.json file for a session"""
    session_dir = get_session_dir(session_name)
    return session_dir / "instructions.json"


def load_session_history(session_name: str) -> List[Dict[str, Any]]:
    """Load history from history.json file"""
    history_path = get_history_path(session_name)
    
    if not history_path.exists():
        return []
    
    try:
        with history_path.open("r", encoding="utf-8") as f:
            history_data = json.load(f)
            
        if not isinstance(history_data, list):
            return []
            
        return history_data
        
    except Exception:
        return []


def save_session_history(session_name: str, history: List[Dict[str, Any]]) -> None:
    """Save history to history.json file"""
    session_dir = get_session_dir(session_name)
    session_dir.mkdir(parents=True, exist_ok=True)
    
    history_path = get_history_path(session_name)
    
    with history_path.open("w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)


def load_session_instructions(session_name: str) -> List[str]:
    """Load instructions from instructions.json file"""
    instructions_path = get_instructions_path(session_name)
    
    if not instructions_path.exists():
        return []
    
    try:
        with instructions_path.open("r", encoding="utf-8") as f:
            instructions_data = json.load(f)
            
        if not isinstance(instructions_data, list):
            return []
            
        return instructions_data
        
    except Exception:
        return []


def save_session_instructions(session_name: str, instructions: List[str]) -> None:
    """Save instructions to instructions.json file"""
    session_dir = get_session_dir(session_name)
    session_dir.mkdir(parents=True, exist_ok=True)
    
    instructions_path = get_instructions_path(session_name)
    
    with instructions_path.open("w", encoding="utf-8") as f:
        json.dump(instructions, f, ensure_ascii=False, indent=2)


def add_session_instruction(session_name: str, instruction: str) -> None:
    """Add a new instruction to the session"""
    instructions = load_session_instructions(session_name)
    instructions.append(instruction)
    save_session_instructions(session_name, instructions)


def replace_session_instructions(session_name: str, instructions: List[str]) -> None:
    """Replace all instructions for the session"""
    save_session_instructions(session_name, instructions)


def get_formatted_instructions(session_name: str) -> str:
    """Get formatted instructions for display"""
    try:
        instructions = load_session_instructions(session_name)
        
        if not instructions:
            return "No instructions available."
        
        formatted_instructions = []
        for i, instruction in enumerate(instructions, 1):
            formatted_instructions.append(f"• {instruction}")
        
        return "\n".join(formatted_instructions)
        
    except Exception as e:
        return f"Error loading instructions: {e}"


def record_user_request(session_name: str, user_request: str) -> None:
    """Record a user request in history. Should be called at the start of any multi-step task."""
    # Create a user request entry that looks like a history entry
    entry = {
        "timestamp": time.time(),
        "current_task": user_request,  # The user's request becomes the task
        "summary_of_what_we_just_did": "User provided new request",
        "summary_of_what_we_about_to_do": "Processing user request",
        "event_type": "user_request",
        "success": True,
        "user_request": user_request,  # Store the actual request text
        "duration": 0.0
    }
    
    # Load current history
    history = load_session_history(session_name)
    
    # Add new entry
    history.append(entry)
    
    # Trim if needed
    history = trim_history_to_size(history)
    
    # Save to disk
    save_session_history(session_name, history)


def trim_history_to_size(history: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Trim history to stay under MAX_HISTORY_SIZE by removing oldest entries"""
    if not history:
        return history
    
    # Calculate current size
    history_json = json.dumps(history, ensure_ascii=False)
    current_size = len(history_json)
    
    if current_size <= MAX_HISTORY_SIZE:
        return history  # Already under limit
    
    # Remove entries from the beginning until we're under the limit
    trimmed_history = history.copy()
    
    while len(trimmed_history) > 1:  # Keep at least one entry
        trimmed_history.pop(0)  # Remove oldest entry
        
        # Check new size
        trimmed_json = json.dumps(trimmed_history, ensure_ascii=False)
        if len(trimmed_json) <= MAX_HISTORY_SIZE:
            break
    
    return trimmed_history


def add_history_entry(session_name: str, event: Event) -> None:
    """Add a new history entry immediately (synchronous)"""
    # Extract success from outputs
    success = False
    if event.get("outputs") and isinstance(event["outputs"], dict):
        success = event["outputs"].get("success", False)
    
    # Create simple history entry
    entry = {
        "timestamp": event.get("timestamp", time.time()),
        "current_task": event.get("current_task", ""),
        "summary_of_what_we_just_did": event.get("summary_of_what_we_just_did", ""),
        "summary_of_what_we_about_to_do": event.get("summary_of_what_we_about_to_do", ""),
        "event_type": event.get("type", ""),
        "success": success,
        "duration": event.get("duration")
    }
    
    # Load current history
    history = load_session_history(session_name)
    
    # Add new entry
    history.append(entry)
    
    # Trim if needed
    history = trim_history_to_size(history)
    
    # Save to disk
    save_session_history(session_name, history)


def get_formatted_history(session_name: str, limit: Optional[int] = None) -> str:
    """Get formatted history for display"""
    try:
        history = load_session_history(session_name)
        
        if not history:
            return "No history available."
        
        # Apply limit if specified
        if limit:
            history = history[-limit:]
        
        formatted_entries = []
        for i, entry in enumerate(history, 1):
            # Format timestamp
            timestamp_str = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(entry.get("timestamp", 0)))
            
            # Format success indicator
            status = "✓" if entry.get("success", False) else "✗"
            
            # Special formatting for user requests
            if entry.get("event_type") == "user_request":
                entry_text = f"""Entry {i} [{timestamp_str}] {status}
  User Request: {entry.get('user_request', '')}
  Type: {entry.get('event_type', '')}"""
            else:
                # Build entry text
                entry_text = f"""Entry {i} [{timestamp_str}] {status}
  Task: {entry.get('current_task', '')}
  Just did: {entry.get('summary_of_what_we_just_did', '')}
  About to do: {entry.get('summary_of_what_we_about_to_do', '')}
  Type: {entry.get('event_type', '')}"""
            
            if entry.get("duration"):
                entry_text += f"\n  Duration: {entry['duration']:.2f}s"
            
            formatted_entries.append(entry_text)
        
        return "\n\n".join(formatted_entries)
        
    except Exception as e:
        return f"Error loading history: {e}"


def get_history_entry_count(session_name: str) -> int:
    """Get the number of entries in the history"""
    try:
        history = load_session_history(session_name)
        return len(history)
    except Exception:
        return 0
