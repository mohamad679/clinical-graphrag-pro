"""
Application configuration via Pydantic Settings.
All values are loaded from environment variables or a .env file.
"""

import json
from pathlib import Path
from functools import lru_cache
from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings

INSECURE_JWT_DEFAULT = "clinical-graphrag-secret-change-in-prod"
ALLOWED_APP_ENVS = {"development", "staging", "production"}
ALLOWED_VECTOR_BACKENDS = {"faiss", "qdrant"}
ALLOWED_LLM_PROVIDERS = {"groq", "gemini", "ollama", "local_hf", "llama_cpp", "retrieval-only"}
ALLOWED_STREAM_MODES = {"safe"}
ALLOWED_OBSERVABILITY_MODES = {
    "LOCAL_SYNTHETIC_DEBUG",
    "STAGING_REDACTED",
    "PRODUCTION_METADATA_ONLY",
}
DEVELOPMENT_ONLY_VALUES = {
    "postgres",
    "password",
    "changeme",
    "change-this-password",
    "neo4jpassword",
}
DISCLAIMER_TEXT = (
    "Clinical GraphRAG Pro provides decision support only. "
    "It does not replace clinician judgment, primary literature review, "
    "or institution-specific protocols."
)


class Settings(BaseSettings):
    """Global application settings."""

    # ── App ──────────────────────────────────────────────
    app_name: str = "Clinical GraphRAG Pro"
    app_version: str = "1.0.0"
    app_env: str = "development"
    debug: bool = False
    log_level: str = "INFO"
    observability_mode: str = "LOCAL_SYNTHETIC_DEBUG"
    internal_full_trace_enabled: bool = False

    # ── API ──────────────────────────────────────────────
    api_prefix: str = "/api"
    cors_origins: list[str] | str = ["http://localhost:3000", "http://127.0.0.1:3000"]
    cors_allow_credentials: bool = True
    cors_allow_methods: list[str] | str = ["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"]
    cors_allow_headers: list[str] | str = ["Authorization", "Content-Type", "Accept", "Origin"]

    # ── Database ─────────────────────────────────────────
    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/clinical_graphrag"
    auto_migrate_on_startup: bool = True

    # ── Redis ────────────────────────────────────────────
    redis_url: str = "redis://localhost:6379/0"
    cache_ttl: int = 3600  # seconds
    celery_task_always_eager: bool = False
    celery_task_store_eager_result: bool = False
    background_jobs_require_broker: bool = False
    background_job_default_max_retries: int = 3
    background_job_retry_backoff_seconds: int = 30
    background_job_retry_backoff_max_seconds: int = 900
    document_processing_timeout_seconds: int = 1800
    evaluation_timeout_seconds: int = 1800
    image_analysis_timeout_seconds: int = 900
    audio_transcription_timeout_seconds: int = 300
    agent_tool_timeout_seconds: int = 30
    agent_workflow_timeout_seconds: int = 180

    # ── LLM Providers ────────────────────────────────────
    groq_api_key: str = ""
    groq_model: str = "llama-3.3-70b-versatile"

    google_api_key: str = ""
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.5-flash-lite"

    # ── RAG Settings ─────────────────────────────────────
    chunk_size: int = 512
    chunk_overlap: int = 64
    top_k: int = 5
    embedding_model: str = "sentence-transformers/all-mpnet-base-v2"
    vector_backend: str = "faiss"
    qdrant_url: str = ""
    qdrant_api_key: str = ""
    qdrant_collection: str = "clinical_graphrag"

    # ── Advanced RAG ─────────────────────────────────────
    reranker_model: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"
    use_reranking: bool = False
    use_query_expansion: bool = True
    use_hybrid_search: bool = True
    chat_history_message_limit: int = 10
    chat_context_max_words: int = 2500
    chat_context_max_chunk_words: int = 350
    chat_low_confidence_threshold: float = 0.6
    chat_stream_chunk_size: int = 80

    # ── Fine-Tuning ──────────────────────────────────────
    enable_fine_tune: bool = False
    fine_tune_base_model: str = "unsloth/Meta-Llama-3.1-8B-bnb-4bit"
    lora_rank: int = 16
    lora_alpha: int = 32
    learning_rate: float = 2e-4
    num_epochs: int = 3
    max_seq_length: int = 2048
    fine_tune_max_validation_loss: float = 2.0
    adapters_dir: Path = Path("./data/adapters")
    vector_store_dir: Path = Path("./data/vector_store")
    scispacy_model: str = "en_core_sci_sm"
    enable_scispacy: bool = False

    # ── Auth & Security ──────────────────────────────────
    jwt_secret: str = ""
    secret_key_min_length: int = 32
    jwt_expire_minutes: int = 480
    refresh_token_expire_days: int = 30
    password_reset_token_expire_minutes: int = 60
    require_email_verification: bool = False
    enable_demo_auth: bool = False
    bootstrap_admin_email: str = ""
    bootstrap_admin_password: str = ""
    bootstrap_admin_name: str = "Administrator"
    rate_limit_enabled: bool = True
    rate_limit_per_minute: int = 60
    rate_limit_trust_forwarded_for: bool = False
    rate_limit_trusted_proxies: list[str] | str = []
    rate_limit_redis_failure_policy: str = "fail_open"
    rate_limit_fail_closed_paths: list[str] | str = ["/api/chat", "/api/eval", "/api/fine-tune"]

    # ── LLM Abstraction ──────────────────────────────────
    llm_provider: str = "gemini"  # groq | gemini | ollama | local_hf | llama_cpp
    llm_model: str = "gemini-2.5-flash-lite"
    embedding_dim: int = 768
    stream_mode: str = "safe"
    llm_max_tokens: int = 2048
    llm_temperature: float = 0.1
    offline_demo_mode: bool = False

    # ── Local LLM Options ────────────────────────────────
    ollama_url: str = "http://localhost:11434"
    llama_cpp_url: str = "http://localhost:8080"
    local_llm_model: str = "llama3"
    local_llm_timeout: float = 60.0

    # ── Caching Options ──────────────────────────────────
    cache_enabled: bool = True
    cache_backend: str = "in-memory"  # in-memory | redis
    cache_ttl: int = 3600


    # ── File Storage ─────────────────────────────────────
    upload_dir: Path = Path("./uploads")
    max_upload_size_mb: int = 50
    storage_provider: str = "local"  # local | s3 | minio
    storage_bucket: str = "clinical-graphrag"
    storage_endpoint_url: str = ""
    storage_access_key: str = ""
    storage_secret_key: str = ""
    storage_region: str = ""
    storage_prefix: str = ""
    storage_use_ssl: bool = True
    storage_encrypt_uploads: bool = False
    static_frontend_dir: Path | None = None
    postgres_fts_config: str = "english"
    document_duplicate_policy: str = "reuse"
    document_enable_pdf_fallback: bool = True
    document_enable_ocr: bool = False
    document_ocr_provider: str = "none"
    document_scanned_pdf_min_chars_per_page: int = 40
    document_embedding_version: str = ""
    image_max_upload_size_mb: int = 50
    image_max_width: int = 10000
    image_max_height: int = 10000
    image_max_pixels: int = 40000000
    image_strip_metadata: bool = True
    image_allow_dicom: bool = False
    image_dicom_policy: str = "reject"
    image_auto_analyze_on_upload: bool = True
    audio_max_upload_size_mb: int = 25
    audio_max_duration_seconds: int = 300
    audio_sync_transcription_max_size_mb: int = 2
    audio_default_language: str = "en"
    audio_allow_auto_language_detection: bool = False
    audio_transcription_provider: str = "groq"
    audio_raw_retention_days: int = 1
    audio_transcript_retention_days: int = 365
    audio_provider_max_retries: int = 2
    audio_provider_retry_backoff_seconds: int = 30

    # ── Neo4j ─────────────────────────────────────────────
    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = "neo4jpassword"
    use_neo4j: bool = False
    graph_seed_enabled: bool = True
    graph_query_default_limit: int = 25
    graph_query_max_limit: int = 200

    # ── WebSocket ────────────────────────────────────────
    ws_heartbeat_interval: int = 30  # seconds
    ws_ticket_ttl_seconds: int = 45
    ws_ticket_allow_memory_fallback: bool = True
    data_retention_days: int = 365
    disclaimer_text: str = DISCLAIMER_TEXT

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "case_sensitive": False,
        "extra": "ignore",
    }

    @field_validator(
        "cors_origins",
        "cors_allow_methods",
        "cors_allow_headers",
        "rate_limit_trusted_proxies",
        "rate_limit_fail_closed_paths",
        mode="before",
    )
    @classmethod
    def _parse_csv_or_json_list(cls, value):
        if isinstance(value, str):
            value = value.strip()
            if not value:
                return []
            if value.startswith("["):
                return json.loads(value)
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    @field_validator("debug", mode="before")
    @classmethod
    def _parse_debug_flag(cls, value):
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in {"release", "production", "prod"}:
                return False
            if normalized in {"debug", "development", "dev"}:
                return True
        return value

    @field_validator("app_env")
    @classmethod
    def _validate_app_env(cls, value: str) -> str:
        if value not in ALLOWED_APP_ENVS:
            allowed = ", ".join(sorted(ALLOWED_APP_ENVS))
            raise ValueError(f"APP_ENV must be one of: {allowed}")
        return value

    @field_validator("log_level")
    @classmethod
    def _validate_log_level(cls, value: str) -> str:
        normalized = value.strip().upper()
        allowed_levels = {"CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG"}
        if normalized not in allowed_levels:
            allowed = ", ".join(sorted(allowed_levels))
            raise ValueError(f"LOG_LEVEL must be one of: {allowed}")
        return normalized

    @field_validator("observability_mode")
    @classmethod
    def _validate_observability_mode(cls, value: str) -> str:
        normalized = value.strip().upper()
        if normalized not in ALLOWED_OBSERVABILITY_MODES:
            allowed = ", ".join(sorted(ALLOWED_OBSERVABILITY_MODES))
            raise ValueError(f"OBSERVABILITY_MODE must be one of: {allowed}")
        return normalized

    @field_validator("vector_backend")
    @classmethod
    def _validate_vector_backend(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in ALLOWED_VECTOR_BACKENDS:
            allowed = ", ".join(sorted(ALLOWED_VECTOR_BACKENDS))
            raise ValueError(f"VECTOR_BACKEND must be one of: {allowed}")
        return normalized

    @field_validator("llm_provider")
    @classmethod
    def _validate_llm_provider(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in ALLOWED_LLM_PROVIDERS:
            allowed = ", ".join(sorted(ALLOWED_LLM_PROVIDERS))
            raise ValueError(f"LLM_PROVIDER must be one of: {allowed}")
        return normalized

    @field_validator("stream_mode")
    @classmethod
    def _validate_stream_mode(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in ALLOWED_STREAM_MODES:
            allowed = ", ".join(sorted(ALLOWED_STREAM_MODES))
            raise ValueError(
                f"STREAM_MODE must be one of: {allowed}. "
                "Unsafe pre-validation streaming is not supported."
            )
        return normalized

    @field_validator("rate_limit_redis_failure_policy")
    @classmethod
    def _validate_rate_limit_failure_policy(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in {"fail_open", "fail_closed"}:
            raise ValueError("RATE_LIMIT_REDIS_FAILURE_POLICY must be fail_open or fail_closed.")
        return normalized

    @field_validator("ws_ticket_ttl_seconds")
    @classmethod
    def _validate_ws_ticket_ttl(cls, value: int) -> int:
        if value < 30 or value > 60:
            raise ValueError("WS_TICKET_TTL_SECONDS must be between 30 and 60 seconds.")
        return value

    @model_validator(mode="after")
    def _validate_security_settings(self):
        is_google_empty = not self.google_api_key or self.google_api_key == "CHANGE_ME_GOOGLE_API_KEY"
        if is_google_empty and self.gemini_api_key:
            self.google_api_key = self.gemini_api_key

        if self.jwt_secret == INSECURE_JWT_DEFAULT:
            raise ValueError(
                "JWT_SECRET uses the insecure default value. Set a unique secret before startup."
            )

        if self.jwt_secret and len(self.jwt_secret) < self.secret_key_min_length:
            raise ValueError(
                f"JWT_SECRET must be at least {self.secret_key_min_length} characters long."
            )

        if not self.debug and not self.jwt_secret:
            raise ValueError("JWT_SECRET must be configured when DEBUG=false.")

        if self.app_env == "production" and self.celery_task_always_eager:
            raise ValueError("CELERY_TASK_ALWAYS_EAGER must be false in production.")

        if self.app_env == "production":
            self.background_jobs_require_broker = True
            self.graph_seed_enabled = False
            self.ws_ticket_allow_memory_fallback = False
            self.internal_full_trace_enabled = False

            if self.observability_mode != "PRODUCTION_METADATA_ONLY":
                raise ValueError(
                    "OBSERVABILITY_MODE must be PRODUCTION_METADATA_ONLY when APP_ENV=production."
                )

            if "*" in self.cors_origins:
                raise ValueError("CORS_ORIGINS must not include '*' in production.")

            if "postgres:postgres@" in self.database_url or "localhost" in self.database_url:
                raise ValueError(
                    "DATABASE_URL appears to use development credentials or localhost in production."
                )

            if self.redis_url in {"redis://localhost:6379/0", "redis://redis:6379/0"}:
                raise ValueError("REDIS_URL must not use the unauthenticated development default in production.")

            if self.use_neo4j and self.neo4j_password.strip().lower() in DEVELOPMENT_ONLY_VALUES:
                raise ValueError("NEO4J_PASSWORD must be changed when USE_NEO4J=true in production.")

            if self.llm_provider == "groq" and not self.groq_api_key:
                raise ValueError("GROQ_API_KEY is required when LLM_PROVIDER=groq in production.")

            if self.llm_provider == "gemini" and not self.google_api_key:
                raise ValueError("GOOGLE_API_KEY is required when LLM_PROVIDER=gemini in production.")

        if self.vector_backend == "qdrant" and not self.qdrant_url:
            raise ValueError("QDRANT_URL is required when VECTOR_BACKEND=qdrant.")

        return self


@lru_cache
def get_settings() -> Settings:
    """Cached singleton for settings."""
    return Settings()
