from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Job Application Copilot"
    app_env: str = "development"
    app_host: str = "127.0.0.1"
    app_port: int = 8000
    debug: bool = True

    database_url: str = "sqlite:///./job_application_copilot.db"

    # Free APIs (recommended)
    gemini_api_key: str = ""       # FREE — aistudio.google.com
    hf_api_key: str = ""           # FREE — huggingface.co/settings/tokens

    # Optional paid APIs (not required)
    openai_api_key: str = ""
    anthropic_api_key: str = ""

    storage_dir: str = "storage"
    resume_dir: str = "storage/resumes"
    generated_dir: str = "storage/generated"
    screenshot_dir: str = "storage/screenshots"
    log_dir: str = "storage/logs"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )


settings = Settings()
