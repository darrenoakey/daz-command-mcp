#!/usr/bin/env python3
"""
MCP Tool endpoints for DAZ Command MCP Server
"""

from __future__ import annotations

import json
from typing import Optional

from fastmcp import FastMCP

from .session_manager import (
    list_session_views, create_session_record, create_session_metadata
)
from .command_executor import change_directory, read_file, write_file, run_command
from .utils import get_active_session_name, set_active_session_name, session_exists, load_session_summary


# Comment: MCP server instance.
mcp = FastMCP("DAZ Command MCP")


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
