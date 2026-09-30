"""Deterministic text personalization that does not require an AI request."""

from __future__ import annotations

import difflib
import re
import string


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


def _is_trivial_word_change(source: str, replacement: str) -> bool:
    source = source.strip(string.punctuation)
    replacement = replacement.strip(string.punctuation)
    return source[1:] == replacement[1:] and source[:1].casefold() == replacement[:1].casefold()


def _is_trivial_change(source: str, replacement: str) -> bool:
    """Edits that only add punctuation or capitalize a first letter make poor rules."""
    source_words, replacement_words = source.split(), replacement.split()
    return len(source_words) == len(replacement_words) and all(
        _is_trivial_word_change(a, b) for a, b in zip(source_words, replacement_words)
    )


def _trim_shared_punctuation(source: str, replacement: str) -> tuple[str, str]:
    while source and replacement and source[-1] == replacement[-1] and source[-1] in string.punctuation:
        source, replacement = source[:-1], replacement[:-1]
    while source and replacement and source[0] == replacement[0] and source[0] in string.punctuation:
        source, replacement = source[1:], replacement[1:]
    return source, replacement


def suggest_replacements(
    original: str,
    corrected: str,
    existing_rules: str = "",
    max_words: int = 4,
    limit: int = 5,
) -> list[dict[str, str]]:
    """Suggest ``spoken => replacement`` rules from a user's correction of a transcript.

    Only short word-for-word substitutions are suggested (e.g. "docker compose" ->
    "docker-compose"); rewording whole sentences does not produce rules.
    """
    before = (original or "").split()
    after = (corrected or "").split()
    known = {spoken.casefold() for spoken, _ in parse_rules(existing_rules)}
    suggestions: list[dict[str, str]] = []

    matcher = difflib.SequenceMatcher(a=before, b=after, autojunk=False)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag != "replace" or not (0 < i2 - i1 <= max_words and 0 < j2 - j1 <= max_words):
            continue
        source, replacement = _trim_shared_punctuation(" ".join(before[i1:i2]), " ".join(after[j1:j2]))
        if not source or not replacement or "=>" in source or "=>" in replacement:
            continue
        if _is_trivial_change(source, replacement) or source.casefold() in known:
            continue
        known.add(source.casefold())
        suggestions.append({"spoken": source, "replacement": replacement})
        if len(suggestions) >= limit:
            break
    return suggestions
