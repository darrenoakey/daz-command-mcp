#!/usr/bin/env python3
# DAZ Command MCP Server (Sessions + Async LLM Summaries)

from __future__ import annotations

# --- stdlib imports (top-level only) ---
import argparse
import json
import os
import queue
import signal
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, TypedDict

# --- third-party (top-level only) ---
from fastmcp import FastMCP
from pydantic import BaseModel
from dazllm import Llm


# --- constants and globals ---
# Comment: Sets the model once; if LM Studio isn't running or model missing, the summariser will log and skip.
LLM_MODEL_NAME = "lm-studio:openai/gpt-oss-20b"

# Comment: Resolve script directory and sessions path.
SCRIPT_DIR = Path(__file__).resolve().parent
SESSIONS_DIR = SCRIPT_DIR / "sessions"

# Comment: Global state for active session selection and thread safety.
_active_session_name_lock = threading.Lock()
_active_session_name: Optional[str] = None

# Comment: In-memory queue and worker thread for asynchronous summarisation.
_summary_queue: "queue.Queue[Dict[str, Any]]" = queue.Queue()
_summary_thread_started = False
_summary_thread_started_lock = threading.Lock()

# Comment: MCP server instance.
mcp = FastMCP("DAZ Command MCP")


# --- Pydantic schemas for structured LLM responses ---
# Comment: Defines the structured output we expect from the LLM when updating a session.
class SessionSummary(BaseModel):
    summary: str


# --- lightweight typed dicts for clarity ---
# Comment: Event payload recorded to the session file.
class Event(TypedDict, total=False):
    timestamp: float
    type: str
    why: str
    inputs: Dict[str, Any]
    outputs: Dict[str, Any]
    duration: float


# --- utility functions (small, single-responsibility) ---
# Comment: Ensures the sessions directory exists.
def ensure_sessions_dir() -> None:
    SESSIONS_DIR.mkdir(parents=True, exist_ok=True)


# Comment: Sanitize session name for use as directory name
def sanitize_session_name(name: str) -> str:
    """Convert session name to valid directory name"""
    # Replace invalid characters with underscores
    sanitized = "".join(c if c.isalnum() or c in "-_." else "_" for c in name)
    # Ensure it doesn't start with a dot
    if sanitized.startswith("."):
        sanitized = "_" + sanitized[1:]
    # Limit length
    return sanitized[:100]


# Comment: Get session directory path from name
def get_session_dir(session_name: str) -> Path:
    return SESSIONS_DIR / sanitize_session_name(session_name)


# Comment: Check if session exists
def session_exists(session_name: str) -> bool:
    return get_session_dir(session_name).exists()


# Comment: Load session summary; returns summary text or empty string
def load_session_summary(session_name: str) -> str:
    summary_path = get_session_dir(session_name) / "summary.txt"
    if summary_path.exists():
        return summary_path.read_text(encoding="utf-8").strip()
    return ""


# Comment: Save session summary
def save_session_summary(session_name: str, summary: str) -> None:
    session_dir = get_session_dir(session_name)
    session_dir.mkdir(parents=True, exist_ok=True)
    summary_path = session_dir / "summary.txt"
    summary_path.write_text(summary, encoding="utf-8")


# Comment: Append event to event log (JSONL format)
def append_event_to_log(session_name: str, event: Event) -> None:
    session_dir = get_session_dir(session_name)
    session_dir.mkdir(parents=True, exist_ok=True)
    log_path = session_dir / "event_log.json"
    
    # Append as JSON line
    with log_path.open("a", encoding="utf-8") as f:
        json.dump(event, f, ensure_ascii=False)
        f.write("\n")


# Comment: Append error to errors log (JSONL format)
def append_error_to_log(session_name: str, error: Dict[str, Any]) -> None:
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


# Comment: Returns the currently active session name or None.
def get_active_session_name() -> Optional[str]:
    with _active_session_name_lock:
        return _active_session_name


# Comment: Sets the currently active session name (or None).
def set_active_session_name(session_name: Optional[str]) -> None:
    with _active_session_name_lock:
        global _active_session_name
        _active_session_name = session_name


# Comment: Create session metadata dict for public view
def create_session_metadata(session_name: str) -> Dict[str, Any]:
    session_dir = get_session_dir(session_name)
    
    # Count events by counting lines in event_log.json
    events_count = 0
    log_path = session_dir / "event_log.json"
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


# Comment: Truncate text with indication if it was truncated
def truncate_with_indication(text: str, max_chars: int, from_end: bool = False) -> str:
    if len(text) <= max_chars:
        return text
    
    if from_end:
        truncated = text[-max_chars:]
        return f"...(abridged from {len(text)} chars)...{truncated}"
    else:
        truncated = text[:max_chars]
        return f"{truncated}...(abridged from {len(text)} chars)..."


