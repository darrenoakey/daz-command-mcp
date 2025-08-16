#!/usr/bin/env python3
"""
LLM Summary Worker for DAZ Command MCP Server
"""

from __future__ import annotations

import json
import sys
import time
import threading
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

# Fail-fast dependency check
try:
    from dazllm import Llm
except ImportError as e:
    print(f"FATAL ERROR: dazllm module not available: {e}", file=sys.stderr)
    print(f"Install with: {sys.executable} -m pip install dazllm", file=sys.stderr)
    print(f"Current Python executable: {sys.executable}", file=sys.stderr)
    sys.exit(1)

from .models import (
    LLM_MODEL_NAME, _summary_queue, _summary_thread_started,
    _summary_thread_started_lock, _summary_worker_init_event,
    _summary_worker_init_success, _summary_worker_init_error, Event
)
from .utils import save_session_summary, truncate_with_indication, get_session_dir


# Global token limit management
_current_token_limit = 30000  # Default starting limit
_token_limit_lock = threading.Lock()


def estimate_tokens(text: str) -> int:
    """
    Estimate token count for text.
    Rule of thumb: ~4 characters per token for English text.
    """
    return len(text) // 4


def get_current_token_limit() -> int:
    """Get the current dynamic token limit"""
    with _token_limit_lock:
        return _current_token_limit


def update_token_limit(new_limit: int) -> None:
    """Update the current dynamic token limit"""
    global _current_token_limit
    with _token_limit_lock:
        old_limit = _current_token_limit
        _current_token_limit = new_limit
        print(f"[summary-worker] token limit adjusted: {old_limit} → {new_limit}", file=sys.stderr)


def is_summary_queue_empty() -> bool:
    """Check if the summary queue is empty"""
    return _summary_queue.empty()


def get_summary_queue_size() -> int:
    """Get the approximate size of the summary queue"""
    return _summary_queue.qsize()


def wait_for_summary_queue_empty(timeout: float = 30.0) -> bool:
    """
    Wait for the summary queue to become empty.
    
    Args:
        timeout: Maximum time to wait in seconds
        
    Returns:
        True if queue became empty within timeout, False otherwise
    """
    start_time = time.time()
    
    while time.time() - start_time < timeout:
        if is_summary_queue_empty():
            return True
        time.sleep(0.5)  # Check every 500ms
    
    return False


def extract_context_length_from_error(error_message: str) -> Optional[int]:
    """
    Extract the first number from a context length error message.
    
    Example error: "Reached context length of 4096 tokens with model..."
    Returns: 4096
    """
    try:
        # Look for the first number in the error message
        match = re.search(r'\b(\d+)\b', error_message)
        if match:
            return int(match.group(1))
    except Exception as e:
        print(f"[summary-worker] failed to extract context length from error: {e}", file=sys.stderr)
    return None


def handle_context_length_error(error_message: str, session_name: str) -> bool:
    """
    Handle a context length error by adjusting the token limit.
    
    Returns True if the limit was adjusted, False otherwise.
    """
    try:
        # Extract the context length from the error
        context_length = extract_context_length_from_error(error_message)
        if context_length is None:
            print(f"[summary-worker] could not extract context length from error: {error_message}", file=sys.stderr)
            return False
        
        current_limit = get_current_token_limit()
        target_90_percent = int(context_length * 0.9)
        
        # If our current limit is already at or below 90% of the context length,
        # ratchet down to 90% of our current limit
        if current_limit <= target_90_percent:
            new_limit = int(current_limit * 0.9)
            print(f"[summary-worker] current limit {current_limit} already <= 90% of context length {context_length}, ratcheting down to 90% of current", file=sys.stderr)
        else:
            # Set to 90% of the reported context length
            new_limit = target_90_percent
            print(f"[summary-worker] setting limit to 90% of reported context length {context_length}", file=sys.stderr)
        
        # Ensure we don't go below a reasonable minimum
        min_limit = 1000
        if new_limit < min_limit:
            new_limit = min_limit
            print(f"[summary-worker] enforcing minimum limit of {min_limit}", file=sys.stderr)
        
        update_token_limit(new_limit)
        
        log_error(session_name, "handle_context_length_error", 
                 f"adjusted token limit from {current_limit} to {new_limit} due to context length {context_length}")
        
        return True
        
    except Exception as e:
        log_error(session_name, "handle_context_length_error", f"failed to handle context length error: {e}")
        return False


