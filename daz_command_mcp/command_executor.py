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


def _clean_command_result(result: Dict[str, Any], include_session: bool = False) -> Dict[str, Any]:
    """
    Clean up command results to remove unnecessary information.
    
    Rules:
    - Remove stderr if blank
    - Remove exitcode if zero
    - Remove command (always)
    - Remove killed if false
    - Remove duration (always)
    - Remove session unless include_session is True
    """
    cleaned = {}
    
    # Always include success
    if "success" in result:
        cleaned["success"] = result["success"]
    
    # Include session_id for identification
    if "session_id" in result:
        cleaned["session_id"] = result["session_id"]
    
    # Copy other core fields
    for field in ["old_directory", "new_directory", "content", "file_path", "stdout", "working_directory", "message", "info_length"]:
        if field in result:
            cleaned[field] = result[field]
    
    # Conditional fields based on rules
    if "stderr" in result and result["stderr"]:  # Only include if not blank
        cleaned["stderr"] = result["stderr"]
    
    if "exitcode" in result and result["exitcode"] != 0:  # Only include if not zero
        cleaned["exitcode"] = result["exitcode"]
    
    if "killed" in result and result["killed"]:  # Only include if true
        cleaned["killed"] = result["killed"]
    
    # Never include: command, duration
    
    # Include session only if requested (for open/current commands)
    if include_session and "session" in result:
        cleaned["session"] = result["session"]
    
    return cleaned


def add_learnings(learning_info: str) -> Dict[str, Any]:
    """
    Add learnings or useful information to the session for future reference.
    
    This function captures important discoveries, insights, or context that might be 
    valuable for future work in this session. Examples include:
    - Full directory paths discovered during navigation
    - Important file locations or project structure insights  
    - Configuration details or environment setup notes
    - Error patterns or troubleshooting discoveries
    - Any contextual information that would help someone continue work later
    
    This function preserves useful information for the session context.
    """
    session_name = get_active_session_name()
    if not session_name:
        raise ValueError("No active session. Create or open a session first.")

    start_time = time.time()

    event: Event = {
        "timestamp": start_time,
        "type": "learning",
        "current_task": "Capturing useful session context",
        "summary_of_what_we_just_did": "Identified important information to preserve",
        "summary_of_what_we_about_to_do": "Store this information for future session reference",
        "inputs": {"learning_info": learning_info},
        "outputs": {"captured": True, "info_length": len(learning_info)},
        "duration": time.time() - start_time,
    }

    session_data = append_event(session_name, event)

    result = {
        "success": True,
        "message": "Learning information added to session context",
        "info_length": len(learning_info),
        "session": session_data,
    }
    
    return _clean_command_result(result)


def change_directory(directory: str, current_task: str, summary_of_what_we_just_did: str, summary_of_what_we_about_to_do: str) -> Dict[str, Any]:
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
        "current_task": current_task,
        "summary_of_what_we_just_did": summary_of_what_we_just_did,
        "summary_of_what_we_about_to_do": summary_of_what_we_about_to_do,
        "inputs": {"directory": directory, "old_cwd": old_cwd},
        "outputs": {"success": success, "new_cwd": new_cwd, "error": error_msg},
        "duration": time.time() - start_time,
    }

    session_data = append_event(session_name, event)

    if not success:
        raise ValueError(f"Failed to change directory: {error_msg}")

    result = {
        "success": True,
        "old_directory": old_cwd,
        "new_directory": new_cwd,
        "session": session_data,
    }
    
    return _clean_command_result(result)


def read_file(file_path: str, current_task: str, summary_of_what_we_just_did: str, summary_of_what_we_about_to_do: str) -> Dict[str, Any]:
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
        "current_task": current_task,
        "summary_of_what_we_just_did": summary_of_what_we_just_did,
        "summary_of_what_we_about_to_do": summary_of_what_we_about_to_do,
        "inputs": {"file_path": file_path, "absolute_path": str(path.resolve())},
        "outputs": {"success": success, "content_length": len(content), "error": error_msg},
        "duration": time.time() - start_time,
    }

    session_data = append_event(session_name, event)

    if not success:
        raise ValueError(f"Failed to read file: {error_msg}")

    result = {
        "success": True,
        "content": content,
        "file_path": str(path.resolve()),
        "session": session_data,
    }
    
    return _clean_command_result(result)


def write_file(file_path: str, content: str, current_task: str, summary_of_what_we_just_did: str, summary_of_what_we_about_to_do: str, create_dirs: bool = True) -> Dict[str, Any]:
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
        "current_task": current_task,
        "summary_of_what_we_just_did": summary_of_what_we_just_did,
        "summary_of_what_we_about_to_do": summary_of_what_we_about_to_do,
        "inputs": {"file_path": file_path, "content_length": len(content), "create_dirs": create_dirs},
        "outputs": {"success": success, "absolute_path": str(path.resolve()), "error": error_msg},
        "duration": time.time() - start_time,
    }

    session_data = append_event(session_name, event)

    if not success:
        raise ValueError(f"Failed to write file: {error_msg}")

    result = {
        "success": True,
        "file_path": str(path.resolve()),
        "session": session_data,
    }
    
    return _clean_command_result(result)


def run_command(command: str, current_task: str, summary_of_what_we_just_did: str, summary_of_what_we_about_to_do: str, timeout: float = 60, working_directory: Optional[str] = None) -> Dict[str, Any]:
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
        "current_task": current_task,
        "summary_of_what_we_just_did": summary_of_what_we_just_did,
        "summary_of_what_we_about_to_do": summary_of_what_we_about_to_do,
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

    result_dict = {
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
    
    return _clean_command_result(result_dict)
