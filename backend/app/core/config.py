from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import List, Union


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env")

    api_title: str = "AI Agent Hub API"
    api_version: str = "0.1.0"
    environment: str = "development"
    debug: bool = True
    
    # Database - uses app user, not admin
    database_url: str = "postgresql://ai_agent_app:ai_agent_app_password@localhost:5435/ai_agent_hub"
    
    # Security
    secret_key: str = "dev-secret-key-change-in-production"
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 30
    
    # CORS - can be comma-separated string or list
    cors_origins: Union[List[str], str] = "http://localhost:4200,http://localhost:3000"

    # Optional token for GitHub ingestion (5000 req/hr instead of 10/min)
    github_token: str | None = None

    def get_cors_origins(self) -> List[str]:
        """Parse CORS origins from string or list"""
        if isinstance(self.cors_origins, str):
            return [origin.strip() for origin in self.cors_origins.split(",")]
        return self.cors_origins


settings = Settings()