# Comment: Enqueue a summary update task
def enqueue_summary(session_name: str, old_summary: str, event: Event) -> None:
    payload = {
        "session_name": session_name,
        "old_summary": old_summary,
        "event": event,
    }
    _summary_queue.put(payload)


# Comment: Loads the LLM client; returns None if unavailable.
def get_llm() -> Optional[Llm]:
    try:
        return Llm(LLM_MODEL_NAME)
    except Exception as e:
        print(f"[summary-worker] LLM init failed: {e}", file=sys.stderr)
        return None


# --- background worker ---
# Comment: Background worker that consumes the queue and updates session summaries; robust to errors.
def _summary_worker() -> None:
    llm = get_llm()
    last_llm_error_time = 0.0

    while True:
        try:
            task = _summary_queue.get()
        except Exception:
            time.sleep(0.1)
            continue

        session_name = None
        try:
            session_name: str = task["session_name"]
            old_summary: str = task.get("old_summary", "")
            event: Event = task["event"]

            # Skip if LLM not available; retry infrequently by reinitialising after failures.
            if llm is None:
                now = time.time()
                if now - last_llm_error_time > 10.0:
                    llm = get_llm()
                    last_llm_error_time = now
                # If still None, drop task silently.
                if llm is None:
                    continue

            # Prepare input and output text for LLM
            input_text = ""
            output_text = ""
            
            if event.get("inputs"):
                # Get input text from various sources
                for key, value in event["inputs"].items():
                    if isinstance(value, str):
                        input_text += f"{key}: {value}\n"
                    else:
                        input_text += f"{key}: {json.dumps(value)}\n"
            
            if event.get("outputs"):
                # Get output text from various sources
                for key, value in event["outputs"].items():
                    if isinstance(value, str):
                        output_text += f"{key}: {value}\n"
                    else:
                        output_text += f"{key}: {json.dumps(value)}\n"

            # Truncate input and output as specified
            input_summary = truncate_with_indication(input_text.strip(), 256, from_end=False)
            output_summary = truncate_with_indication(output_text.strip(), 256, from_end=True)

            # Prepare detailed prompt for summary update
            prompt = (
                "You are maintaining a detailed engineering session log. "
                "Please provide a comprehensive update to the session summary based on the new event.\n\n"
                "Your summary should include:\n"
                "- The main intent and purpose of this session\n"
                "- The current location/directory being worked on\n"
                "- Any important learnings about file structure, project layout, or technical insights\n"
                "- Current progress and what was most recently accomplished\n"
                "- Any challenges encountered or things to be aware of\n\n"
                "Be detailed and thorough - this summary will be used to understand the session context later. "
                "Include technical details, file paths, command outcomes, and any discoveries made.\n\n"
                "Do NOT be concise - provide a full, detailed summary that captures all important context."
            )

            # Build inputs for the LLM.
            llm_inputs = {
                "old_summary": old_summary,
                "new_event": {
                    "type": event.get("type", ""),
                    "why": event.get("why", ""),
                    "timestamp": event.get("timestamp", time.time()),
                    "duration": event.get("duration", 0)
                },
                "input_text": input_summary,
                "output_text": output_summary
            }

            # Call LLM with structured output; failures must not break MCP.
            try:
                update = llm.chat_structured(
                    prompt + "\n\nJSON INPUT:\n" + json.dumps(llm_inputs, ensure_ascii=False, indent=2),
                    SessionSummary,
                )
                new_summary = update.summary.strip()
                if new_summary:
                    save_session_summary(session_name, new_summary)
            except Exception as e:
                error_record = {
                    "timestamp": time.time(),
                    "type": "llm_summary_error",
                    "error": str(e),
                    "session_name": session_name
                }
                append_error_to_log(session_name, error_record)
                print(f"[summary-worker] llm.chat_structured failed: {e}", file=sys.stderr)

        except Exception as e:
            error_record = {
                "timestamp": time.time(),
                "type": "summary_worker_error",
                "error": str(e),
                "session_name": session_name or "unknown"
            }
            if session_name:
                append_error_to_log(session_name, error_record)
            print(f"[summary-worker] unexpected error: {e}", file=sys.stderr)
        finally:
            try:
                _summary_queue.task_done()
            except Exception:
                pass


