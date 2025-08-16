#!/usr/bin/env python3
"""
MCP Tool endpoints for DAZ Command MCP Server

CRITICAL: All @mcp.tool() decorators MUST include description="..." parameter.
The description parameter is what gets sent to the MCP client as the tool description.
Docstrings alone are NOT sufficient and will not be displayed to users.

NEVER remove the description parameter from @mcp.tool() decorators.
ALWAYS ensure every tool has a clear, detailed description in the decorator.
"""

from __future__ import annotations

import json
from typing import Optional

from fastmcp import FastMCP

from .session_manager import (
    list_session_views, create_session_record, create_session_metadata,
    rename_session, delete_session
)
from .command_executor import change_directory, read_file, write_file, run_command, add_learnings
from .utils import get_active_session_name, set_active_session_name, session_exists, load_session_summary
from .summary_worker import wait_for_summary_queue_empty, is_summary_queue_empty, get_summary_queue_size
from .history_manager import (
    get_formatted_history, get_formatted_instructions, load_session_instructions,
    add_session_instruction, replace_session_instructions, record_user_request
)


# Comment: MCP server instance.
mcp = FastMCP("DAZ Command MCP")


@mcp.tool(description="Record a user request in the session history. This should be called at the start of any multi-step task to document what the user is requesting. This creates a user_request entry type in the history that clearly shows what the user asked for.")
def daz_record_user_request(user_request: str) -> str:
    try:
        session_name = get_active_session_name()
        if not session_name:
            return json.dumps({"error": "No active session"}, ensure_ascii=False)
        
        record_user_request(session_name, user_request)
        
        return json.dumps({
            "success": True,
            "message": "User request recorded successfully",
            "session_name": session_name,
            "user_request": user_request
        }, ensure_ascii=False, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False)


@mcp.tool(description="Rename an existing session. If the session being renamed is currently active, it will remain active under the new name.")
def daz_session_rename(old_name: str, new_name: str) -> str:
    try:
        session_data = rename_session(old_name, new_name)
        
        return json.dumps({
            "success": True,
            "message": f"Session '{old_name}' renamed to '{new_name}'",
            "old_name": old_name,
            "new_name": new_name,
            "session": session_data,
            "is_active": session_data.get("is_active", False)
        }, ensure_ascii=False, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False)


@mcp.tool(description="Delete a session by moving it to the deleted_sessions directory. If the deleted session was active, no session will be active after deletion.")
def daz_session_delete(session_name: str) -> str:
    try:
        result = delete_session(session_name)
        
        return json.dumps(result, ensure_ascii=False, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False)


@mcp.tool(description="List all sessions and which one is active.")
def daz_sessions_list() -> str:
    try:
        sessions = list_session_views()
        return json.dumps({"sessions": sessions}, ensure_ascii=False, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False)


@mcp.tool(description="Create a new session. Provide a name and a detailed description of the task. Activates the new session.")
def daz_session_create(name: str, description: str) -> str:
    try:
        session_data = create_session_record(name, description)
        set_active_session_name(name)
        return json.dumps({
            "success": True, 
            "session": session_data
        }, ensure_ascii=False, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False)


@mcp.tool(description="Open an existing session by id and make it active. Returns a summary, history, and instructions of the session.")
def daz_session_open(session_id: str) -> str:
    try:
        # session_id is actually the session name in the new structure
        session_name = session_id
        
        if not session_exists(session_name):
            return json.dumps({"error": f"Session '{session_name}' not found"}, ensure_ascii=False)
        
        set_active_session_name(session_name)
        session_data = create_session_metadata(session_name)
        
        # Load and return the full summary
        summary = load_session_summary(session_name)
        
        # Load and return the history
        history = get_formatted_history(session_name, limit=10)  # Show last 10 entries
        
        # Load and return the instructions
        instructions = get_formatted_instructions(session_name)
        
        return json.dumps({
            "success": True,
            "session": session_data,
            "summary": summary,
            "history": history,
            "instructions": instructions
        }, ensure_ascii=False, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False)


@mcp.tool(description="Return the currently active session summary, history, and instructions.")
def daz_session_current() -> str:
    try:
        session_name = get_active_session_name()
        if not session_name:
            return json.dumps({"error": "No active session"}, ensure_ascii=False)
        
        session_data = create_session_metadata(session_name)
        summary = load_session_summary(session_name)
        
        # Load and return the history
        history = get_formatted_history(session_name, limit=10)  # Show last 10 entries
        
        # Load and return the instructions
        instructions = get_formatted_instructions(session_name)
        
        return json.dumps({
            "active_session": session_data,
            "summary": summary,
            "history": history,
            "instructions": instructions
        }, ensure_ascii=False, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False)


@mcp.tool(description="Close the current session. This command waits for any pending summary processing to complete before confirming the session is closed. If summary processing is still in progress after 30 seconds, returns a message asking to retry.")
def daz_session_close() -> str:
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


@mcp.tool(description="Read the current instructions for the active session.")
def daz_instructions_read() -> str:
    try:
        session_name = get_active_session_name()
        if not session_name:
            return json.dumps({"error": "No active session"}, ensure_ascii=False)
        
        instructions = load_session_instructions(session_name)
        formatted_instructions = get_formatted_instructions(session_name)
        
        return json.dumps({
            "success": True,
            "session_name": session_name,
            "instructions": instructions,
            "formatted_instructions": formatted_instructions
        }, ensure_ascii=False, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False)


