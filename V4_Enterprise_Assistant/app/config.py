import os
from typing import Optional

from pydantic import ConfigDict, model_validator
from pydantic_settings import BaseSettings

# APP_ENV=test 时跳过 .env 读取，确保测试环境与真实配置完全隔离
_env_file = None if os.environ.get("APP_ENV") == "test" else ".env"


class Settings(BaseSettings):
    APP_ENV: str = "development"
    DATABASE_URL: str = "sqlite:///./customer_assistant.db"
    COOKIE_SECURE: bool = False
    APP_ACCESS_PASSWORD: str = ""
    APP_ADMIN_USERNAME: str = "admin"
    ENABLE_PUBLIC_REGISTRATION: bool = False
    SESSION_SECRET: str = ""
    PUBLIC_SITE_URL: str = ""
    LLM_PROVIDER: str = "mock"
    OPENAI_API_KEY: Optional[str] = None
    OPENAI_BASE_URL: Optional[str] = None
    OPENAI_MODEL: str = "deepseek-chat"

    # ─── LLM stability & cost control ───
    LLM_TIMEOUT_SECONDS: int = 30
    LLM_MAX_RETRIES: int = 2
    LLM_MAX_PROMPT_CHARS: int = 12000
    LLM_MAX_COMPLETION_TOKENS: int = 1200
    LLM_TEMPERATURE: float = 0.4
    LLM_ENABLE_USAGE_LOG: bool = True

    MAX_UPLOAD_SIZE_MB: int = 10

    # ─── Vector Search ───
    # 安全默认值：向量检索默认关闭，用户配置好 API Key 后再开启。
    VECTOR_SEARCH_ENABLED: bool = False
    EMBEDDING_PROVIDER: str = "openai_compatible"  # local | openai_compatible | test
    EMBEDDING_MODEL: str = "BAAI/bge-m3"  # local model name
    EMBEDDING_API_KEY: Optional[str] = None  # falls back to OPENAI_API_KEY
    EMBEDDING_BASE_URL: Optional[str] = None  # falls back to OPENAI_BASE_URL
    EMBEDDING_MODEL_NAME: str = "text-embedding-v3"  # API model name
    EMBEDDING_DIMENSION: int = 0  # 0=auto-detect from model; set to override (must match model)
    CHROMA_PERSIST_DIR: str = "./data/chroma_db"
    VECTOR_SEARCH_TOP_K: int = 4

    CORS_ORIGINS: str = (
        "http://localhost:3000,http://localhost:5173,"
        "http://127.0.0.1:3000,http://127.0.0.1:5173,http://127.0.0.1:8000"
    )

    model_config = ConfigDict(env_file=_env_file, extra="ignore")

    @model_validator(mode="after")
    def _validate_auth_config(self):
        if self.APP_ACCESS_PASSWORD:
            if not self.SESSION_SECRET:
                raise ValueError(
                    "SESSION_SECRET must be set when APP_ACCESS_PASSWORD is configured"
                )
            if len(self.SESSION_SECRET) < 32:
                raise ValueError(
                    "SESSION_SECRET must be at least 32 characters long. "
                    "Generate one with: python -c \"import secrets; print(secrets.token_hex(32))\""
                )
        return self

    @property
    def cors_origins(self) -> list[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]


settings = Settings()


def validate_production_settings() -> list[str]:
    """Validate production security configuration.

    Returns a list of warning strings (non-blocking issues).
    Raises ValueError for blocking misconfigurations.

    Only meaningful when APP_ENV == 'production'.  Callers should guard:
        if settings.APP_ENV == 'production':
            validate_production_settings()
    """
    warnings: list[str] = []
    errors: list[str] = []

    # 1. APP_ACCESS_PASSWORD must be set
    if not settings.APP_ACCESS_PASSWORD:
        errors.append(
            "APP_ACCESS_PASSWORD is empty. "
            "In production you MUST set a strong access password."
        )

    # 2. SESSION_SECRET must be set and strong enough
    if not settings.SESSION_SECRET:
        errors.append(
            "SESSION_SECRET is empty. "
            "Generate one with: python -c \"import secrets; print(secrets.token_hex(32))\""
        )
    elif len(settings.SESSION_SECRET) < 32:
        errors.append(
            f"SESSION_SECRET is only {len(settings.SESSION_SECRET)} characters. "
            "It must be at least 32 characters for production. "
            "Generate one with: python -c \"import secrets; print(secrets.token_hex(32))\""
        )

    # 3. Public registration must be off in production
    if settings.ENABLE_PUBLIC_REGISTRATION:
        errors.append(
            "ENABLE_PUBLIC_REGISTRATION is true. "
            "In production, public registration MUST be disabled (set to false)."
        )

    # 4. COOKIE_SECURE should be true (warning, not block)
    if not settings.COOKIE_SECURE:
        warnings.append(
            "COOKIE_SECURE is false. This is unsafe in production over HTTPS. "
            "Set COOKIE_SECURE=true unless you are temporarily using HTTP on an "
            "internal network (not recommended long-term)."
        )

    if errors:
        raise ValueError(
            "Production security check failed:\n  - "
            + "\n  - ".join(errors)
        )

    return warnings
