"""
Application configuration via Pydantic Settings.
All values are loaded from environment variables or a .env file.
"""

from pathlib import Path
from functools import lru_cache
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Global application settings."""

    # ── App ──────────────────────────────────────────────
    app_name: str = "Clinical GraphRAG Pro"
    app_version: str = "1.0.0"
    debug: bool = False

    # ── API ──────────────────────────────────────────────
    api_prefix: str = "/api"
    cors_origins: list[str] = [
        "*",
    ]

    # ── Database ─────────────────────────────────────────
    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/clinical_graphrag"

    # ── Redis ────────────────────────────────────────────
    redis_url: str = "redis://localhost:6379/0"
    cache_ttl: int = 3600  # seconds

    # ── LLM Providers ────────────────────────────────────
    groq_api_key: str = ""
    groq_model: str = "llama-3.3-70b-versatile"

    google_api_key: str = ""
    gemini_model: str = "gemini-2.0-flash"

    # ── RAG Settings ─────────────────────────────────────
    chunk_size: int = 512
    chunk_overlap: int = 64
    top_k: int = 5
    embedding_model: str = "sentence-transformers/all-mpnet-base-v2"

    # ── Advanced RAG ─────────────────────────────────────
    reranker_model: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"
    use_reranking: bool = True
    use_query_expansion: bool = True
    use_hybrid_search: bool = True

    # ── Fine-Tuning ──────────────────────────────────────
    fine_tune_base_model: str = "unsloth/Meta-Llama-3.1-8B-bnb-4bit"
    lora_rank: int = 16
    lora_alpha: int = 32
    learning_rate: float = 2e-4
    num_epochs: int = 3
    max_seq_length: int = 2048
    adapters_dir: Path = Path("./data/adapters")

    # ── Auth & Security ──────────────────────────────────
    jwt_secret: str = "clinical-graphrag-secret-change-in-prod"
    jwt_expire_minutes: int = 480
    rate_limit_enabled: bool = True
    rate_limit_per_minute: int = 60

    # ── LLM Abstraction ──────────────────────────────────
    llm_provider: str = "gemini"  # groq | gemini
    llm_model: str = "gemini-2.0-flash"
    embedding_dim: int = 768

    # ── File Storage ─────────────────────────────────────
    upload_dir: Path = Path("./uploads")
    max_upload_size_mb: int = 50

    # ── WebSocket ────────────────────────────────────────
    ws_heartbeat_interval: int = 30  # seconds

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "case_sensitive": False,
    }


@lru_cache
def get_settings() -> Settings:
    """Cached singleton for settings."""
    return Settings()