def log_llm_interaction(session_name: str, prompt: str, response: str, duration: float, error: Optional[str] = None) -> None:
    """Log LLM interaction to session's llm_summary.jsonl file"""
    try:
        session_dir = get_session_dir(session_name)
        session_dir.mkdir(parents=True, exist_ok=True)
        llm_log_path = session_dir / "llm_summary.jsonl"
        
        log_entry = {
            "timestamp": time.time(),
            "prompt": prompt,
            "response": response,
            "duration": duration,
            "error": error,
            "prompt_length": len(prompt),
            "response_length": len(response),
            "model": LLM_MODEL_NAME,
            "python_executable": sys.executable,
            "token_limit": get_current_token_limit()
        }
        
        # Append as JSON line
        with llm_log_path.open("a", encoding="utf-8") as f:
            json.dump(log_entry, f, ensure_ascii=False)
            f.write("\n")
            
    except Exception as e:
        log_error(session_name, "log_llm_interaction", f"failed to log LLM interaction: {e}")


def log_error(session_name: str, function_name: str, error_message: str, extra_data: Optional[Dict[str, Any]] = None) -> None:
    """Log error to session's errors.jsonl file"""
    try:
        session_dir = get_session_dir(session_name)
        session_dir.mkdir(parents=True, exist_ok=True)
        errors_log_path = session_dir / "errors.jsonl"
        
        error_entry = {
            "timestamp": time.time(),
            "function": function_name,
            "error": error_message,
            "extra_data": extra_data or {},
            "python_executable": sys.executable,
            "token_limit": get_current_token_limit()
        }
        
        # Append as JSON line
        with errors_log_path.open("a", encoding="utf-8") as f:
            json.dump(error_entry, f, ensure_ascii=False)
            f.write("\n")
            
    except Exception as e:
        # Last resort - print to stderr if we can't even log the error
        print(f"[error-log] CRITICAL: failed to log error to {session_name}/errors.jsonl: {e}", file=sys.stderr)
        print(f"[error-log] Original error - {function_name}: {error_message}", file=sys.stderr)


def enqueue_summary(session_name: str, old_summary: str, event: Event) -> None:
    """Enqueue a summary update task"""
    try:
        payload = {
            "session_name": session_name,
            "old_summary": old_summary,
            "event": event,
        }
        _summary_queue.put(payload)
    except Exception as e:
        log_error(session_name, "enqueue_summary", f"failed to enqueue summary: {e}")


def requeue_items(items: List[Dict[str, Any]]) -> None:
    """
    Re-queue items that couldn't be processed due to token limits.
    Items are put back in reverse order to maintain the original processing order.
    """
    try:
        for item in reversed(items):
            _summary_queue.put(item)
        print(f"[summary-worker] re-queued {len(items)} items due to token limit adjustment", file=sys.stderr)
    except Exception as e:
        print(f"[summary-worker] failed to re-queue items: {e}", file=sys.stderr)


