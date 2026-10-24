from pathlib import Path
from typing import Literal
from functools import lru_cache
from pydantic import model_validator, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT / ".env", extra="ignore")
    app_host: str = "127.0.0.1"
    app_port: int = 8000
    data_dir: Path = ROOT / "data"
    database_url: str | None = None
    allowed_origins: str = (
        "http://127.0.0.1:5173,http://localhost:5173,http://127.0.0.1:8000,http://localhost:8000"
    )
    gemini_api_key: str = Field(default="", repr=False)
    gemini_model: str = "gemini-3.1-flash-lite"
    gemini_api_surface: str = "interactions"
    video_processing_mode: str = "static"
    enable_agentic_video: bool = False
    gemini_store_interactions: bool = False
    ai_provider: str = "gemini"
    max_upload_mb: int = Field(default=500, gt=0)
    max_video_seconds: float = Field(default=1200, gt=0)
    max_video_pixels: int = Field(default=8294400, gt=0)
    max_project_storage_mb: int = Field(default=5000, gt=0)
    worker_concurrency: int = 1
    chunk_seconds: float = Field(default=300, gt=0)
    chunk_overlap_seconds: float = Field(default=5, ge=0)
    video_fps: float = Field(default=1, gt=0, le=30)
    max_output_tokens: int = Field(default=16384, gt=0, le=65536)
    max_steps: int = Field(default=80, gt=0, le=80)
    max_screenshots: int = Field(default=40, ge=0, le=40)
    max_generation_attempts: int = Field(default=12, gt=0)
    max_json_repair_requests: int = Field(default=1, ge=0, le=1)
    max_estimated_job_cost_usd: float = Field(default=1, gt=0)
    job_timeout_seconds: int = Field(default=2700, gt=0)
    provider_request_timeout_seconds: int = Field(default=300, gt=0)
    keep_raw_provider_output: bool = False
    verify_window_seconds: float = Field(default=5, ge=0, le=60)
    verify_text_threshold: int = Field(default=85, ge=0, le=100)
    verify_max_ocr_frames: int = Field(default=3, ge=1, le=10)
    asr_engine: Literal["faster-whisper", "none"] = "faster-whisper"
    asr_model: str = "small"
    asr_timeout_seconds: int = Field(default=1200, gt=0)
    ocr_engine: Literal["paddleocr", "none"] = "paddleocr"
    ocr_timeout_seconds: int = Field(default=300, gt=0)

    @model_validator(mode="after")
    def validate_settings(self):
        self.data_dir = self.data_dir.expanduser().absolute()
        if self.chunk_overlap_seconds >= self.chunk_seconds:
            raise ValueError("Overlap must be smaller than chunk duration")
        if (
            self.enable_agentic_video
            or self.video_processing_mode != "static"
            or self.gemini_store_interactions
        ):
            raise ValueError("FEATURE_NOT_IMPLEMENTED: only static, store=false is supported")
        if self.worker_concurrency != 1 or self.gemini_api_surface != "interactions":
            raise ValueError("FEATURE_NOT_IMPLEMENTED: one worker and Interactions required")
        if self.ai_provider not in ("gemini", "mock"):
            raise ValueError("AI_PROVIDER must be gemini or mock")
        if self.app_host not in ("127.0.0.1", "localhost"):
            raise ValueError("LAN_PUBLIC_NOT_SUPPORTED: bind localhost only")
        if self.keep_raw_provider_output:
            raise ValueError("FEATURE_NOT_IMPLEMENTED: raw provider debug retention is disabled")
        if self.database_url is None:
            self.database_url = "sqlite:///" + str(self.data_dir / "app.sqlite3")
        db_path = Path(self.database_url.removeprefix("sqlite:///")).absolute()
        if (
            not self.database_url.startswith("sqlite:///")
            or db_path.parent.resolve() != self.data_dir.resolve()
        ):
            raise ValueError("Database must be SQLite inside DATA_DIR")
        return self

    @property
    def origins(self):
        return [x.strip() for x in self.allowed_origins.split(",") if x.strip()]

    def snapshot(self):
        return self.model_dump(mode="json", exclude={"gemini_api_key", "database_url", "data_dir"})


@lru_cache
def get_settings():
    return Settings()
