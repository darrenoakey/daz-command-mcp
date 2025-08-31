#!/usr/bin/env python3
"""
DAZ Command MCP Server - Main Entry Point
"""

from __future__ import annotations

import argparse
import signal
import sys
from typing import Any

# Graceful LLM dependency check - allow system to continue without it
_dazllm_available = False
try:
    from dazllm import Llm
    _dazllm_available = True
except ImportError as e:
    print(f"[mcp] dazllm module not available: {e}", file=sys.stderr)
    print(f"[mcp] LLM functionality will be disabled, but other functionality will continue", file=sys.stderr)
    Llm = None

from src.summary_worker import ensure_summary_thread, wait_for_summary_worker_init, is_summary_system_available
from src.mcp_tools import mcp

LLM_MODEL_NAME = "lm-studio:openai/gpt-oss-20b"


def main() -> None:
    """Main entry point for the DAZ Command MCP Server"""
    parser = argparse.ArgumentParser(description="DAZ Command MCP Server")
    # Remove the port argument since MCP servers communicate over stdio
    args = parser.parse_args()

    # Check LLM availability but don't fail if not available
    if _dazllm_available:
        try:
            llm_check = Llm()
            if not llm_check: 
                print("[mcp] LLM check failed - continuing without LLM functionality", file=sys.stderr)
        except Exception as e:
            print(f"[mcp] LLM check error: {e} - continuing without LLM functionality", file=sys.stderr)
    else:
        print("[mcp] dazllm not available - continuing without LLM functionality", file=sys.stderr)

    # Start the summary worker thread
    print("[mcp] starting summary worker...", file=sys.stderr)
    ensure_summary_thread()
    
    # Wait for summary worker initialization but don't fail if it can't initialize LLM
    try:
        print("[mcp] waiting for summary worker initialization...", file=sys.stderr)
        wait_for_summary_worker_init(timeout=30.0)  # 30 second timeout
        
        if is_summary_system_available():
            print("[mcp] summary worker successfully initialized with LLM functionality", file=sys.stderr)
        else:
            print("[mcp] summary worker initialized in no-LLM mode - summaries disabled", file=sys.stderr)
            
    except RuntimeError as e:
        print(f"FATAL ERROR: Summary worker initialization failed: {e}", file=sys.stderr)
        print("[mcp] The MCP server cannot start without a working summary worker", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"FATAL ERROR: Unexpected error during summary worker initialization: {e}", file=sys.stderr)
        sys.exit(1)

    def signal_handler(sig: int, frame: Any) -> None:
        print("\n[mcp] shutting down gracefully...", file=sys.stderr)
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    print("[mcp] starting server over stdio...", file=sys.stderr)
    # Run without port argument - MCP servers communicate over stdio
    mcp.run()


if __name__ == "__main__":
    main()
