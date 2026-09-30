"""Writing profiles: a style, instructions, and AI Polish choice for specific apps."""

from __future__ import annotations

import os
import sys
import uuid
from typing import Any, Iterable, Optional

from voiceflow_core.llm import WRITING_STYLE_PROMPTS

# "default" means "use the main setting from the dashboard".
PROFILE_STYLES = {"default", *WRITING_STYLE_PROMPTS}
PROFILE_AI_POLISH = {"default", "on", "off"}
MAX_PROFILES = 50
MAX_APPS_PER_PROFILE = 50


def normalize_app_name(name: str) -> str:
    """Turn 'Slack', 'slack.exe' or a full path into the process name we detect."""
    name = os.path.basename((name or "").strip().strip('"')).lower()
    if name and sys.platform == "win32" and not name.endswith(".exe"):
        name += ".exe"
    return name


def _text(value: Any, label: str, max_length: int) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{label} must be text")
    value = value.strip()
    if len(value) > max_length:
        raise ValueError(f"{label} is too long")
    return value


def parse_profiles(value: Any) -> list[dict]:
    """Validate writing profiles from the dashboard or config file. Raises ValueError."""
    if not isinstance(value, list):
        raise ValueError("Writing profiles must be a list")
    if len(value) > MAX_PROFILES:
        raise ValueError(f"You can have at most {MAX_PROFILES} writing profiles")

    profiles = []
    owners: dict[str, str] = {}
    for index, raw in enumerate(value, start=1):
        if not isinstance(raw, dict):
            raise ValueError(f"Writing profile {index} is invalid")
        name = _text(raw.get("name", ""), "Profile name", 100) or f"Profile {index}"

        style = raw.get("writing_style", "default")
        if style not in PROFILE_STYLES:
            raise ValueError(f'"{name}" has an unknown writing style')
        ai_polish = raw.get("ai_polish", "default")
        if ai_polish not in PROFILE_AI_POLISH:
            raise ValueError(f'"{name}" has an unknown AI Polish choice')

        apps_value = raw.get("apps", [])
        if not isinstance(apps_value, list) or len(apps_value) > MAX_APPS_PER_PROFILE:
            raise ValueError(f'"{name}" has an invalid app list')
        apps = []
        for app in apps_value:
            app = normalize_app_name(_text(app, "App name", 100))
            if not app or app in apps:
                continue
            if app in owners:
                raise ValueError(f'{app} is assigned to both "{owners[app]}" and "{name}"')
            owners[app] = name
            apps.append(app)

        profiles.append({
            "id": _text(str(raw.get("id") or ""), "Profile id", 64) or f"profile_{uuid.uuid4().hex[:12]}",
            "name": name,
            "apps": apps,
            "writing_style": style,
            "ai_polish": ai_polish,
            "instructions": _text(raw.get("instructions", ""), "Profile instructions", 4000),
        })
    return profiles


def profile_for_app(profiles: Iterable[dict], process_name: str) -> Optional[dict]:
    """Return the profile assigned to the given process, if any."""
    process_name = (process_name or "").lower()
    if not process_name:
        return None
    for profile in profiles or []:
        if process_name in profile.get("apps", []):
            return profile
    return None
