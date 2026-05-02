from typing import Optional

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    LLM_PROVIDER: str = "mock"
    OPENAI_API_KEY: Optional[str] = None
    OPENAI_BASE_URL: Optional[str] = None
    OPENAI_MODEL: str = "deepseek-chat"

    class Config:
        env_file = ".env"
        extra = "ignore"


settings = Settings()