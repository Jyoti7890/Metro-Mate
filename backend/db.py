import os
from pathlib import Path

from supabase import Client, create_client

try:
    from backend.settings import get_env_value, load_project_env, missing_supabase_message
except ImportError:
    from settings import get_env_value, load_project_env, missing_supabase_message


ENV_PATH = Path(__file__).resolve().parents[1] / ".env"


def _mask_secret(value: str | None) -> str:
    if not value:
        return "None"
    if len(value) <= 8:
        return "*" * len(value)
    return f"{value[:4]}...{value[-4:]}"


def load_supabase_settings() -> tuple[str, str]:
    print(f"[supabase] Looking for .env at: {ENV_PATH}")
    print(f"[supabase] .env exists: {ENV_PATH.exists()}")

    file_values = load_project_env()
    print(f"[supabase] .env keys loaded: {', '.join(sorted(file_values)) or 'none'}")

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

    print(f"[supabase] SUPABASE_URL loaded: {bool(supabase_url)}")
    print(f"[supabase] SUPABASE_KEY is None: {supabase_key is None}")
    print(f"[supabase] SUPABASE_KEY preview: {_mask_secret(supabase_key)}")

    missing_values: list[str] = []
    if not supabase_url:
        missing_values.append("SUPABASE_URL")
    if not supabase_key:
        missing_values.append("SUPABASE_SERVICE_ROLE_KEY (or SUPABASE_KEY)")
    if missing_values:
        raise ValueError(missing_supabase_message(missing_values))

    return supabase_url, supabase_key


SUPABASE_URL, SUPABASE_KEY = load_supabase_settings()
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

print("[supabase] Supabase client initialized successfully")
