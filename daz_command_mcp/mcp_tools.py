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
from .command_executor import change_directory, read_file, write_file, run_command, add_learnings
from .utils import get_active_session_name, set_active_session_name, session_exists, load_session_summary
from .summary_worker import wait_for_summary_queue_empty, is_summary_queue_empty, get_summary_queue_size


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
        return json.dumps({
            "success": True, 
            "session": session_data
        }, ensure_ascii=False, indent=2)
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
def daz_session_close() -> str:
    """
    Close the current session. This command waits for any pending summary processing 
    to complete before confirming the session is closed. If summary processing is 
    still in progress after 30 seconds, returns a message asking to retry.
    """
    try:
        session_name = get_active_session_name()
        if not session_name:
            return json.dumps({"error": "No active session to close"}, ensure_ascii=False)
        
        # Check if summary queue is already empty
        if is_summary_queue_empty():
            # No summary processing pending, can close immediately
            set_active_session_name(None)  # Clear active session
            return json.dumps({
                "success": True,
                "message": f"Session '{session_name}' closed successfully",
                "session_name": session_name
            }, ensure_ascii=False, indent=2)
        
        # Queue is not empty, wait for it to finish
        queue_size = get_summary_queue_size()
        if wait_for_summary_queue_empty(timeout=30.0):
            # Queue became empty within timeout
            set_active_session_name(None)  # Clear active session
            return json.dumps({
                "success": True,
                "message": f"Session '{session_name}' closed successfully after waiting for summary processing",
                "session_name": session_name,
                "waited_for_summary": True
            }, ensure_ascii=False, indent=2)
        else:
            # Queue still not empty after timeout
            current_queue_size = get_summary_queue_size()
            return json.dumps({
                "success": False,
                "message": "We are waiting for the summary queue to finish - please try calling close session again immediately",
                "session_name": session_name,
                "queue_size_before": queue_size,
                "queue_size_after": current_queue_size,
                "waited_seconds": 30
            }, ensure_ascii=False, indent=2)
            
    except Exception as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False)


@mcp.tool()
def daz_add_learnings(learning_info: str) -> str:
    """
    Add learnings or useful information to the session for future reference.
    
    Use this to capture important discoveries, insights, or context that might be 
    valuable for future work in this session. Examples include:
    - Full directory paths discovered during navigation
    - Important file locations or project structure insights  
    - Configuration details or environment setup notes
    - Error patterns or troubleshooting discoveries
    - Any contextual information that would help someone continue work later
    
    This function preserves useful information for session context and doesn't 
    execute any commands; it simply adds the information to the LLM processing 
    queue for inclusion in session summaries.
    """
    try:
        result = add_learnings(learning_info)
        return json.dumps(result, ensure_ascii=False, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False)


@mcp.tool()
def daz_command_cd(
    directory: str, 
    current_task: str, 
    summary_of_what_we_just_did: str, 
    summary_of_what_we_about_to_do: str
) -> str:
    """
    Change directory for the active session.
    
    ⚠️  CRITICAL: All three context parameters are REQUIRED and essential for maintaining 
    task continuity across the session. These parameters are the MOST IMPORTANT part 
    of each command as they preserve the complete context of your work.
    
    Parameters:
    - current_task: The main task you are currently working on (e.g., "Implementing the new authentication system")
    - summary_of_what_we_just_did: Brief summary of the last action and its outcome (e.g., "Successfully read the user.py file and identified the login function that needs modification")
    - summary_of_what_we_about_to_do: What you plan to do next (e.g., "Navigate to the auth directory to examine the existing authentication modules")
    
    If you are in the middle of a multi-step task, maintain the COMPLETE task history 
    in these parameters to ensure seamless continuation of work.
    """
    try:
        result = change_directory(directory, current_task, summary_of_what_we_just_did, summary_of_what_we_about_to_do)
        return json.dumps(result, ensure_ascii=False, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False)


@mcp.tool()
def daz_command_read(
    file_path: str, 
    current_task: str, 
    summary_of_what_we_just_did: str, 
    summary_of_what_we_about_to_do: str
) -> str:
    """
    Read a text file for the active session.
    
    ⚠️  CRITICAL: All three context parameters are REQUIRED and essential for maintaining 
    task continuity across the session. These parameters are the MOST IMPORTANT part 
    of each command as they preserve the complete context of your work.
    
    Parameters:
    - current_task: The main task you are currently working on (e.g., "Debugging the payment processing error")
    - summary_of_what_we_just_did: Brief summary of the last action and its outcome (e.g., "Changed to the payment directory and located the payment.py file")
    - summary_of_what_we_about_to_do: What you plan to do next (e.g., "Read the payment.py file to identify the source of the transaction error")
    
    If you are in the middle of a multi-step task, maintain the COMPLETE task history 
    in these parameters to ensure seamless continuation of work.
    """
    try:
        result = read_file(file_path, current_task, summary_of_what_we_just_did, summary_of_what_we_about_to_do)
        return json.dumps(result, ensure_ascii=False, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False)


@mcp.tool()
def daz_command_write(
    file_path: str, 
    content: str, 
    current_task: str, 
    summary_of_what_we_just_did: str, 
    summary_of_what_we_about_to_do: str, 
    create_dirs: bool = True
) -> str:
    """
    Write a text file for the active session.
    
    ⚠️  CRITICAL: All three context parameters are REQUIRED and essential for maintaining 
    task continuity across the session. These parameters are the MOST IMPORTANT part 
    of each command as they preserve the complete context of your work.
    
    Parameters:
    - current_task: The main task you are currently working on (e.g., "Creating the new user registration system")
    - summary_of_what_we_just_did: Brief summary of the last action and its outcome (e.g., "Analyzed the existing registration code and identified required modifications")
    - summary_of_what_we_about_to_do: What you plan to do next (e.g., "Write the updated registration.py file with improved validation and error handling")
    
    If you are in the middle of a multi-step task, maintain the COMPLETE task history 
    in these parameters to ensure seamless continuation of work.
    """
    try:
        result = write_file(file_path, content, current_task, summary_of_what_we_just_did, summary_of_what_we_about_to_do, create_dirs)
        return json.dumps(result, ensure_ascii=False, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False)


@mcp.tool()
def daz_command_run(
    command: str, 
    current_task: str, 
    summary_of_what_we_just_did: str, 
    summary_of_what_we_about_to_do: str, 
    timeout: float = 60, 
    working_directory: Optional[str] = None
) -> str:
    """
    Run a shell command for the active session.
    
    ⚠️  CRITICAL: All three context parameters are REQUIRED and essential for maintaining 
    task continuity across the session. These parameters are the MOST IMPORTANT part 
    of each command as they preserve the complete context of your work.
    
    Parameters:
    - current_task: The main task you are currently working on (e.g., "Setting up the development environment for the new API")
    - summary_of_what_we_just_did: Brief summary of the last action and its outcome (e.g., "Successfully installed the required dependencies via pip")
    - summary_of_what_we_about_to_do: What you plan to do next (e.g., "Run the test suite to verify the environment setup is working correctly")
    
    If you are in the middle of a multi-step task, maintain the COMPLETE task history 
    in these parameters to ensure seamless continuation of work.
    """
    try:
        result = run_command(command, current_task, summary_of_what_we_just_did, summary_of_what_we_about_to_do, timeout, working_directory)
        return json.dumps(result, ensure_ascii=False, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False)
