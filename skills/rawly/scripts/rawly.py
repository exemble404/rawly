#!/usr/bin/env python3
"""Portable skill entry point; no package installation or PYTHONPATH needed."""

from rawly_core.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
