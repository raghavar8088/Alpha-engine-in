from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    mongo_url: str = "mongodb://localhost:27017"
    mongo_db_name: str = "tradingai"
    redis_url: str = "redis://localhost:6379/0"
    broker_encryption_key: str = ""
    dhan_base_url: str = "https://api.dhan.co/v2"
    groq_api_key: str = ""
    mistral_api_key: str = ""
    deepseek_api_key: str = ""
    cerebras_api_key: str = ""
    xai_api_key: str = ""
    enable_live_trading: bool = False
    app_shared_secret: str = ""

    model_config = SettingsConfigDict(env_file=".env")


settings = Settings()
