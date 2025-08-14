#!/usr/bin/env python3
"""
DAZ Command MCP Server Package
"""

# Only import main when explicitly needed
# This avoids loading all dependencies during package import

__all__ = ["main"]

def main():
    """Lazy import and run main to avoid loading dependencies during package import"""
    from .main import main as _main
    return _main()