def peek_queue_for_same_session(session_name: str, max_tokens: Optional[int] = None) -> List[Dict[str, Any]]:
    """
    Peek at the queue and collect additional items for the same session 
    that will fit within the token limit.
    
    Returns a list of queue items that should be batched together.
    """
    if max_tokens is None:
        max_tokens = get_current_token_limit()
    
    batched_items = []
    estimated_tokens = 0
    
    # We need to peek at items without removing them initially
    # Since queue.Queue doesn't have a peek method, we'll collect items
    # and put back any we can't use
    items_to_put_back = []
    
    try:
        while not _summary_queue.empty():
            try:
                # Get item with very short timeout to avoid blocking
                item = _summary_queue.get_nowait()
            except:
                break
                
            # If it's not for the same session, put it back and stop
            if item["session_name"] != session_name:
                items_to_put_back.append(item)
                break
            
            # Estimate tokens for this item
            event = item["event"]
            old_summary = item["old_summary"]
            
            # Rough token estimation for the event content
            event_text = ""
            if event.get("inputs"):
                event_text += json.dumps(event["inputs"])
            if event.get("outputs"):
                event_text += json.dumps(event["outputs"])
            
            # Use the new Event structure fields for context
            event_text += event.get("current_task", "")
            event_text += event.get("summary_of_what_we_just_did", "")
            event_text += event.get("summary_of_what_we_about_to_do", "")
            event_text += event.get("type", "")
            
            item_tokens = estimate_tokens(old_summary + event_text)
            
            # If adding this item would exceed our limit, put it back and stop
            if estimated_tokens + item_tokens > max_tokens:
                items_to_put_back.append(item)
                break
            
            # Add to batch
            batched_items.append(item)
            estimated_tokens += item_tokens
            
            # Mark this item as done since we're consuming it
            _summary_queue.task_done()
            
    except Exception as e:
        print(f"[summary-worker] error while batching: {e}", file=sys.stderr)
    
    # Put back any items we couldn't use
    for item in reversed(items_to_put_back):  # Reverse to maintain order
        _summary_queue.put(item)
    
    print(f"[summary-worker] batched {len(batched_items)} items for session {session_name} (~{estimated_tokens} tokens, limit: {max_tokens})", file=sys.stderr)
    return batched_items


def format_batched_events(events_data: List[Dict[str, Any]]) -> str:
    """Format multiple events into a single text block for the LLM"""
    if not events_data:
        return ""
    
    formatted_events = []
    
    for i, item in enumerate(events_data, 1):
        event = item["event"]
        
        # Prepare input and output text for this event
        input_text = ""
        output_text = ""
        
        try:
            if event.get("inputs"):
                for key, value in event["inputs"].items():
                    if isinstance(value, str):
                        input_text += f"{key}: {value}\n"
                    else:
                        input_text += f"{key}: {json.dumps(value)}\n"
            
            if event.get("outputs"):
                for key, value in event["outputs"].items():
                    if isinstance(value, str):
                        output_text += f"{key}: {value}\n"
                    else:
                        output_text += f"{key}: {json.dumps(value)}\n"
        except Exception as e:
            input_text = f"Error processing inputs: {e}"
            output_text = f"Error processing outputs: {e}"
        
        # Truncate for this event
        try:
            input_summary = truncate_with_indication(input_text.strip(), 256, from_end=False)
            output_summary = truncate_with_indication(output_text.strip(), 256, from_end=True)
        except Exception as e:
            input_summary = input_text[:256] + "..." if len(input_text) > 256 else input_text
            output_summary = output_text[:256] + "..." if len(output_text) > 256 else output_text
        
        # Build the purpose/context from the new Event structure
        purpose_parts = []
        
        # Add current task
        if event.get("current_task"):
            purpose_parts.append(f"Task: {event['current_task']}")
        
        # Add what was just done
        if event.get("summary_of_what_we_just_did"):
            purpose_parts.append(f"Just did: {event['summary_of_what_we_just_did']}")
        
        # Add what's about to be done
        if event.get("summary_of_what_we_about_to_do"):
            purpose_parts.append(f"About to do: {event['summary_of_what_we_about_to_do']}")
        
        # Join the purpose parts or use a fallback
        purpose_text = " | ".join(purpose_parts) if purpose_parts else "No context provided"
        
        event_block = f"""EVENT {i}:
  Type: {event.get('type', '')}
  Purpose: {purpose_text}
  Timestamp: {event.get('timestamp', time.time())}
  Duration: {event.get('duration', 0)}s
  Input Details: {input_summary}
  Output Details: {output_summary}
"""
        formatted_events.append(event_block)
    
    return "\n".join(formatted_events)


