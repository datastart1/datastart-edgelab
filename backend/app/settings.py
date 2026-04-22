from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file='.env', env_file_encoding='utf-8', extra='ignore')

    app_env: str = 'development'
    database_url: str
    jwt_secret_key: str
    jwt_algorithm: str = 'HS256'
    license_token_ttl_hours: int = 24
    offline_grace_days: int = 7

    stripe_secret_key: str
    stripe_webhook_secret: str
    stripe_price_monthly: str
    stripe_price_yearly: str
    app_success_url: str
    app_cancel_url: str
    billing_return_url: str


settings = Settings()