# --- session management helpers ---
# Comment: Creates a new session directory and initializes it.
def create_session_record(name: str, description: str) -> Dict[str, Any]:
    ensure_sessions_dir()
    session_dir = get_session_dir(name)
    
    if session_dir.exists():
        raise ValueError(f"Session '{name}' already exists")
    
    session_dir.mkdir(parents=True, exist_ok=True)
    
    # Initialize summary with the description (the "why")
    initial_summary = f"Session Purpose: {description}\n\nStarted at: {Path.cwd()}\n\nSession Log:\n"
    save_session_summary(name, initial_summary)
    
    return create_session_metadata(name)


# Comment: Lists all sessions by looking at directory names only.
def list_session_views() -> List[Dict[str, Any]]:
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


# Comment: Appends an event and triggers async summary update.
def append_event(session_name: str, event: Event) -> Dict[str, Any]:
    try:
        # Get old summary before appending event
        old_summary = load_session_summary(session_name)
        
        # Append event to log
        append_event_to_log(session_name, event)
        
        # Trigger async summary update
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


# --- command execution ---
# Comment: Changes the current working directory for the active session.
def change_directory(directory: str, why: str) -> Dict[str, Any]:
    session_name = get_active_session_name()
    if not session_name:
        raise ValueError("No active session. Create or open a session first.")

    start_time = time.time()
    old_cwd = str(Path.cwd())

    try:
        os.chdir(directory)
        new_cwd = str(Path.cwd())
        success = True
        error_msg = ""
    except Exception as e:
        new_cwd = old_cwd
        success = False
        error_msg = str(e)

    event: Event = {
        "timestamp": start_time,
        "type": "cd",
        "why": why,
        "inputs": {"directory": directory, "old_cwd": old_cwd},
        "outputs": {"success": success, "new_cwd": new_cwd, "error": error_msg},
        "duration": time.time() - start_time,
    }

    session_data = append_event(session_name, event)

    if not success:
        raise ValueError(f"Failed to change directory: {error_msg}")

    return {
        "success": True,
        "old_directory": old_cwd,
        "new_directory": new_cwd,
        "session": session_data,
    }


# Comment: Reads a text file for the active session.
def read_file(file_path: str, why: str) -> Dict[str, Any]:
    session_name = get_active_session_name()
    if not session_name:
        raise ValueError("No active session. Create or open a session first.")

    start_time = time.time()
    path = Path(file_path)

    try:
        content = path.read_text(encoding="utf-8")
        success = True
        error_msg = ""
    except Exception as e:
        content = ""
        success = False
        error_msg = str(e)

    event: Event = {
        "timestamp": start_time,
        "type": "read",
        "why": why,
        "inputs": {"file_path": file_path, "absolute_path": str(path.resolve())},
        "outputs": {"success": success, "content_length": len(content), "error": error_msg},
        "duration": time.time() - start_time,
    }

    session_data = append_event(session_name, event)

    if not success:
        raise ValueError(f"Failed to read file: {error_msg}")

    return {
        "success": True,
        "content": content,
        "file_path": str(path.resolve()),
        "session": session_data,
    }


# Comment: Writes a text file for the active session.
def write_file(file_path: str, content: str, why: str, create_dirs: bool = True) -> Dict[str, Any]:
    session_name = get_active_session_name()
    if not session_name:
        raise ValueError("No active session. Create or open a session first.")

    start_time = time.time()
    path = Path(file_path)

    try:
        if create_dirs:
            path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        success = True
        error_msg = ""
    except Exception as e:
        success = False
        error_msg = str(e)

    event: Event = {
        "timestamp": start_time,
        "type": "write",
        "why": why,
        "inputs": {"file_path": file_path, "content_length": len(content), "create_dirs": create_dirs},
        "outputs": {"success": success, "absolute_path": str(path.resolve()), "error": error_msg},
        "duration": time.time() - start_time,
    }

    session_data = append_event(session_name, event)

    if not success:
        raise ValueError(f"Failed to write file: {error_msg}")

    return {
        "success": True,
        "file_path": str(path.resolve()),
        "session": session_data,
    }


