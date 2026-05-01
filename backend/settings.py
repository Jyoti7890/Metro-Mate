from __future__ import annotations

import os
from pathlib import Path
from typing import Mapping

from dotenv import dotenv_values


CURRENT_FILE = Path(__file__).resolve()
BACKEND_DIR = CURRENT_FILE.parent
PROJECT_ROOT = BACKEND_DIR.parent
ENV_PATH = PROJECT_ROOT / ".env"
PLACEHOLDER_ENV_VALUES = {
    "SUPABASE_URL": {
        "https://your-project-id.supabase.co",
    },
    "SUPABASE_SERVICE_ROLE_KEY": {
        "your-service-role-key",
        "your-supabase-service-role-key",
    },
    "SUPABASE_KEY": {
        "your-service-role-key",
        "your-supabase-key",
        "your-supabase-service-role-key",
    },
    "APP_SESSION_SECRET": {
        "replace-with-long-random-secret",
        "replace-with-a-long-random-secret",
    },
}


def _clean_env_value(value: str | None) -> str | None:
    if value is None:
        return None

    cleaned_value = value.strip()
    return cleaned_value or None


def load_project_env() -> dict[str, str]:
    if not ENV_PATH.exists():
        return {}

    file_values: dict[str, str] = {}
    for key, raw_value in dotenv_values(ENV_PATH).items():
        cleaned_value = _clean_env_value(raw_value)
        if cleaned_value is not None:
            file_values[key] = cleaned_value

    for key, value in file_values.items():
        if _clean_env_value(os.getenv(key)) is None:
            os.environ[key] = value

    return file_values


def is_placeholder_env_value(name: str, value: str | None) -> bool:
    cleaned_value = _clean_env_value(value)
    if cleaned_value is None:
        return False

    return cleaned_value.lower() in {
        placeholder.lower()
        for placeholder in PLACEHOLDER_ENV_VALUES.get(name, set())
    }


def get_env_value(
    name: str,
    file_values: Mapping[str, str] | None = None,
    allow_placeholder: bool = True,
) -> str | None:
    if file_values is None:
        file_values = load_project_env()

    resolved_value = _clean_env_value(os.getenv(name)) or _clean_env_value(file_values.get(name))
    if not allow_placeholder and is_placeholder_env_value(name, resolved_value):
        return None

    return resolved_value


def missing_supabase_message(missing_names: list[str]) -> str:
    missing_values = ", ".join(missing_names)
    return (
        f"Missing required Supabase setting(s): {missing_values}. "
        f"For local development, add them to {ENV_PATH}. "
        "For Render, set them in the service environment variables."
    )


def load_supabase_settings() -> tuple[str, str]:
    file_values = load_project_env()
    supabase_url = get_env_value("SUPABASE_URL", file_values, allow_placeholder=False)
    supabase_key = get_env_value(
        "SUPABASE_SERVICE_ROLE_KEY",
        file_values,
        allow_placeholder=False,
    ) or get_env_value(
        "SUPABASE_KEY",
        file_values,
        allow_placeholder=False,
    )

    missing_names: list[str] = []
    if not supabase_url:
        missing_names.append("SUPABASE_URL")
    if not supabase_key:
        missing_names.append("SUPABASE_SERVICE_ROLE_KEY (or SUPABASE_KEY)")

    if missing_names:
        raise RuntimeError(missing_supabase_message(missing_names))

    return supabase_url, supabase_key
