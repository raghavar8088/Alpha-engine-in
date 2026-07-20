from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    mongo_url: str = "mongodb://localhost:27017"
    mongo_db_name: str = "tradingai"
    redis_url: str = "redis://localhost:6379/0"
    broker_encryption_key: str = ""
    dhan_base_url: str = "https://api.dhan.co/v2"
    dhan_auth_base_url: str = "https://auth.dhan.co"
    # TOTP-based programmatic login (no browser/2FA prompt) — all three must be set
    # to enable auto-refresh. Requires TOTP API auth enabled once on the Dhan
    # account first (Dhan Web -> DhanHQ Trading APIs -> Setup TOTP).
    dhan_client_id: str = ""
    dhan_pin: str = ""
    dhan_totp_secret: str = ""
    # Angel One SmartAPI — standby market-data source for when Dhan's single
    # permitted access token is rotated out from under us. Quotes and candles only;
    # orders stay on Dhan. Angel enforces IP whitelisting, so angelone_public_ip
    # must be one of the static IPs registered against the API key.
    angelone_base_url: str = "https://apiconnect.angelone.in"
    angelone_api_key: str = ""
    angelone_client_code: str = ""
    angelone_pin: str = ""
    angelone_totp_secret: str = ""
    angelone_public_ip: str = ""
    groq_api_key: str = ""
    mistral_api_key: str = ""
    deepseek_api_key: str = ""
    cerebras_api_key: str = ""
    xai_api_key: str = ""
    enable_live_trading: bool = False
    app_shared_secret: str = ""

    model_config = SettingsConfigDict(env_file=".env")


settings = Settings()
