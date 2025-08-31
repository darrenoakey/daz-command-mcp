#!/usr/bin/env python3
"""
LLM Summary Worker for DAZ Command MCP Server - REFACTORED VERSION
Now uses the separated SummaryGenerator for LLM logic while handling worker management.
"""

from __future__ import annotations

import json
import sys
import time
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional

from .models import (
    LLM_MODEL_NAME, _summary_queue, _summary_thread_started,
    _summary_thread_started_lock, _summary_worker_init_event,
    _summary_worker_init_success, _summary_worker_init_error, Event
)
from .utils import save_session_summary, get_session_dir
from .summary_generator import SummaryGenerator, _dazllm_available

# Global token limit management
_current_token_limit = 30000  # Default starting limit
_token_limit_lock = threading.Lock()

# Global summary generator instance
_summary_generator = None
_generator_lock = threading.Lock()

# Summary system availability flag
_summary_system_available = False
_summary_worker_should_start = _dazllm_available


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


def is_summary_system_available() -> bool:
    """Check if the summary system is available and functional"""
    return _summary_system_available


def should_start_summary_worker() -> bool:
    """Check if the summary worker should be started at all"""
    return _summary_worker_should_start


def is_summary_queue_empty() -> bool:
    """Check if the summary queue is empty"""
    if not _summary_worker_should_start:
        return True  # Consider it empty if worker doesn't exist
    return _summary_queue.empty()


def get_summary_queue_size() -> int:
    """Get the approximate size of the summary queue"""
    if not _summary_worker_should_start:
        return 0  # No queue if no worker
    return _summary_queue.qsize()


def wait_for_summary_queue_empty(timeout: float = 30.0) -> bool:
    """
    Wait for the summary queue to become empty.
    
    Args:
        timeout: Maximum time to wait in seconds
        
    Returns:
        True if queue became empty within timeout, False otherwise
    """
    if not _summary_worker_should_start:
        return True  # No queue to wait for if no worker
        
    start_time = time.time()
    
    while time.time() - start_time < timeout:
        if is_summary_queue_empty():
            return True
        time.sleep(0.5)  # Check every 500ms
    
    return False


def handle_context_length_error(error_message: str, session_name: str) -> bool:
    """
    Handle a context length error by adjusting the token limit.
    
    Returns True if the limit was adjusted, False otherwise.
    """
    try:
        # Use the generator's method to extract context length
        global _summary_generator
        if _summary_generator is None:
            return False
            
        context_length = _summary_generator.extract_context_length_from_error(error_message)
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
    # Complete no-op if summary worker shouldn't exist
    if not _summary_worker_should_start:
        return
        
    # Only enqueue if summary system is available
    if not _summary_system_available:
        return
        
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
            
            # Estimate tokens for this item using the generator's method
            global _summary_generator
            if _summary_generator is None:
                # Fallback estimation
                item_tokens = len(json.dumps(item)) // 4
            else:
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
                
                item_tokens = _summary_generator.estimate_tokens(old_summary + event_text)
            
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


def get_summary_generator() -> Optional[SummaryGenerator]:
    """Get the global summary generator instance"""
    global _summary_generator
    with _generator_lock:
        return _summary_generator


def _summary_worker() -> None:
    """Background worker that consumes the queue and updates session summaries; robust to errors."""
    global _summary_worker_init_success, _summary_worker_init_error, _summary_generator, _summary_system_available
    
    print(f"[summary-worker] starting background thread with Python: {sys.executable}", file=sys.stderr)
    
    # Initialize the summary generator
    try:
        with _generator_lock:
            _summary_generator = SummaryGenerator(LLM_MODEL_NAME)
        
        # Try to initialize the LLM
        init_success = _summary_generator.initialize()
        
        if not init_success:
            error_msg = _summary_generator.init_error or "Unknown initialization error"
            print(f"[summary-worker] {error_msg}", file=sys.stderr)
            _summary_worker_init_success = False
            _summary_worker_init_error = error_msg
            _summary_worker_init_event.set()
            return
        
        # Signal successful initialization
        print(f"[summary-worker] LLM successfully initialized", file=sys.stderr)
        _summary_worker_init_success = True
        _summary_worker_init_error = None
        _summary_system_available = True
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
                
                # Generate the summary using the new generator
                result = _summary_generator.generate_summary(old_summary, batched_items)
                
                # Log the LLM interaction
                log_llm_interaction(
                    session_name, 
                    result.get("prompt", ""), 
                    result.get("response", ""), 
                    result.get("duration", 0.0), 
                    result.get("error")
                )
                
                if result["success"]:
                    # Save the new summary
                    save_session_summary(session_name, result["summary"])
                    print(f"[summary-worker] saved updated architecture document for session {session_name} (batch of {len(batched_items)} events)", file=sys.stderr)
                    break  # Success - break out of retry loop
                else:
                    error_msg = result["error"]
                    
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
                        log_error(session_name, "_summary_worker", f"summary generation failed: {error_msg}")
                        print(f"[summary-worker] summary generation failed for session {session_name}: {error_msg}", file=sys.stderr)
                        break

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
    
    # Don't start thread at all if LLM not available
    if not _summary_worker_should_start:
        print("[summary-worker] LLM not available - skipping summary worker thread creation", file=sys.stderr)
        return
    
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
    
    # If worker shouldn't start, consider initialization successful (no worker needed)
    if not _summary_worker_should_start:
        print("[summary-worker] No summary worker needed - LLM not available", file=sys.stderr)
        return True
    
    if not _summary_worker_init_event.wait(timeout):
        raise RuntimeError(f"Summary worker initialization timed out after {timeout} seconds")
    
    if _summary_worker_init_success is False:
        error_msg = _summary_worker_init_error or "Unknown initialization error"
        raise RuntimeError(f"Summary worker initialization failed: {error_msg}")
    
    if _summary_worker_init_success is None:
        raise RuntimeError("Summary worker initialization completed but status is unknown")
        
    return True
