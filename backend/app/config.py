from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Aromaz POS API"
    environment: str = "development"
    mongo_uri: str = "mongodb://localhost:27017"
    mongo_db_name: str = "aromaz_pos"
    cors_origins: str = "http://localhost:5173"
    owner_emails: str = ""
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_from_email: str = ""
    otp_ttl_minutes: int = 10
    otp_max_attempts: int = 5
    otp_cooldown_seconds: int = 30
    otp_lockout_minutes: int = 15
    totp_issuer: str = "Aromaz POS"
    totp_account_name: str = "owner@aromaz.local"
    totp_setup_key: str = ""
    session_ttl_hours: int = 720
    session_cookie_name: str = "pos_session"
    session_secret: str = "dev-change-me"
    ebill_token_ttl_hours: int = 24
    ebill_link_secret: str = ""
    ebill_public_base_url: str = ""
    msg91_auth_key: str = ""
    msg91_sender_id: str = ""
    msg91_route: str = "4"
    msg91_country_code: str = "91"
    msg91_retry_attempts: int = 2
    msg91_retry_delay_ms: int = 250
    resend_api_key: str = ""
    resend_from_email: str = "billing@aromaz.co.in"
    resend_retry_attempts: int = 2
    resend_retry_delay_ms: int = 250
    gemini_api_key: str = ""
    gemini_model: str = "gemini-3.1-flash-lite"
    gemini_timeout_seconds: int = 75
    gemini_retry_attempts: int = 1
    gemini_retry_backoff_ms: int = 600
    gemini_fallback_models: str = "gemini-2.5-flash,gemini-3-flash"
    gemini_input_cost_per_million_usd: float = 0.30
    gemini_output_cost_per_million_usd: float = 2.50
    gemini_bill_thoughts_tokens: bool = True
    tax_rate_percent: float = 5.0

    # Load base env first, then optional local override.
    # This lets VM keep its .env while local dev can override via .env.local.
    model_config = SettingsConfigDict(env_file=(".env", ".env.local"), extra="ignore")


settings = Settings()
