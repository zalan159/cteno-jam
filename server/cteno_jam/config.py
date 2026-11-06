"""Runtime configuration, read once from environment variables (see .env.example)."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def _bool(name: str, default: bool) -> bool:
    v = os.environ.get(name)
    if v is None or v == "":
        return default
    return v.strip().lower() in ("1", "true", "yes", "on")


def _int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name) or default)
    except ValueError:
        return default


@dataclass
class Config:
    data_dir: Path = field(default_factory=lambda: Path(os.environ.get("JAM_DATA_DIR", "./data")).resolve())
    web_dir: Path = field(default_factory=lambda: Path(os.environ.get(
        "JAM_WEB_DIR", str(Path(__file__).resolve().parents[2] / "web"))).resolve())
    host: str = field(default_factory=lambda: os.environ.get("JAM_HOST", "0.0.0.0"))
    port: int = field(default_factory=lambda: _int("JAM_PORT", 8765))
    # "full" = upload + processing; "player" = library/player/sync only (no processing, tiny RAM)
    mode: str = field(default_factory=lambda: os.environ.get("JAM_MODE", "full"))
    workers: int = field(default_factory=lambda: max(1, _int("JAM_WORKERS", 1)))
    device: str = field(default_factory=lambda: os.environ.get("JAM_DEVICE", "auto"))  # auto|cpu|cuda|mps
    threads: int = field(default_factory=lambda: _int("JAM_THREADS", 0))
    max_upload_mb: int = field(default_factory=lambda: _int("JAM_MAX_UPLOAD_MB", 200))
    max_duration_s: int = field(default_factory=lambda: _int("JAM_MAX_DURATION_S", 15 * 60))
    demucs_model: str = field(default_factory=lambda: os.environ.get("JAM_DEMUCS_MODEL", "htdemucs_6s"))
    whisper_model: str = field(default_factory=lambda: os.environ.get("JAM_WHISPER_MODEL", "small"))
    lrclib: bool = field(default_factory=lambda: _bool("JAM_LRCLIB", True))
    lrclib_url: str = field(default_factory=lambda: os.environ.get("JAM_LRCLIB_URL", "https://lrclib.net"))
    # Uploading/deleting can be protected by a shared passphrase (header X-Jam-Key or ?key=)
    admin_key: str = field(default_factory=lambda: os.environ.get("JAM_ADMIN_KEY", ""))
    # Abuse guards for an internet-facing instance (all optional; 0 disables)
    max_queue: int = field(default_factory=lambda: _int("JAM_MAX_QUEUE", 0))                 # songs waiting+processing
    uploads_per_ip_hour: int = field(default_factory=lambda: _int("JAM_UPLOADS_PER_IP_HOUR", 0))
    rate_limit_private: bool = field(default_factory=lambda: _bool("JAM_RATE_LIMIT_PRIVATE", False))  # LAN clients exempt by default
    max_disk_percent: int = field(default_factory=lambda: _int("JAM_MAX_DISK_PERCENT", 0))   # refuse uploads above this
    public_url: str = field(default_factory=lambda: os.environ.get("JAM_PUBLIC_URL", ""))
    # Jamendo free-music search/import (optional): the client id stays on the server; empty hides the feature
    jamendo_client_id: str = field(default_factory=lambda: os.environ.get("JAM_JAMENDO_CLIENT_ID", "").strip())
    jamendo_api_url: str = field(default_factory=lambda: os.environ.get("JAM_JAMENDO_API_URL", "https://api.jamendo.com/v3.0"))

    # AI review (optional): any OpenAI/Anthropic/Gemini-compatible endpoint via the Cteno SDK
    ai_enabled: bool = field(default_factory=lambda: _bool("JAM_AI_REVIEW", True))
    ai_base_url: str = field(default_factory=lambda: os.environ.get("JAM_AI_BASE_URL", "https://api.deepseek.com/v1"))
    ai_model: str = field(default_factory=lambda: os.environ.get("JAM_AI_MODEL", "deepseek-chat"))
    ai_api_format: str = field(default_factory=lambda: os.environ.get("JAM_AI_API_FORMAT", "openai"))
    ai_api_key: str = field(default_factory=lambda: os.environ.get("JAM_AI_API_KEY") or os.environ.get("DEEPSEEK_API_KEY", ""))
    ai_timeout_s: int = field(default_factory=lambda: _int("JAM_AI_TIMEOUT_S", 300))
    ai_sdk_home: str = field(default_factory=lambda: os.environ.get("CTENO_SDK_HOME", ""))

    @property
    def songs_dir(self) -> Path:
        return self.data_dir / "songs"

    @property
    def ai_configured(self) -> bool:
        return self.ai_enabled and bool(self.ai_api_key)

    @property
    def processing(self) -> bool:
        return self.mode == "full"

    @property
    def jamendo(self) -> bool:
        return self.processing and bool(self.jamendo_client_id)


_cfg: Config | None = None


def get() -> Config:
    global _cfg
    if _cfg is None:
        _cfg = Config()
    return _cfg


def reset(**over) -> Config:
    """Tests: rebuild from env and override fields."""
    global _cfg
    _cfg = Config()
    for k, v in over.items():
        setattr(_cfg, k, v)
    return _cfg
