from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    APP_NAME: str = "WhatsApp Quiz Engine"
    PORT: int = 8000
    SECRET_KEY: str

    WHATSAPP_TOKEN: str
    PHONE_NUMBER_ID: str
    VERIFY_TOKEN: str

    REDIS_HOST: str = "localhost"
    REDIS_PORT: int = 6379

    # Email Settings
    SMTP_HOST: str = "smtp.gmail.com"
    SMTP_PORT: int = 587
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""
    NOTIFICATION_EMAIL: str = ""  # Destination address for leads

    # HubSpot Settings
    HUBSPOT_ACCESS_TOKEN: str = ""

    # Feature Flags for integrations
    ENABLE_EMAIL_NOTIFICATIONS: bool = True
    ENABLE_HUBSPOT_SYNC: bool = True

    class Config:
        env_file = ".env"

settings = Settings()