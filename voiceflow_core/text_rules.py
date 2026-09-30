"""Deterministic text personalization that does not require an AI request."""

from __future__ import annotations

import re


def parse_rules(value: str) -> list[tuple[str, str]]:
    """Parse one ``spoken => replacement`` rule per line.

    Blank lines and lines beginning with ``#`` are ignored. Invalid lines are
    skipped so one typo cannot break dictation.
    """
    rules: list[tuple[str, str]] = []
    for raw_line in (value or "").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=>" not in line:
            continue
        source, replacement = (part.strip() for part in line.split("=>", 1))
        if source:
            rules.append((source, replacement))
    return rules


def expand_snippet(text: str, rules_text: str) -> str:
    """Expand a snippet when the entire dictated phrase matches its trigger."""
    normalized = text.strip().rstrip(".!?").casefold()
    for trigger, replacement in parse_rules(rules_text):
        if normalized == trigger.strip().rstrip(".!?").casefold():
            return replacement
    return text


def apply_replacements(text: str, rules_text: str) -> str:
    """Apply case-insensitive whole-phrase replacements in declaration order."""
    result = text
    for spoken, replacement in parse_rules(rules_text):
        pattern = re.compile(rf"(?<!\w){re.escape(spoken)}(?!\w)", re.IGNORECASE)
        result = pattern.sub(lambda _match, value=replacement: value, result)
    return result
