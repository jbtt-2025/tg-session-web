"""
Configuration management for the Telegram session keepalive web interface.
Loads configuration from environment variables with validation and defaults.
"""

from pydantic_settings import BaseSettings
from typing import Optional


class Config(BaseSettings):
    """
    Application configuration loaded from environment variables.
    
    Required parameters:
    - TG_API_ID: Telegram API ID
    - TG_API_HASH: Telegram API Hash
    - TG_NOTIFY_BOT_TOKEN: Telegram Bot Token
    - TG_NOTIFY_BOT_NAME: Telegram Bot Username
    
    Optional parameters with defaults:
    - TG_INTERVAL_SECONDS: Heartbeat interval (default: 86400 = 1 day)
    - TG_JITTER_SECONDS: Random jitter for interval (default: 300 = 5 minutes)
    - TG_HEART_BEAT_MAX_FAIL: Max consecutive failures before cleanup (default: 3)
    - DATA_DIR: Directory for storing session files (default: ./data)
    """
    
    # Required parameters
    TG_API_ID: int = 32471437
    TG_API_HASH: str = "c356cf8137a04c92ebfda0fdbd299604"
    TG_NOTIFY_BOT_TOKEN: str
    TG_NOTIFY_BOT_NAME: str
    
    # Optional parameters with defaults
    TG_INTERVAL_SECONDS: int = 86400  # 1 day
    TG_JITTER_SECONDS: int = 300      # 5 minutes
    TG_HEART_BEAT_MAX_FAIL: int = 3
    DATA_DIR: str = "./data"
    
    class Config:
        """Pydantic settings configuration"""
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = True
        extra = "ignore"  # Ignore extra environment variables


def load_config() -> Config:
    """
    Load and validate configuration from environment variables.
    
    Raises:
        ValueError: If required parameters are missing
    
    Returns:
        Config: Validated configuration object
    """
    try:
        config = Config()
        return config
    except Exception as e:
        raise ValueError(f"Failed to load configuration: {str(e)}")
