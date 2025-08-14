#!/usr/bin/env python3
"""
DAZ Command MCP Server - Main Entry Point
"""

from __future__ import annotations

import argparse
import signal
import sys
from typing import Any

from .summary_worker import ensure_summary_thread
from .mcp_tools import mcp


def main() -> None:
    """Main entry point for the DAZ Command MCP Server"""
    parser = argparse.ArgumentParser(description="DAZ Command MCP Server")
    # Remove the port argument since MCP servers communicate over stdio
    args = parser.parse_args()

    ensure_summary_thread()

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
