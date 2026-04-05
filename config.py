import os
from pydantic_settings import BaseSettings
from typing import List

class Settings(BaseSettings):
    nim_base_url: str = "https://integrate.api.nvidia.com/v1"
    api_keys: List[str] = []
    rpm_limit: int = 40
    window_seconds: int = 60
    health_check_interval: int = 300
    max_consecutive_failures: int = 3
    request_timeout: int = 120
    max_retries: int = 2
    database_url: str = "sqlite+aiosqlite:///./nim_pool.db"
    log_level: str = "INFO"

    class Config:
        env_file = ".env"
        env_prefix = "NIM_"

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        if not self.api_keys:
            keys_str = os.environ.get("NIM_API_KEYS", "")
            self.api_keys = [k.strip() for k in keys_str.split(",") if k.strip()]

settings = Settings()
