#!/usr/bin/env python3
"""
Command execution functionality for DAZ Command MCP Server
"""

from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, Optional

from .models import Event
from .utils import get_active_session_name
from .session_manager import append_event


def change_directory(directory: str, why: str) -> Dict[str, Any]:
    """Changes the current working directory for the active session."""
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


def read_file(file_path: str, why: str) -> Dict[str, Any]:
    """Reads a text file for the active session."""
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


def write_file(file_path: str, content: str, why: str, create_dirs: bool = True) -> Dict[str, Any]:
    """Writes a text file for the active session."""
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


def run_command(command: str, why: str, timeout: float = 60, working_directory: Optional[str] = None) -> Dict[str, Any]:
    """Runs a shell command for the active session."""
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
