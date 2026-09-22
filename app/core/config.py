from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = "postgresql+psycopg2://localhost/plant_ops_dashboard"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
