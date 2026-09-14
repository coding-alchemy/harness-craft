#!/usr/bin/env python3
"""Local, read-only Harness token accounting entry point."""
import sys

sys.dont_write_bytecode = True

from token_audit.cli import main

if __name__ == "__main__":
    sys.exit(main())
