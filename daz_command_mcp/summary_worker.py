#!/usr/bin/env python3
"""
LLM Summary Worker for DAZ Command MCP Server
"""

from __future__ import annotations

import json
import sys
import time
import threading
from typing import Any, Dict, Optional

from dazllm import Llm

from .models import (
    LLM_MODEL_NAME, _summary_queue, _summary_thread_started,
    _summary_thread_started_lock, Event
)
from .utils import save_session_summary, append_error_to_log, truncate_with_indication, get_session_dir


def log_llm_interaction(session_name: str, prompt: str, response: str, duration: float, error: Optional[str] = None) -> None:
    """Log LLM interaction to llm.json file in session directory"""
    try:
        session_dir = get_session_dir(session_name)
        session_dir.mkdir(parents=True, exist_ok=True)
        llm_log_path = session_dir / "llm.json"
        
        log_entry = {
            "timestamp": time.time(),
            "prompt": prompt,
            "response": response,
            "duration": duration,
            "error": error,
            "prompt_length": len(prompt),
            "response_length": len(response)
        }
        
        # Append as JSON line
        with llm_log_path.open("a", encoding="utf-8") as f:
            json.dump(log_entry, f, ensure_ascii=False)
            f.write("\n")
    except Exception as e:
        print(f"[summary-worker] failed to log LLM interaction: {e}", file=sys.stderr)


def enqueue_summary(session_name: str, old_summary: str, event: Event) -> None:
    """Enqueue a summary update task"""
    payload = {
        "session_name": session_name,
        "old_summary": old_summary,
        "event": event,
    }
    _summary_queue.put(payload)


def get_llm() -> Optional[Llm]:
    """Loads the LLM client; returns None if unavailable."""
    try:
        return Llm.model_named(LLM_MODEL_NAME)
    except Exception as e:
        print(f"[summary-worker] LLM init failed: {e}", file=sys.stderr)
        return None


def _summary_worker() -> None:
    """Background worker that consumes the queue and updates session summaries; robust to errors."""
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
                "Do NOT be concise - provide a full, detailed summary that captures all important context.\n\n"
                "Current session summary:\n"
                f"{old_summary}\n\n"
                "New event details:\n"
                f"Type: {event.get('type', '')}\n"
                f"Purpose: {event.get('why', '')}\n"
                f"Timestamp: {event.get('timestamp', time.time())}\n"
                f"Duration: {event.get('duration', 0)}s\n"
                f"Input details: {input_summary}\n"
                f"Output details: {output_summary}\n\n"
                "Please provide the updated session summary:"
            )

            # Call LLM with regular chat; failures must not break MCP.
            llm_start_time = time.time()
            response = ""
            error_msg = None
            
            try:
                response = llm.chat(prompt)
                new_summary = response.strip()
                
                # Only save if the response is substantial (>= 256 characters)
                if len(new_summary) >= 256:
                    save_session_summary(session_name, new_summary)
                else:
                    print(f"[summary-worker] LLM response too short ({len(new_summary)} chars), not saving", file=sys.stderr)
                    
            except Exception as e:
                error_msg = str(e)
                error_record = {
                    "timestamp": time.time(),
                    "type": "llm_summary_error",
                    "error": error_msg,
                    "session_name": session_name
                }
                append_error_to_log(session_name, error_record)
                print(f"[summary-worker] llm.chat failed: {e}", file=sys.stderr)
            
            finally:
                # Log the LLM interaction regardless of success/failure
                llm_duration = time.time() - llm_start_time
                log_llm_interaction(session_name, prompt, response, llm_duration, error_msg)

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


def ensure_summary_thread() -> None:
    """Ensures the background summary thread is started exactly once."""
    global _summary_thread_started
    with _summary_thread_started_lock:
        if not _summary_thread_started:
            thread = threading.Thread(target=_summary_worker, daemon=True)
            thread.start()
            _summary_thread_started = True
