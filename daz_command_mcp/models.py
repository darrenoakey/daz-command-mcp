#!/usr/bin/env python3
"""
Models, types, and constants for DAZ Command MCP Server
"""

from __future__ import annotations

import threading
import queue
from pathlib import Path
from typing import Any, Dict, Optional, TypedDict


# --- Constants ---
# Comment: Sets the model once; if LM Studio isn't running or model missing, the summariser will log and skip.
LLM_MODEL_NAME = "lm-studio:openai/gpt-oss-20b"

# Comment: Resolve script directory and sessions path.
SCRIPT_DIR = Path(__file__).resolve().parent
SESSIONS_DIR = SCRIPT_DIR / "sessions"


# --- Global State ---
# Comment: Global state for active session selection and thread safety.
_active_session_name_lock = threading.Lock()
_active_session_name: Optional[str] = None

# Comment: In-memory queue and worker thread for asynchronous summarisation.
_summary_queue: "queue.Queue[Dict[str, Any]]" = queue.Queue()
_summary_thread_started = False
_summary_thread_started_lock = threading.Lock()

# Comment: Summary worker initialization signaling
_summary_worker_init_event = threading.Event()
_summary_worker_init_success: Optional[bool] = None
_summary_worker_init_error: Optional[str] = None


# --- TypedDicts ---
# Comment: Event payload recorded to the session file.
class Event(TypedDict, total=False):
    timestamp: float
    type: str
    why: str
    inputs: Dict[str, Any]
    outputs: Dict[str, Any]
    duration: float
