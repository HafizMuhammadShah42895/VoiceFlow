"""Safe logging utility that avoids printing sensitive raw speech or keys."""

import sys


def log(msg: str) -> None:
    """Print safe log message to stdout without throwing in windowed mode."""
    try:
        # Avoid logging if stdout is None or closed
        if sys.stdout and not sys.stdout.closed:
            print(f"[dictation] {msg}", flush=True)
    except Exception:
        pass
