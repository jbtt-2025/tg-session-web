"""
Telethon client wrapper for Telegram operations.
Provides methods for login, session validation, code listening, and heartbeat.
"""

import asyncio
import logging
import re
from functools import wraps
from typing import Dict, Optional

from telethon import TelegramClient, events
from telethon.errors import (
    FloodWaitError,
    AuthKeyUnregisteredError,
    SessionPasswordNeededError,
    PhoneCodeInvalidError,
    PhoneCodeExpiredError,
    PasswordHashInvalidError,
)
from telethon.sessions import StringSession


logger = logging.getLogger(__name__)


def mask_sensitive_data(data: str, visible_chars: int = 10) -> str:
    """
    遮蔽敏感数据，只显示前几个字符
    
    Args:
        data: 需要遮蔽的敏感数据
        visible_chars: 可见字符数量（默认10个）
        
    Returns:
        str: 遮蔽后的字符串（前N个字符 + "..."）
    """
    if not data:
        return ""
    if len(data) <= visible_chars:
        return data[:3] + "..."
    return data[:visible_chars] + "..."


class RateLimiter:
    """简单的速率限制器，确保相邻请求之间的最小间隔"""
    
    def __init__(self, min_interval: float):
        """
        初始化速率限制器
        
        Args:
            min_interval: 相邻请求之间的最小间隔（秒）
        """
        self.min_interval = min_interval
        self._last_request_time = 0.0
        self._lock = asyncio.Lock()
    
    async def wait(self):
        """等待直到可以发起下一个请求"""
        async with self._lock:
            current_time = asyncio.get_event_loop().time()
            time_since_last = current_time - self._last_request_time
            
            if time_since_last < self.min_interval:
                await asyncio.sleep(self.min_interval - time_since_last)
            
            self._last_request_time = asyncio.get_event_loop().time()


def handle_telegram_errors(func):
    """
    Decorator to handle common Telegram API errors.
    Automatically retries on FloodWaitError and converts errors to meaningful exceptions.
    """
    @wraps(func)
    async def wrapper(*args, **kwargs):
        try:
            return await func(*args, **kwargs)
        except FloodWaitError as e:
            logger.warning(f"FloodWaitError: waiting {e.seconds} seconds")
            await asyncio.sleep(e.seconds + 5)
            return await func(*args, **kwargs)
        except AuthKeyUnregisteredError:
            logger.error("Session expired or invalid")
            raise ValueError("Session expired or invalid")
        except PhoneCodeInvalidError:
            logger.error("Invalid verification code")
            raise ValueError("Invalid verification code")
        except PhoneCodeExpiredError:
            logger.error("Verification code expired")
            raise ValueError("Verification code expired")
        except PasswordHashInvalidError:
            logger.error("Invalid 2FA password")
            raise ValueError("Invalid 2FA password")
        except Exception as e:
            logger.error(f"Unexpected error in {func.__name__}: {e}")
            raise
    return wrapper


