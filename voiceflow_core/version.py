import re

APP_VERSION = "3.2.1"


def parse_version(value: str) -> tuple[int, ...]:
    """Return the numeric parts of a version string such as ``v3.1.0-beta``."""
    match = re.match(r"\s*v?(\d+(?:\.\d+)*)", value or "")
    if not match:
        return ()
    return tuple(int(part) for part in match.group(1).split("."))


def is_newer_version(latest: str, current: str = APP_VERSION) -> bool:
    latest_parts = parse_version(latest)
    current_parts = parse_version(current)
    if not latest_parts or not current_parts:
        return False
    width = max(len(latest_parts), len(current_parts))
    latest_parts += (0,) * (width - len(latest_parts))
    current_parts += (0,) * (width - len(current_parts))
    return latest_parts > current_parts
