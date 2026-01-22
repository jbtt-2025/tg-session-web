"""
Pydantic data models for the Telegram session keepalive web management interface.
"""

from pydantic import BaseModel, Field, field_validator
from datetime import datetime
from typing import Optional
import re


class SessionData(BaseModel):
    """
    Data model for a Telegram session keepalive task.
    Stored in ./data/{uuid}.json files.
    """
    uuid: str = Field(..., description="Unique identifier for the task")
    tg_id: int = Field(..., description="Telegram user ID")
    session_string: str = Field(..., description="Telethon StringSession")
    notify_chat_id: int = Field(..., description="Chat ID to receive notifications")
    consecutive_failures: int = Field(default=0, ge=0, description="Number of consecutive heartbeat failures")
    created_at: datetime = Field(..., description="Task creation timestamp")
    last_heartbeat: Optional[datetime] = Field(default=None, description="Last successful heartbeat timestamp")

    @field_validator('uuid')
    @classmethod
    def validate_uuid(cls, v: str) -> str:
        """Validate UUID format (basic check for 8-4-4-4-12 pattern)"""
        uuid_pattern = r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
        if not re.match(uuid_pattern, v, re.IGNORECASE):
            raise ValueError('Invalid UUID format')
        return v

    @field_validator('session_string')
    @classmethod
    def validate_session_string(cls, v: str) -> str:
        """Validate that session_string is not empty"""
        if not v or not v.strip():
            raise ValueError('session_string cannot be empty')
        return v

    class Config:
        json_schema_extra = {
            "example": {
                "uuid": "550e8400-e29b-41d4-a716-446655440000",
                "tg_id": 123456789,
                "session_string": "1AQAAA...",
                "notify_chat_id": 123456789,
                "consecutive_failures": 0,
                "created_at": "2025-01-14T10:30:00Z",
                "last_heartbeat": "2025-01-14T12:00:00Z"
            }
        }


class LoginStartRequest(BaseModel):
    """Request model for starting the login process"""
    phone: str = Field(..., description="Phone number in international format")

    @field_validator('phone')
    @classmethod
    def validate_phone(cls, v: str) -> str:
        """Validate phone number format (basic check for digits and optional +)"""
        # Remove spaces and dashes for validation
        cleaned = v.replace(' ', '').replace('-', '')
        
        # Check if it starts with + and has digits
        if cleaned.startswith('+'):
            cleaned = cleaned[1:]
        
        if not cleaned.isdigit():
            raise ValueError('Phone number must contain only digits (and optional + prefix)')
        
        if len(cleaned) < 10 or len(cleaned) > 15:
            raise ValueError('Phone number must be between 10 and 15 digits')
        
        return v

    class Config:
        json_schema_extra = {
            "example": {
                "phone": "+1234567890"
            }
        }


class LoginCodeRequest(BaseModel):
    """Request model for submitting verification code"""
    session_id: str = Field(..., description="Session ID returned from login start")
    code: str = Field(..., description="Verification code from Telegram")

    @field_validator('code')
    @classmethod
    def validate_code(cls, v: str) -> str:
        """Validate verification code format (5-6 digits)"""
        if not v.isdigit():
            raise ValueError('Verification code must contain only digits')
        
        if len(v) < 5 or len(v) > 6:
            raise ValueError('Verification code must be 5 or 6 digits')
        
        return v

    class Config:
        json_schema_extra = {
            "example": {
                "session_id": "abc123def456...",
                "code": "12345"
            }
        }


class LoginPasswordRequest(BaseModel):
    """Request model for submitting 2FA password"""
    session_id: str = Field(..., description="Session ID returned from login start")
    password: str = Field(..., description="Two-factor authentication password")

    @field_validator('password')
    @classmethod
    def validate_password(cls, v: str) -> str:
        """Validate that password is not empty"""
        if not v or not v.strip():
            raise ValueError('Password cannot be empty')
        return v

    class Config:
        json_schema_extra = {
            "example": {
                "session_id": "abc123def456...",
                "password": "my2fapassword"
            }
        }


class CreateTaskRequest(BaseModel):
    """Request model for creating a keepalive task"""
    session_string: str = Field(..., description="Telethon StringSession")
    notify_chat_id: int = Field(..., description="Chat ID to receive notifications")

    @field_validator('session_string')
    @classmethod
    def validate_session_string(cls, v: str) -> str:
        """Validate that session_string is not empty"""
        if not v or not v.strip():
            raise ValueError('session_string cannot be empty')
        return v

    class Config:
        json_schema_extra = {
            "example": {
                "session_string": "1AQAAA...",
                "notify_chat_id": 123456789
            }
        }


class ValidateSessionRequest(BaseModel):
    """Request model for validating a StringSession"""
    session_string: str = Field(..., description="Telethon StringSession to validate")

    @field_validator('session_string')
    @classmethod
    def validate_session_string(cls, v: str) -> str:
        """Validate that session_string is not empty"""
        if not v or not v.strip():
            raise ValueError('session_string cannot be empty')
        return v

    class Config:
        json_schema_extra = {
            "example": {
                "session_string": "1AQAAA..."
            }
        }