def get_llm() -> Optional[Any]:
    """Loads the LLM client; returns None if unavailable."""
    try:
        return Llm.model_named(LLM_MODEL_NAME)
    except Exception as e:
        # Don't log to session since we don't have a session context here
        print(f"[summary-worker] LLM init failed: {e}", file=sys.stderr)
        print(f"[summary-worker] Model: {LLM_MODEL_NAME}", file=sys.stderr)
        print(f"[summary-worker] Python executable: {sys.executable}", file=sys.stderr)
        return None


def _summary_worker() -> None:
    """Background worker that consumes the queue and updates session summaries; robust to errors."""
    global _summary_worker_init_success, _summary_worker_init_error
    
    print(f"[summary-worker] starting background thread with Python: {sys.executable}", file=sys.stderr)
    
    # Initialize LLM and signal results
    try:
        llm = get_llm()
        if llm is None:
            error_msg = f"LLM initialization failed - model '{LLM_MODEL_NAME}' not available"
            print(f"[summary-worker] {error_msg}", file=sys.stderr)
            _summary_worker_init_success = False
            _summary_worker_init_error = error_msg
            _summary_worker_init_event.set()
            return
        
        # Test the LLM with a simple query to ensure it's working
        try:
            test_response = llm.chat("Hello, please respond with 'OK' if you are working.")
            if not test_response or len(test_response.strip()) == 0:
                error_msg = f"LLM test failed - empty response from model '{LLM_MODEL_NAME}'"
                print(f"[summary-worker] {error_msg}", file=sys.stderr)
                _summary_worker_init_success = False
                _summary_worker_init_error = error_msg
                _summary_worker_init_event.set()
                return
        except Exception as e:
            error_msg = f"LLM test failed: {e}"
            print(f"[summary-worker] {error_msg}", file=sys.stderr)
            _summary_worker_init_success = False
            _summary_worker_init_error = error_msg
            _summary_worker_init_event.set()
            return
        
        # Signal successful initialization
        print(f"[summary-worker] LLM successfully initialized", file=sys.stderr)
        _summary_worker_init_success = True
        _summary_worker_init_error = None
        _summary_worker_init_event.set()
        
    except Exception as e:
        error_msg = f"Unexpected error during LLM initialization: {e}"
        print(f"[summary-worker] {error_msg}", file=sys.stderr)
        _summary_worker_init_success = False
        _summary_worker_init_error = error_msg
        _summary_worker_init_event.set()
        return

    # Main worker loop with batching and dynamic token limit adjustment
    while True:
        task = None
        session_name = None
        batched_items = []
        
        try:
            # Get the first task
            task = _summary_queue.get()
            session_name = task["session_name"]
            
            # Now try to batch additional items for the same session using current token limit
            current_limit = get_current_token_limit()
            batched_items = [task] + peek_queue_for_same_session(session_name, current_limit)
            
            print(f"[summary-worker] processing batch of {len(batched_items)} events for session {session_name} (limit: {current_limit})", file=sys.stderr)
            
        except Exception as e:
            print(f"[summary-worker] failed to get task from queue: {e}", file=sys.stderr)
            time.sleep(0.1)
            continue

        retry_count = 0
        max_retries = 3
        
        while retry_count < max_retries:
            try:
                # Use the old_summary from the first item (they should all be similar since they're queued in order)
                old_summary = batched_items[0]["old_summary"]
                
                # Format all events for the LLM
                all_events_text = format_batched_events(batched_items)

                # Prepare the batched prompt
                try:
                    prompt = (
                        "You are updating a technical knowledge base for a software project session. "
                        "This knowledge base will be used by future AI assistants to understand how to work with this specific project. "
                        "Your ONLY job is to extract and organize factual information that will help future work.\n\n"
                        
                        "==== CRITICAL REQUIREMENTS ====\n"
                        "1. FUTURE-FOCUSED: Only include information that helps future LLMs work with this project\n"
                        "2. FACTS ONLY: Document what IS, not what was attempted, tried, or discovered through process\n"
                        "3. NO PROCESS DOCUMENTATION: Don't record commands run, attempts made, or discovery steps\n"
                        "4. NO SUGGESTIONS: Never add ideas, recommendations, next steps, or best practices\n"
                        "5. NO INVENTED INFORMATION: Only include information explicitly found or confirmed\n"
                        "6. STRUCTURE OVER PROCESS: Document final project structure, not how it was discovered\n"
                        "7. ACTIONABLE INFORMATION: Focus on 'how to work with this project' not 'what happened'\n\n"
                        
                        "==== WHAT TO INCLUDE ====\n"
                        "- Project root directory (absolute path)\n"
                        "- Code structure and file organization (as a clear diagram/map)\n"
                        "- Key executable files and how to run them\n"
                        "- Configuration details (dependencies, environment setup, build systems)\n"
                        "- Development workflows (how to build, test, deploy if known)\n"
                        "- Important file locations and their purposes\n"
                        "- Technology stack and frameworks in use\n"
                        "- Any work currently in progress (what specific task is being worked on)\n"
                        "- Gotchas, specific requirements, or constraints that affect how to work with the code\n\n"
                        
                        "==== WHAT TO ABSOLUTELY NEVER INCLUDE ====\n"
                        "- Command execution history or results\n"
                        "- Failed attempts or troubleshooting steps\n"
                        "- 'We tried X but found Y' - just state Y\n"
                        "- Raw command outputs (ls, find results, etc.)\n"
                        "- Suggestions about what to do next\n"
                        "- Warnings, observations, or recommendations you think up\n"
                        "- Best practices or general advice\n"
                        "- 'Challenges encountered' or 'things to be aware of' (unless they came from explicit user input)\n"
                        "- Process descriptions of how information was discovered\n"
                        "- Your own analysis, conclusions, or interpretations beyond the direct facts\n\n"
                        
                        "==== EXAMPLE TRANSFORMATIONS ====\n"
                        "BAD: 'We tried to go to ~/src/project but it failed, then found the code in /Volumes/T9/project'\n"
                        "GOOD: 'Project code located at: /Volumes/T9/project'\n\n"
                        
                        "BAD: 'Ran ls command and found these files: main.py, config.py, tests/'\n"
                        "GOOD: 'Code structure: main.py (entry point), config.py (configuration), tests/ (test suite)'\n\n"
                        
                        "BAD: 'Current progress: successfully read the main.py file and discovered it uses FastAPI'\n"
                        "GOOD: 'Technology: FastAPI web framework'\n\n"
                        
                        "BAD: 'Challenges: no virtual environment found, need to create one'\n"
                        "GOOD: [Don't include this unless a venv was explicitly created/configured]\n\n"
                        
                        "==== BATCH PROCESSING ====\n"
                        f"You are processing {len(batched_items)} events together for efficiency. "
                        "Extract information from ALL events and integrate them into a single updated knowledge base. "
                        "Focus on the final state and cumulative knowledge, not the individual steps.\n\n"
                        
                        "==== YOUR RESPONSE FORMAT ====\n"
                        "Provide a complete technical knowledge base that replaces the previous summary. "
                        "Structure it clearly with specific sections. Use absolute paths. "
                        "Make it immediately actionable for someone who needs to work with this project.\n\n"
                        
                        "==== CURRENT KNOWLEDGE BASE ====\n"
                        f"{old_summary}\n\n"
                        
                        "==== NEW INFORMATION TO INTEGRATE ====\n"
                        f"{all_events_text}\n\n"
                        
                        "Extract only the factual, actionable information from ALL these events and integrate it into "
                        "the knowledge base. Ignore the process of how this information was obtained. "
                        "Focus only on what a future LLM needs to know to work effectively with this project.\n\n"
                        
                        "Updated Knowledge Base:"
                    )
                except Exception as e:
                    log_error(session_name, "_summary_worker", f"failed to prepare batched prompt: {e}")
                    break  # Break out of retry loop, continue to next task

                # Call LLM with the batched prompt
                llm_start_time = time.time()
                response = ""
                error_msg = None
                
                try:
                    response = llm.chat(prompt)
                    new_summary = response.strip()
                    
                    # Only save if the response is substantial (>= 256 characters)
                    if len(new_summary) >= 256:
                        save_session_summary(session_name, new_summary)
                        print(f"[summary-worker] saved updated summary for session {session_name} (batch of {len(batched_items)} events)", file=sys.stderr)
                    else:
                        log_error(session_name, "_summary_worker", f"LLM response too short ({len(new_summary)} chars), not saving")
                    
                    # Success - break out of retry loop
                    break
                        
                except Exception as e:
                    error_msg = str(e)
                    
                    # Check if this is a context length error
                    if "context length" in error_msg.lower():
                        print(f"[summary-worker] context length error detected: {error_msg}", file=sys.stderr)
                        
                        # Try to handle the context length error
                        if handle_context_length_error(error_msg, session_name):
                            # If we successfully adjusted the token limit, we need to re-batch
                            print(f"[summary-worker] re-batching with adjusted token limit", file=sys.stderr)
                            
                            # Re-queue the items that were in this batch (except the first one which we'll retry)
                            if len(batched_items) > 1:
                                requeue_items(batched_items[1:])
                                # Update batched_items to just the first item
                                batched_items = [batched_items[0]]
                            
                            # Retry with the adjusted limit
                            retry_count += 1
                            continue
                        else:
                            # If we couldn't handle the error, log it and break
                            log_error(session_name, "_summary_worker", f"failed to handle context length error: {error_msg}")
                            break
                    else:
                        # Not a context length error, log and break
                        log_error(session_name, "_summary_worker", f"llm.chat failed for batch: {error_msg}")
                        print(f"[summary-worker] llm.chat failed for session {session_name} batch: {e}", file=sys.stderr)
                        break
                
                finally:
                    # Log the LLM interaction for the batch
                    try:
                        llm_duration = time.time() - llm_start_time
                        log_llm_interaction(session_name, prompt, response, llm_duration, error_msg)
                    except Exception as e:
                        log_error(session_name, "_summary_worker", f"failed to log LLM interaction: {e}")

            except Exception as e:
                log_error(session_name or "unknown", "_summary_worker", f"unexpected error in summary worker batch: {e}")
                print(f"[summary-worker] unexpected error: {e}", file=sys.stderr)
                break  # Break out of retry loop
        
        # Final cleanup - mark the first task as done 
        # (others were either marked done during batching or re-queued)
        try:
            _summary_queue.task_done()
        except Exception as e:
            print(f"[summary-worker] failed to mark task done: {e}", file=sys.stderr)


def ensure_summary_thread() -> None:
    """Ensures the background summary thread is started exactly once."""
    global _summary_thread_started
    with _summary_thread_started_lock:
        if not _summary_thread_started:
            thread = threading.Thread(target=_summary_worker, daemon=True)
            thread.start()
            _summary_thread_started = True
            print(f"[summary-worker] background thread started with Python: {sys.executable}", file=sys.stderr)


def wait_for_summary_worker_init(timeout: float = 10.0) -> bool:
    """
    Wait for the summary worker to complete initialization.
    
    Args:
        timeout: Maximum time to wait in seconds
        
    Returns:
        True if initialization succeeded, False if it failed or timed out
        
    Raises:
        RuntimeError: If initialization failed with an error message
    """
    global _summary_worker_init_success, _summary_worker_init_error
    
    if not _summary_worker_init_event.wait(timeout):
        raise RuntimeError(f"Summary worker initialization timed out after {timeout} seconds")
    
    if _summary_worker_init_success is False:
        error_msg = _summary_worker_init_error or "Unknown initialization error"
        raise RuntimeError(f"Summary worker initialization failed: {error_msg}")
    
    if _summary_worker_init_success is None:
        raise RuntimeError("Summary worker initialization completed but status is unknown")
        
    return True