# Comment: Runs a shell command for the active session.
def run_command(command: str, why: str, timeout: float = 60, working_directory: Optional[str] = None) -> Dict[str, Any]:
    session_name = get_active_session_name()
    if not session_name:
        raise ValueError("No active session. Create or open a session first.")

    start_time = time.time()
    cwd = working_directory or str(Path.cwd())

    try:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=cwd,
        )
        stdout = result.stdout
        stderr = result.stderr
        exitcode = result.returncode
        killed = False
        success = True
        error_msg = ""
    except subprocess.TimeoutExpired:
        stdout = ""
        stderr = f"Command timed out after {timeout} seconds"
        exitcode = -1
        killed = True
        success = False
        error_msg = "timeout"
    except Exception as e:
        stdout = ""
        stderr = str(e)
        exitcode = -1
        killed = False
        success = False
        error_msg = str(e)

    duration = time.time() - start_time

    event: Event = {
        "timestamp": start_time,
        "type": "run",
        "why": why,
        "inputs": {"command": command, "timeout": timeout, "working_directory": cwd},
        "outputs": {
            "success": success,
            "stdout": stdout,
            "stderr": stderr,
            "exitcode": exitcode,
            "killed": killed,
            "error": error_msg
        },
        "duration": duration,
    }

    session_data = append_event(session_name, event)

    return {
        "success": success,
        "session_id": session_name,
        "command": command,
        "stdout": stdout,
        "stderr": stderr,
        "exitcode": exitcode,
        "killed": killed,
        "duration": duration,
        "working_directory": cwd,
        "session": session_data,
    }


# --- MCP endpoints ---
@mcp.tool()
def daz_sessions_list() -> str:
    """List all sessions and which one is active."""
    try:
        sessions = list_session_views()
        return json.dumps({"sessions": sessions}, ensure_ascii=False, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False)


@mcp.tool()
def daz_session_create(name: str, description: str) -> str:
    """Create a new session. Provide a name and a detailed description of the task. Activates the new session."""
    try:
        session_data = create_session_record(name, description)
        set_active_session_name(name)
        return json.dumps({"success": True, "session": session_data}, ensure_ascii=False, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False)


@mcp.tool()
def daz_session_open(session_id: str) -> str:
    """Open an existing session by id and make it active. Returns a summary of the session."""
    try:
        # session_id is actually the session name in the new structure
        session_name = session_id
        
        if not session_exists(session_name):
            return json.dumps({"error": f"Session '{session_name}' not found"}, ensure_ascii=False)
        
        set_active_session_name(session_name)
        session_data = create_session_metadata(session_name)
        
        # Load and return the full summary
        summary = load_session_summary(session_name)
        
        return json.dumps({
            "success": True,
            "session": session_data,
            "summary": summary
        }, ensure_ascii=False, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False)


@mcp.tool()
def daz_session_current() -> str:
    """Return the currently active session summary."""
    try:
        session_name = get_active_session_name()
        if not session_name:
            return json.dumps({"error": "No active session"}, ensure_ascii=False)
        
        session_data = create_session_metadata(session_name)
        summary = load_session_summary(session_name)
        
        return json.dumps({
            "active_session": session_data,
            "summary": summary
        }, ensure_ascii=False, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False)


@mcp.tool()
def daz_command_cd(directory: str, why: str) -> str:
    """Change directory for the active session."""
    try:
        result = change_directory(directory, why)
        return json.dumps(result, ensure_ascii=False, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False)


@mcp.tool()
def daz_command_read(file_path: str, why: str) -> str:
    """Read a text file for the active session. Provide 'why' to explain the purpose."""
    try:
        result = read_file(file_path, why)
        return json.dumps(result, ensure_ascii=False, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False)


@mcp.tool()
def daz_command_write(file_path: str, content: str, why: str, create_dirs: bool = True) -> str:
    """Write a text file for the active session. Provide 'why' to explain the purpose."""
    try:
        result = write_file(file_path, content, why, create_dirs)
        return json.dumps(result, ensure_ascii=False, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False)


@mcp.tool()
def daz_command_run(command: str, why: str, timeout: float = 60, working_directory: Optional[str] = None) -> str:
    """Run a shell command for the active session. Provide 'why' to explain the purpose."""
    try:
        result = run_command(command, why, timeout, working_directory)
        return json.dumps(result, ensure_ascii=False, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False)


# --- background thread startup ---
# Comment: Ensures the background summary thread is started exactly once.
def ensure_summary_thread() -> None:
    global _summary_thread_started
    with _summary_thread_started_lock:
        if not _summary_thread_started:
            thread = threading.Thread(target=_summary_worker, daemon=True)
            thread.start()
            _summary_thread_started = True


# --- main function ---
def main() -> None:
    parser = argparse.ArgumentParser(description="DAZ Command MCP Server")
    parser.add_argument("--port", type=int, default=3001, help="Port to run the server on")
    args = parser.parse_args()

    ensure_summary_thread()

    def signal_handler(sig: int, frame: Any) -> None:
        print("\n[mcp] shutting down gracefully...", file=sys.stderr)
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    print(f"[mcp] starting server on port {args.port}...", file=sys.stderr)
    mcp.run(port=args.port)


if __name__ == "__main__":
    main()
