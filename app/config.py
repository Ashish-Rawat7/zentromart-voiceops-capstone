from __future__ import annotations
import os
from pathlib import Path
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(PROJECT_ROOT / ".env")

def env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}

def resolve_path(value: str, default: str) -> Path:
    raw = Path(os.getenv(value, default)).expanduser()
    return (PROJECT_ROOT / raw).resolve() if not raw.is_absolute() else raw.resolve()

class Settings:
    app_name = "ZentroMart Support Agent"
    app_version = "3.0.0"
    dataset_dir = resolve_path("DATASET_DIR", "./Capstone_Project_Dataset_FTTT_2026")
    session_db_path = resolve_path("SESSION_DB_PATH", "./instance/sessions.sqlite3")
    gemini_api_key = os.getenv("GEMINI_API_KEY", "").strip()
    gemini_model = os.getenv("GEMINI_MODEL", "gemini-2.5-flash").strip()
    gnani_api_key = os.getenv("GNANI_API_KEY", "").strip()
    voice_stt_language = os.getenv("VOICE_STT_LANGUAGE", "en-IN").strip()
    voice_tts_model = os.getenv("VOICE_TTS_MODEL", "timbre-v2.5").strip()
    voice_tts_name = os.getenv("VOICE_TTS_NAME", "Kaveri").strip()
    voice_tts_language = os.getenv("VOICE_TTS_LANGUAGE", "en-IN").strip()
    enable_gemini = env_bool("ENABLE_GEMINI", False)
    cors_origins = [x.strip() for x in os.getenv(
        "CORS_ORIGINS", "http://localhost:8501,http://127.0.0.1:8501"
    ).split(",") if x.strip()]
    max_verification_attempts = 2
    session_ttl_hours = 12
    reference_date = "2026-10-20"

settings = Settings()