@mcp.tool(description="Add a new instruction to the active session. The instruction should be a single dot point of guidance.")
def daz_instructions_add(instruction: str) -> str:
    try:
        session_name = get_active_session_name()
        if not session_name:
            return json.dumps({"error": "No active session"}, ensure_ascii=False)
        
        add_session_instruction(session_name, instruction)
        instructions = load_session_instructions(session_name)
        
        return json.dumps({
            "success": True,
            "message": "Instruction added successfully",
            "session_name": session_name,
            "total_instructions": len(instructions),
            "new_instruction": instruction
        }, ensure_ascii=False, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False)


@mcp.tool(description="Replace ALL instructions for the active session with a new list. This will completely overwrite all existing instructions.")
def daz_instructions_replace(instructions: list[str]) -> str:
    try:
        session_name = get_active_session_name()
        if not session_name:
            return json.dumps({"error": "No active session"}, ensure_ascii=False)
        
        replace_session_instructions(session_name, instructions)
        
        return json.dumps({
            "success": True,
            "message": "Instructions replaced successfully",
            "session_name": session_name,
            "instruction_count": len(instructions),
            "instructions": instructions
        }, ensure_ascii=False, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False)


@mcp.tool(description="Add learnings or useful information to the session for future reference. Use this to capture important discoveries, insights, or context that might be valuable for future work in this session. Examples include: full directory paths discovered during navigation, important file locations or project structure insights, configuration details or environment setup notes, error patterns or troubleshooting discoveries, any contextual information that would help someone continue work later. This function preserves useful information for session context and doesn't execute any commands; it simply adds the information to the LLM processing queue for inclusion in session summaries.")
def daz_add_learnings(learning_info: str) -> str:
    try:
        result = add_learnings(learning_info)
        return json.dumps(result, ensure_ascii=False, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False)


@mcp.tool(description="Change directory for the active session. CRITICAL: All three context parameters are REQUIRED and essential for maintaining task continuity across the session. These parameters are the MOST IMPORTANT part of each command as they preserve the complete context of your work. Parameters: current_task (the main task you are currently working on), summary_of_what_we_just_did (brief summary of the last action and its outcome), summary_of_what_we_about_to_do (what you plan to do next). If you are in the middle of a multi-step task, maintain the COMPLETE task history in these parameters to ensure seamless continuation of work.")
def daz_command_cd(
    directory: str, 
    current_task: str, 
    summary_of_what_we_just_did: str, 
    summary_of_what_we_about_to_do: str
) -> str:
    try:
        result = change_directory(directory, current_task, summary_of_what_we_just_did, summary_of_what_we_about_to_do)
        return json.dumps(result, ensure_ascii=False, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False)


@mcp.tool(description="Read a text file for the active session. CRITICAL: All three context parameters are REQUIRED and essential for maintaining task continuity across the session. These parameters are the MOST IMPORTANT part of each command as they preserve the complete context of your work. Parameters: current_task (the main task you are currently working on), summary_of_what_we_just_did (brief summary of the last action and its outcome), summary_of_what_we_about_to_do (what you plan to do next). If you are in the middle of a multi-step task, maintain the COMPLETE task history in these parameters to ensure seamless continuation of work.")
def daz_command_read(
    file_path: str, 
    current_task: str, 
    summary_of_what_we_just_did: str, 
    summary_of_what_we_about_to_do: str
) -> str:
    try:
        result = read_file(file_path, current_task, summary_of_what_we_just_did, summary_of_what_we_about_to_do)
        return json.dumps(result, ensure_ascii=False, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False)


@mcp.tool(description="Write a text file for the active session. CRITICAL: All three context parameters are REQUIRED and essential for maintaining task continuity across the session. These parameters are the MOST IMPORTANT part of each command as they preserve the complete context of your work. Parameters: current_task (the main task you are currently working on), summary_of_what_we_just_did (brief summary of the last action and its outcome), summary_of_what_we_about_to_do (what you plan to do next). If you are in the middle of a multi-step task, maintain the COMPLETE task history in these parameters to ensure seamless continuation of work.")
def daz_command_write(
    file_path: str, 
    content: str, 
    current_task: str, 
    summary_of_what_we_just_did: str, 
    summary_of_what_we_about_to_do: str, 
    create_dirs: bool = True
) -> str:
    try:
        result = write_file(file_path, content, current_task, summary_of_what_we_just_did, summary_of_what_we_about_to_do, create_dirs)
        return json.dumps(result, ensure_ascii=False, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False)


@mcp.tool(description="Run a shell command for the active session. CRITICAL: All three context parameters are REQUIRED and essential for maintaining task continuity across the session. These parameters are the MOST IMPORTANT part of each command as they preserve the complete context of your work. Parameters: current_task (the main task you are currently working on), summary_of_what_we_just_did (brief summary of the last action and its outcome), summary_of_what_we_about_to_do (what you plan to do next). If you are in the middle of a multi-step task, maintain the COMPLETE task history in these parameters to ensure seamless continuation of work.")
def daz_command_run(
    command: str, 
    current_task: str, 
    summary_of_what_we_just_did: str, 
    summary_of_what_we_about_to_do: str, 
    timeout: float = 60, 
    working_directory: Optional[str] = None
) -> str:
    try:
        result = run_command(command, current_task, summary_of_what_we_just_did, summary_of_what_we_about_to_do, timeout, working_directory)
        return json.dumps(result, ensure_ascii=False, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False)
