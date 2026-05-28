from pydantic_settings import BaseSettings
from typing import Optional

class Settings(BaseSettings):
    app_env: str = "development"
    database_url: str
    neon_auth_project_id: str = ""
    neon_auth_base_url: str = ""
    neon_auth_jwks_url: str = ""
    neon_auth_cookie_secret: str = ""
    api_key_encryption_secret: str
    paddle_api_key: str
    paddle_webhook_secret: str
    paddle_environment: str = "sandbox"
    resend_api_key: str = ""
    email_from: str = "noreply@aitohumanizer.com"
    email_from_name: str = "AiToHumanizer"
    first_superadmin_email: str = "admin@aitohumanizer.com"
    frontend_url: str = "http://localhost:3000"
    backend_url: str = "http://localhost:8000"
    jwks_cache_ttl: int = 86400
    cors_origins: list[str] = []

    @property
    def resolved_cors_origins(self) -> list[str]:
        if self.cors_origins:
            return self.cors_origins
        if self.app_env == "production":
            return [
                self.frontend_url,
                "https://aitohumanizer.com",
                "https://www.aitohumanizer.com",
                "https://aitohumanizer.vercel.app",
            ]
        return ["http://localhost:3000", "http://127.0.0.1:3000"]

    model_config = {"env_file": ".env", "case_sensitive": False}

settings = Settings()