class TelegramClientWrapper:
    """
    Wrapper class for Telethon client operations.
    Manages login flow, session validation, code listening, and heartbeat operations.
    """

    def __init__(self, api_id: int, api_hash: str, max_concurrent: int = 10):
        """
        Initialize the Telegram client wrapper.

        Args:
            api_id: Telegram API ID
            api_hash: Telegram API Hash
            max_concurrent: Maximum number of concurrent Telegram API operations (default: 10)
        """
        self.api_id = api_id
        self.api_hash = api_hash
        
        # 添加并发和速率限制
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._rate_limiter = RateLimiter(min_interval=0.5)
        
        logger.info(f"TelegramClientWrapper initialized with max_concurrent={max_concurrent}")

    async def _with_limits(self, coro):
        """
        在并发和速率限制下执行协程
        
        Args:
            coro: 要执行的协程
            
        Returns:
            协程的返回值
        """
        async with self._semaphore:
            await self._rate_limiter.wait()
            return await coro

    @handle_telegram_errors
    async def start_login(self, phone: str) -> tuple[Dict[str, str], TelegramClient]:
        """
        Start the login process by sending a verification code to the phone number.

        Args:
            phone: Phone number in international format

        Returns:
            Tuple containing:
            - Dictionary containing phone_code_hash and status
            - TelegramClient instance for this login session

        Raises:
            ValueError: If phone number is invalid or other errors occur
        """
        logger.info(f"Starting login for phone: {phone}")
        
        # Create a new client for this login session
        client = TelegramClient(StringSession(), self.api_id, self.api_hash)
        await client.connect()
        
        try:
            # Send code request
            sent_code = await client.send_code_request(phone)
            
            logger.info(f"Verification code sent to {phone}")
            return (
                {
                    "status": "code_sent",
                    "phone_code_hash": sent_code.phone_code_hash,
                    "phone": phone
                },
                client
            )
        except Exception as e:
            # Clean up client on error
            await client.disconnect()
            raise

    @handle_telegram_errors
    async def submit_code(self, client: TelegramClient, phone: str, code: str, phone_code_hash: str) -> Dict[str, str]:
        """
        Submit the verification code to complete login.

        Args:
            client: TelegramClient instance from start_login
            phone: Phone number used in start_login
            code: Verification code from Telegram
            phone_code_hash: Hash returned from start_login

        Returns:
            Dictionary with status and session_string (if successful) or password_required flag

        Raises:
            ValueError: If code is invalid or client not initialized
        """
        if not client:
            raise ValueError("No active login session. Call start_login first.")
        
        logger.info(f"Submitting verification code for {phone}")
        
        try:
            # Sign in with the code
            user = await client.sign_in(phone, code, phone_code_hash=phone_code_hash)
            
            # Login successful, get the session string
            session_string = client.session.save()
            
            # Clean up
            await client.disconnect()
            
            logger.info(f"Login successful for user {user.id}")
            return {
                "status": "success",
                "session_string": session_string,
                "tg_id": user.id
            }
        except SessionPasswordNeededError:
            # 2FA is enabled, need password
            logger.info("2FA password required")
            return {
                "status": "password_required"
            }
        except Exception as e:
            # Clean up on error
            await client.disconnect()
            raise

    @handle_telegram_errors
    async def submit_password(self, client: TelegramClient, password: str) -> Dict[str, str]:
        """
        Submit 2FA password to complete login.

        Args:
            client: TelegramClient instance from start_login
            password: Two-factor authentication password

        Returns:
            Dictionary with status and session_string

        Raises:
            ValueError: If password is invalid or client not initialized
        """
        if not client:
            raise ValueError("No active login session. Call start_login first.")
        
        logger.info("Submitting 2FA password")
        
        try:
            # Sign in with password
            user = await client.sign_in(password=password)
            
            # Get the session string
            session_string = client.session.save()
            
            # Clean up
            await client.disconnect()
            
            logger.info(f"Login successful with 2FA for user {user.id}")
            return {
                "status": "success",
                "session_string": session_string,
                "tg_id": user.id
            }
        except Exception as e:
            # Clean up on error
            await client.disconnect()
            raise

    @handle_telegram_errors
    async def validate_session(self, session_string: str) -> Dict[str, any]:
        """
        Validate a StringSession and retrieve account information.

        Args:
            session_string: Telethon StringSession to validate

        Returns:
            Dictionary containing tg_id, username, phone, and other account info

        Raises:
            ValueError: If session is invalid or expired
        """
        logger.info("Validating session")
        
        async def _do_validate():
            client = TelegramClient(StringSession(session_string), self.api_id, self.api_hash)
            
            try:
                await client.connect()
                
                # Call get_me to validate session and get account info
                me = await client.get_me()
                
                if not me:
                    raise ValueError("Invalid session: unable to retrieve account information")
                
                logger.info(f"Session validated for user {me.id}, session: {mask_sensitive_data(session_string)}")
                
                result = {
                    "tg_id": me.id,
                    "username": me.username,
                    "phone": me.phone,
                    "first_name": me.first_name,
                    "last_name": me.last_name
                }
                
                return result
            finally:
                await client.disconnect()
        
        return await self._with_limits(_do_validate())

    @handle_telegram_errors
    async def listen_for_code(self, session_string: str, timeout: int = 300) -> Optional[str]:
        """
        Listen for verification code from Telegram (777000).

        Args:
            session_string: Telethon StringSession
            timeout: Maximum time to wait for code in seconds (default: 300 = 5 minutes)

        Returns:
            Verification code as string, or None if timeout

        Raises:
            ValueError: If session is invalid
        """
        logger.info("Starting to listen for verification code")
        
        async def _do_listen():
            client = TelegramClient(StringSession(session_string), self.api_id, self.api_hash)
            code_received = asyncio.Event()
            verification_code = None
            
            try:
                await client.connect()
                await client.start()
                
                @client.on(events.NewMessage(from_users=777000))
                async def handler(event):
                    nonlocal verification_code
                    logger.info(f"Received message from 777000: {event.raw_text}")
                    
                    # Extract verification code from message
                    code = self._extract_verification_code(event.raw_text)
                    if code:
                        verification_code = code
                        code_received.set()
                
                # Wait for code or timeout
                try:
                    await asyncio.wait_for(code_received.wait(), timeout=timeout)
                    logger.info(f"Verification code received: {verification_code}")
                    return verification_code
                except asyncio.TimeoutError:
                    logger.warning(f"Timeout waiting for verification code after {timeout} seconds")
                    return None
            finally:
                await client.disconnect()
        
        return await self._with_limits(_do_listen())

    @staticmethod
    def _extract_verification_code(message: str) -> Optional[str]:
        """
        Extract verification code from Telegram message.
        Looks for 5-6 digit codes in the message.

        Args:
            message: Message text from Telegram

        Returns:
            Verification code as string, or None if not found
        """
        # Pattern to match 5-6 digit codes
        pattern = r'\b(\d{5,6})\b'
        match = re.search(pattern, message)
        
        if match:
            return match.group(1)
        return None

    @handle_telegram_errors
    async def heartbeat(self, session_string: str) -> bool:
        """
        Execute a heartbeat operation to keep the session alive.
        Calls get_me() to verify the session is still valid.

        Args:
            session_string: Telethon StringSession

        Returns:
            True if heartbeat successful, False otherwise

        Raises:
            ValueError: If session is invalid or expired
        """
        logger.info("Executing heartbeat")
        
        async def _do_heartbeat():
            client = TelegramClient(StringSession(session_string), self.api_id, self.api_hash)
            
            try:
                await client.connect()
                
                # Call get_me as heartbeat
                me = await client.get_me()
                
                if not me:
                    logger.error("Heartbeat failed: unable to retrieve account information")
                    return False
                
                logger.info(f"Heartbeat successful for user {me.id}, session: {mask_sensitive_data(session_string)}")
                return True
            except Exception as e:
                logger.error(f"Heartbeat failed: {e}")
                raise
            finally:
                await client.disconnect()
        
        return await self._with_limits(_do_heartbeat())
