"""
FastAPI Web Server for Telegram Session Keepalive Management Interface.

Provides three main functionalities:
1. Login to Telegram and get StringSession
2. Create keepalive tasks using StringSession
3. Receive verification codes via SSE
"""

import logging
import logging.handlers
import os
import time
import json
import asyncio
import sys
import secrets
import re
from contextlib import asynccontextmanager
from typing import Dict
from pathlib import Path
from dataclasses import dataclass

from fastapi import FastAPI, HTTPException, status, Query
from fastapi.responses import JSONResponse, HTMLResponse, FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from sse_starlette.sse import EventSourceResponse
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from telethon import TelegramClient, events
from telethon.errors import AuthKeyUnregisteredError
from telethon.sessions import StringSession

from models import (
    LoginStartRequest,
    LoginCodeRequest,
    LoginPasswordRequest,
    CreateTaskRequest,
    ValidateSessionRequest,
)
from telegram_client import TelegramClientWrapper
from session_manager import SessionManager, Config
from bot_notifier import BotNotifier


@dataclass
class LoginSession:
    """登录会话数据"""
    session_id: str
    phone: str
    phone_code_hash: str
    client: TelegramClient
    created_at: float
    status: str  # "code_sent", "password_required"


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


def validate_uuid_format(uuid: str) -> bool:
    """
    验证 UUID 格式
    
    Args:
        uuid: 待验证的 UUID 字符串
        
    Returns:
        bool: 如果符合标准 UUID 格式返回 True，否则返回 False
    """
    uuid_pattern = r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\Z'
    return bool(re.match(uuid_pattern, uuid, re.IGNORECASE))


def validate_safe_path(uuid: str, data_dir: str) -> Path:
    """
    验证路径安全性，防止路径遍历
    
    Args:
        uuid: 任务 UUID
        data_dir: 数据目录路径
        
    Returns:
        Path: 解析后的安全路径
        
    Raises:
        ValueError: 如果 UUID 格式无效或检测到路径遍历尝试
    """
    # 验证 UUID 格式
    if not validate_uuid_format(uuid):
        raise ValueError("Invalid UUID format")
    
    # 构造并解析路径
    session_file_path = (Path(data_dir) / f"{uuid}.json").resolve()
    data_dir_resolved = Path(data_dir).resolve()
    
    # 确保路径在 data_dir 内
    if not str(session_file_path).startswith(str(data_dir_resolved)):
        raise ValueError("Path traversal detected")
    
    return session_file_path


def setup_logging(log_level: str = "INFO", log_dir: str = "./logs") -> logging.Logger:
    """
    Configure logging with both console and file handlers.
    
    Args:
        log_level: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        log_dir: Directory for log files
        
    Returns:
        Configured logger instance
    """
    # Create logs directory if it doesn't exist
    log_path = Path(log_dir)
    log_path.mkdir(parents=True, exist_ok=True)
    
    # Get root logger to configure all modules
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, log_level.upper(), logging.INFO))
    
    # Remove existing handlers to avoid duplicates
    root_logger.handlers.clear()
    
    # Create formatters
    detailed_formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    
    simple_formatter = logging.Formatter(
        '%(asctime)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    
    # Console handler (INFO and above)
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(simple_formatter)
    root_logger.addHandler(console_handler)
    
    # File handler for all logs (DEBUG and above)
    file_handler = logging.handlers.RotatingFileHandler(
        log_path / "app.log",
        maxBytes=10 * 1024 * 1024,  # 10 MB
        backupCount=5,
        encoding='utf-8'
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(detailed_formatter)
    root_logger.addHandler(file_handler)
    
    # File handler for errors only
    error_handler = logging.handlers.RotatingFileHandler(
        log_path / "error.log",
        maxBytes=10 * 1024 * 1024,  # 10 MB
        backupCount=5,
        encoding='utf-8'
    )
    error_handler.setLevel(logging.ERROR)
    error_handler.setFormatter(detailed_formatter)
    root_logger.addHandler(error_handler)
    
    # Return a logger for this module
    return logging.getLogger(__name__)


# Configure logging
logger = setup_logging(
    log_level=os.getenv("LOG_LEVEL", "INFO"),
    log_dir=os.getenv("LOG_DIR", "./logs")
)


# Global instances
scheduler: AsyncIOScheduler = None
telegram_client: TelegramClientWrapper = None
session_manager: SessionManager = None
bot_notifier: BotNotifier = None
config: Config = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Lifespan context manager for FastAPI application.
    Handles startup and shutdown events.
    """
    # Startup
    logger.info("Starting FastAPI application")
    
    global scheduler, telegram_client, session_manager, bot_notifier, config
    
    # Load configuration from environment variables
    config = Config(
        api_id=int(os.getenv("TG_API_ID", "32471437")),
        api_hash=os.getenv("TG_API_HASH", "c356cf8137a04c92ebfda0fdbd299604"),
        interval_seconds=int(os.getenv("TG_INTERVAL_SECONDS", "86400")),
        jitter_seconds=int(os.getenv("TG_JITTER_SECONDS", "300")),
        notify_bot_token=os.getenv("TG_NOTIFY_BOT_TOKEN", ""),
        notify_bot_name=os.getenv("TG_NOTIFY_BOT_NAME", ""),
        max_failures=int(os.getenv("TG_HEART_BEAT_MAX_FAIL", "3")),
        data_dir=os.getenv("DATA_DIR", "./data")
    )
    
    # Validate required configuration
    if not config.api_id or not config.api_hash:
        logger.error("TG_API_ID and TG_API_HASH are required")
        raise ValueError("Missing required configuration: TG_API_ID and TG_API_HASH")
    
    # Initialize components
    scheduler = AsyncIOScheduler()
    telegram_client = TelegramClientWrapper(config.api_id, config.api_hash)
    bot_notifier = BotNotifier(config.notify_bot_token)
    session_manager = SessionManager(scheduler, config, telegram_client, bot_notifier)
    
    # Start scheduler
    scheduler.start()
    logger.info("APScheduler started")
    
    # Initialize session manager (load existing tasks)
    await session_manager.initialize()
    
    # Add periodic cleanup task for expired login sessions (every 5 minutes)
    scheduler.add_job(
        cleanup_expired_sessions,
        'interval',
        seconds=SESSION_CLEANUP_INTERVAL,
        id='cleanup_expired_sessions',
        replace_existing=True
    )
    logger.info(f"Scheduled periodic login session cleanup (every {SESSION_CLEANUP_INTERVAL} seconds)")
    
    logger.info("Application startup complete")
    
    yield
    
    # Shutdown
    logger.info("Shutting down application")
    
    # Clean up all login sessions
    await cleanup_all_login_sessions()
    logger.info("All login sessions cleaned up")
    
    # Stop scheduler
    scheduler.shutdown(wait=False)
    logger.info("APScheduler stopped")
    
    # Close bot notifier HTTP client
    await bot_notifier.close()
    
    logger.info("Application shutdown complete")


# Create FastAPI application
app = FastAPI(
    title="Telegram Session Keepalive Manager",
    description="Web interface for managing Telegram session keepalive tasks",
    version="1.0.0",
    lifespan=lifespan
)


# Store active login sessions (session_id -> LoginSession)
# This is a simple in-memory store for the login flow
login_sessions: Dict[str, LoginSession] = {}

# Session configuration
SESSION_TIMEOUT = 600  # 10 minutes
SESSION_CLEANUP_INTERVAL = 300  # 5 minutes cleanup interval

# SSE connection management
active_sse_connections = 0
MAX_SSE_CONNECTIONS = 50
sse_connections_lock = asyncio.Lock()


async def cleanup_login_session(session_id: str):
    """
    清理单个登录会话
    
    Args:
        session_id: 会话ID
    """
    session = login_sessions.pop(session_id, None)
    if session and session.client.is_connected():
        await session.client.disconnect()
        logger.info(f"Cleaned up login session: {session_id}")


async def cleanup_expired_sessions():
    """
    清理过期的登录会话
    
    检查所有登录会话，清理超过 SESSION_TIMEOUT (10分钟) 的会话
    """
    current_time = time.time()
    expired_sessions = []
    
    # 找出所有过期的会话
    for session_id, session in login_sessions.items():
        if current_time - session.created_at > SESSION_TIMEOUT:
            expired_sessions.append(session_id)
    
    # 清理过期的会话
    for session_id in expired_sessions:
        session = login_sessions.pop(session_id, None)
        if session and session.client.is_connected():
            await session.client.disconnect()
        logger.info(f"Cleaned up expired login session: {session_id}")
    
    if expired_sessions:
        logger.info(f"Cleaned up {len(expired_sessions)} expired login sessions")


async def cleanup_all_login_sessions():
    """
    清理所有登录会话
    
    在应用关闭时调用，确保所有会话都被正确清理
    """
    session_ids = list(login_sessions.keys())
    
    for session_id in session_ids:
        session = login_sessions.pop(session_id, None)
        if session and session.client.is_connected():
            await session.client.disconnect()
    
    if session_ids:
        logger.info(f"Cleaned up all {len(session_ids)} login sessions")


@app.get("/api/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "ok", "message": "Telegram Session Keepalive Manager"}


@app.post("/api/login/start")
async def login_start(request: LoginStartRequest):
    """
    Start the login process by sending a verification code.
    
    Args:
        request: LoginStartRequest containing phone number
        
    Returns:
        JSON response with status, session_id, and phone
        
    Raises:
        HTTPException: If login fails
    """
    logger.info(f"Login start request for phone: {request.phone}")
    
    try:
        # Start login process and get client
        result, client = await telegram_client.start_login(request.phone)
        
        # Generate unique session_id
        session_id = secrets.token_urlsafe(32)
        
        # Create LoginSession and store it
        login_session = LoginSession(
            session_id=session_id,
            phone=request.phone,
            phone_code_hash=result["phone_code_hash"],
            client=client,
            created_at=time.time(),
            status="code_sent"
        )
        login_sessions[session_id] = login_session
        
        logger.info(f"Verification code sent to {request.phone}, session_id: {session_id}")
        
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={
                "status": "code_sent",
                "session_id": session_id,
                "phone": request.phone,
                "message": "Verification code sent to your Telegram account"
            }
        )
        
    except ValueError as e:
        logger.error(f"Login start failed for {request.phone}: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        logger.error(f"Unexpected error during login start: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error during login"
        )


@app.post("/api/login/code")
async def login_code(request: LoginCodeRequest):
    """
    Submit verification code to complete login.
    
    Args:
        request: LoginCodeRequest containing session_id and code
        
    Returns:
        JSON response with status and session_string (if successful) or password_required flag
        
    Raises:
        HTTPException: If code submission fails
    """
    logger.info(f"Login code submission for session_id: {request.session_id}")
    
    # Check if session exists
    if request.session_id not in login_sessions:
        logger.error(f"Session not found: {request.session_id}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired session. Please start login again."
        )
    
    login_session = login_sessions[request.session_id]
    
    try:
        # Submit verification code
        result = await telegram_client.submit_code(
            login_session.client,
            login_session.phone,
            request.code,
            login_session.phone_code_hash
        )
        
        if result["status"] == "password_required":
            # 2FA is enabled, need password
            login_session.status = "password_required"
            
            logger.info(f"2FA password required for session {request.session_id}")
            
            return JSONResponse(
                status_code=status.HTTP_200_OK,
                content={
                    "status": "password_required",
                    "session_id": request.session_id,
                    "message": "Two-factor authentication is enabled. Please provide your password."
                }
            )
        else:
            # Login successful
            session_string = result["session_string"]
            tg_id = result["tg_id"]
            
            # Clean up login session
            await cleanup_login_session(request.session_id)
            
            logger.info(f"Login successful for session {request.session_id} (user_id: {tg_id})")
            
            return JSONResponse(
                status_code=status.HTTP_200_OK,
                content={
                    "status": "success",
                    "session_string": session_string,
                    "tg_id": tg_id,
                    "message": "Login successful"
                }
            )
            
    except ValueError as e:
        # Clean up login session on error
        await cleanup_login_session(request.session_id)
        logger.error(f"Login code submission failed for session {request.session_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        # Clean up login session on error
        await cleanup_login_session(request.session_id)
        logger.error(f"Unexpected error during code submission: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error during code submission"
        )


@app.post("/api/login/password")
async def login_password(request: LoginPasswordRequest):
    """
    Submit 2FA password to complete login.
    
    Args:
        request: LoginPasswordRequest containing session_id and password
        
    Returns:
        JSON response with status and session_string
        
    Raises:
        HTTPException: If password submission fails
    """
    logger.info(f"Login password submission for session_id: {request.session_id}")
    
    # Check if session exists
    if request.session_id not in login_sessions:
        logger.error(f"Session not found: {request.session_id}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired session. Please start login again."
        )
    
    login_session = login_sessions[request.session_id]
    
    # Verify session is in password_required state
    if login_session.status != "password_required":
        logger.error(f"Session {request.session_id} is not in password_required state")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Session is not in password_required state"
        )
    
    try:
        # Submit 2FA password
        result = await telegram_client.submit_password(login_session.client, request.password)
        
        session_string = result["session_string"]
        tg_id = result["tg_id"]
        
        # Clean up login session
        await cleanup_login_session(request.session_id)
        
        logger.info(f"Login successful with 2FA for session {request.session_id} (user_id: {tg_id})")
        
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={
                "status": "success",
                "session_string": session_string,
                "tg_id": tg_id,
                "message": "Login successful with 2FA"
            }
        )
        
    except ValueError as e:
        # Clean up login session on error
        await cleanup_login_session(request.session_id)
        logger.error(f"Login password submission failed for session {request.session_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        # Clean up login session on error
        await cleanup_login_session(request.session_id)
        logger.error(f"Unexpected error during password submission: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error during password submission"
        )


@app.post("/api/task/validate")
async def validate_task_session(request: ValidateSessionRequest):
    """
    Validate a StringSession and retrieve account information.
    
    Args:
        request: ValidateSessionRequest containing session_string
        
    Returns:
        JSON response with account information (tg_id, username, phone, etc.)
        
    Raises:
        HTTPException: If session validation fails
    """
    logger.info("Validating StringSession for task creation")
    
    try:
        # Validate session and get account info
        logger.debug(f"Validating session: {mask_sensitive_data(request.session_string)}")
        account_info = await telegram_client.validate_session(request.session_string)
        
        logger.info(f"Session validated for user {account_info['tg_id']}")
        
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={
                "status": "valid",
                "tg_id": account_info["tg_id"],
                "username": account_info.get("username"),
                "phone": account_info.get("phone"),
                "first_name": account_info.get("first_name"),
                "last_name": account_info.get("last_name"),
                "bot_name": config.notify_bot_name,
                "message": "Session is valid"
            }
        )
        
    except ValueError as e:
        logger.error(f"Session validation failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        logger.error(f"Unexpected error during session validation: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error during session validation"
        )


@app.post("/api/task/create")
async def create_keepalive_task(request: CreateTaskRequest):
    """
    Create a new keepalive task.
    
    Args:
        request: CreateTaskRequest containing session_string and notify_chat_id
        
    Returns:
        JSON response with task UUID and verification code URL
        
    Raises:
        HTTPException: If task creation fails
    """
    logger.info(f"Creating keepalive task for notify_chat_id: {request.notify_chat_id}")
    
    try:
        # Create the task
        logger.debug(f"Creating task with session: {mask_sensitive_data(request.session_string)}")
        task_uuid = await session_manager.create_task(
            request.session_string,
            request.notify_chat_id
        )
        
        # Generate verification code URL
        # Assuming the server is running on the same host
        # In production, this should use the actual base URL from config
        verify_url = f"/verifyCode/{task_uuid}"
        
        logger.info(f"Task created successfully: {task_uuid}")
        
        return JSONResponse(
            status_code=status.HTTP_201_CREATED,
            content={
                "status": "created",
                "uuid": task_uuid,
                "verify_url": verify_url,
                "message": f"Keepalive task created successfully. Please start the bot @{config.notify_bot_name} to receive notifications."
            }
        )
        
    except ValueError as e:
        logger.error(f"Task creation failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        logger.error(f"Unexpected error during task creation: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error during task creation"
        )


@app.get("/api/verify/listen")
async def listen_verification_code(session_string: str = Query(..., description="Telegram StringSession")):
    """
    Listen for verification codes via Server-Sent Events (SSE).
    
    This endpoint establishes an SSE connection and listens for messages from Telegram (777000).
    When a verification code is received, it's extracted and sent to the client.
    
    Args:
        session_string: Telegram StringSession to use for listening
        
    Returns:
        EventSourceResponse with SSE events:
        - connected: Connection established successfully
        - code: Verification code received
        - heartbeat: Periodic heartbeat to keep connection alive
        - timeout: No code received within timeout period
        - error: An error occurred
        
    Raises:
        HTTPException: 503 if connection limit reached
    """
    logger.info("SSE verification code listening request received")
    logger.debug(f"SSE session: {mask_sensitive_data(session_string)}")
    
    # Check connection limit before establishing connection
    async with sse_connections_lock:
        if active_sse_connections >= MAX_SSE_CONNECTIONS:
            logger.warning(f"SSE connection limit reached: {active_sse_connections}/{MAX_SSE_CONNECTIONS}")
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Too many active connections. Please try again later."
            )
    
    async def event_generator():
        """
        Async generator that yields SSE events.
        """
        global active_sse_connections
        
        # Increment connection count
        async with sse_connections_lock:
            active_sse_connections += 1
            logger.info(f"SSE connection established. Active connections: {active_sse_connections}/{MAX_SSE_CONNECTIONS}")
        
        client = None
        session = None
        
        try:
            # Set timeout to 5 minutes (300 seconds)
            timeout = 300
            start_time = time.time()
            
            # Create StringSession first (this can fail)
            try:
                session = StringSession(session_string)
            except Exception as e:
                logger.error(f"SSE: Failed to create StringSession: {e}")
                raise ValueError(f"Invalid session string: {e}")
            
            # Create Telethon client
            client = TelegramClient(
                session,
                config.api_id,
                config.api_hash
            )
            
            await client.connect()
            await client.start()
            
            logger.info("SSE: Telethon client connected and started")
            
            # Send connected event
            yield {
                "event": "connected",
                "data": json.dumps({"status": "waiting", "message": "Listening for verification code..."})
            }
            
            # Flag to track if code was received
            code_received = asyncio.Event()
            verification_code = None
            
            # Register event handler for messages from 777000
            @client.on(events.NewMessage(from_users=777000))
            async def handler(event):
                nonlocal verification_code
                logger.info(f"SSE: Received message from 777000: {event.raw_text}")
                
                # Extract verification code
                code = telegram_client._extract_verification_code(event.raw_text)
                if code:
                    verification_code = code
                    code_received.set()
                    logger.info(f"SSE: Verification code extracted: {code}")
            
            # Keep connection alive and wait for code or timeout
            while time.time() - start_time < timeout:
                # Check if code was received
                if code_received.is_set():
                    # Send code event
                    yield {
                        "event": "code",
                        "data": json.dumps({"code": verification_code})
                    }
                    logger.info(f"SSE: Code event sent: {verification_code}")
                    break
                
                # Send heartbeat event
                elapsed = int(time.time() - start_time)
                yield {
                    "event": "heartbeat",
                    "data": json.dumps({"elapsed": elapsed, "remaining": timeout - elapsed})
                }
                
                # Wait 1 second before next iteration
                await asyncio.sleep(1)
            else:
                # Timeout occurred
                logger.warning("SSE: Timeout waiting for verification code")
                yield {
                    "event": "timeout",
                    "data": json.dumps({"error": "Timeout waiting for verification code", "timeout": timeout})
                }
        
        except AuthKeyUnregisteredError:
            logger.error("SSE: Session expired or invalid (AuthKeyUnregisteredError)")
            yield {
                "event": "error",
                "data": json.dumps({
                    "error": "Session expired or invalid",
                    "error_type": "auth_key_unregistered"
                })
            }
        except Exception as e:
            logger.error(f"SSE: Error during verification code listening: {e}")
            yield {
                "event": "error",
                "data": json.dumps({"error": str(e)})
            }
        
        finally:
            # Ensure client is disconnected in all cases
            if client is not None:
                try:
                    if client.is_connected():
                        await client.disconnect()
                        logger.info("SSE: Telethon client disconnected")
                except Exception as e:
                    logger.error(f"SSE: Error disconnecting client: {e}")
            
            # Decrement connection count
            async with sse_connections_lock:
                active_sse_connections -= 1
                logger.info(f"SSE connection closed. Active connections: {active_sse_connections}/{MAX_SSE_CONNECTIONS}")
    
    return EventSourceResponse(event_generator())


@app.get("/api/task/{uuid}")
async def get_task_info(uuid: str):
    """
    Get task information by UUID.
    
    Args:
        uuid: Task UUID
        
    Returns:
        JSON response with task information including session_string
        
    Raises:
        HTTPException: If UUID format is invalid (400), path traversal detected (400), or UUID not found (404)
    """
    logger.info(f"Get task info request for UUID: {uuid}")
    
    try:
        # Validate UUID and construct safe path
        session_file_path = validate_safe_path(uuid, config.data_dir)
    except ValueError as e:
        logger.warning(f"Invalid UUID or path traversal attempt: {uuid} - {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid UUID format or path traversal detected: {str(e)}"
        )
    
    # Check if file exists
    if not session_file_path.exists():
        logger.warning(f"UUID not found: {uuid}")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Task with UUID {uuid} not found"
        )
    
    try:
        # Load session file
        with open(session_file_path, 'r') as f:
            session_data = json.load(f)
        
        session_string = session_data.get("session_string")
        
        if not session_string:
            logger.error(f"Session string not found in file for UUID: {uuid}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Session string not found in task file"
            )
        
        logger.info(f"Task info retrieved for UUID: {uuid}")
        
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={
                "uuid": uuid,
                "session_string": session_string,
                "tg_id": session_data.get("tg_id"),
                "notify_chat_id": session_data.get("notify_chat_id"),
                "created_at": session_data.get("created_at"),
                "last_heartbeat": session_data.get("last_heartbeat"),
                "consecutive_failures": session_data.get("consecutive_failures", 0)
            }
        )
        
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse JSON file for UUID {uuid}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to parse task file"
        )
    except Exception as e:
        logger.error(f"Error loading task info for UUID {uuid}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error"
        )


@app.delete("/api/task/{uuid}")
async def delete_task(uuid: str):
    """
    Delete a keepalive task by UUID.
    
    Args:
        uuid: Task UUID
        
    Returns:
        JSON response confirming deletion
        
    Raises:
        HTTPException: If UUID format is invalid (400), path traversal detected (400), or UUID not found (404)
    """
    logger.info(f"Delete task request for UUID: {uuid}")
    
    try:
        # Validate UUID format
        if not validate_uuid_format(uuid):
            raise ValueError("Invalid UUID format")
    except ValueError as e:
        logger.warning(f"Invalid UUID format: {uuid} - {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid UUID format: {str(e)}"
        )
    
    # Check if task exists in session manager
    if uuid not in session_manager.sessions:
        logger.warning(f"UUID not found in session manager: {uuid}")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Task with UUID {uuid} not found"
        )
    
    try:
        # Use session manager's cleanup_task method for complete cleanup
        await session_manager.cleanup_task(uuid, "用户手动删除")
        
        logger.info(f"Task deleted successfully: {uuid}")
        
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={
                "status": "deleted",
                "uuid": uuid,
                "message": "Task deleted successfully"
            }
        )
        
    except Exception as e:
        logger.error(f"Error deleting task {uuid}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Internal server error during task deletion: {str(e)}"
        )


@app.get("/verifyCode/{uuid}")
async def verify_code_redirect(uuid: str):
    """
    Redirect to main page with UUID parameter for verification code listening.
    
    Args:
        uuid: Task UUID
        
    Returns:
        Redirect to main page with uuid query parameter
    """
    return RedirectResponse(url=f"/?uuid={uuid}", status_code=302)


async def main():
    """
    Main entry point for the application.
    
    Initializes all components and starts the FastAPI server.
    Handles graceful shutdown of all resources.
    """
    logger.info("=" * 80)
    logger.info("Starting Telegram Session Keepalive Manager")
    logger.info("=" * 80)
    
    # Load configuration
    try:
        config = Config(
            api_id=int(os.getenv("TG_API_ID", "32471437")),
            api_hash=os.getenv("TG_API_HASH", "c356cf8137a04c92ebfda0fdbd299604"),
            interval_seconds=int(os.getenv("TG_INTERVAL_SECONDS", "86400")),
            jitter_seconds=int(os.getenv("TG_JITTER_SECONDS", "300")),
            notify_bot_token=os.getenv("TG_NOTIFY_BOT_TOKEN", ""),
            notify_bot_name=os.getenv("TG_NOTIFY_BOT_NAME", ""),
            max_failures=int(os.getenv("TG_HEART_BEAT_MAX_FAIL", "3")),
            data_dir=os.getenv("DATA_DIR", "./data")
        )
        
        # Validate required configuration
        if not config.api_id or not config.api_hash:
            logger.error("FATAL: TG_API_ID and TG_API_HASH are required")
            raise ValueError("Missing required configuration: TG_API_ID and TG_API_HASH")
        
        logger.info("Configuration loaded successfully")
        logger.info(f"  - API ID: {config.api_id}")
        logger.info(f"  - Interval: {config.interval_seconds}s")
        logger.info(f"  - Jitter: {config.jitter_seconds}s")
        logger.info(f"  - Max failures: {config.max_failures}")
        logger.info(f"  - Data directory: {config.data_dir}")
        
    except Exception as e:
        logger.error(f"FATAL: Failed to load configuration: {e}")
        sys.exit(1)
    
    # Initialize scheduler
    try:
        scheduler = AsyncIOScheduler()
        logger.info("APScheduler initialized")
    except Exception as e:
        logger.error(f"FATAL: Failed to initialize APScheduler: {e}")
        sys.exit(1)
    
    # Initialize Telegram client wrapper
    try:
        telegram_client = TelegramClientWrapper(config.api_id, config.api_hash)
        logger.info("Telegram client wrapper initialized")
    except Exception as e:
        logger.error(f"FATAL: Failed to initialize Telegram client: {e}")
        sys.exit(1)
    
    # Initialize Bot notifier
    try:
        bot_notifier = BotNotifier(config.notify_bot_token)
        logger.info("Bot notifier initialized")
    except Exception as e:
        logger.error(f"FATAL: Failed to initialize Bot notifier: {e}")
        sys.exit(1)
    
    # Initialize Session Manager
    try:
        session_manager = SessionManager(scheduler, config, telegram_client, bot_notifier)
        logger.info("Session manager initialized")
    except Exception as e:
        logger.error(f"FATAL: Failed to initialize Session manager: {e}")
        sys.exit(1)
    
    # Start scheduler
    try:
        scheduler.start()
        logger.info("APScheduler started")
    except Exception as e:
        logger.error(f"FATAL: Failed to start APScheduler: {e}")
        sys.exit(1)
    
    # Initialize session manager (load existing tasks)
    try:
        await session_manager.initialize()
        logger.info("Session manager initialization complete")
    except Exception as e:
        logger.error(f"FATAL: Failed to initialize session manager: {e}")
        scheduler.shutdown(wait=False)
        sys.exit(1)
    
    logger.info("=" * 80)
    logger.info("Application startup complete - ready to accept requests")
    logger.info("=" * 80)
    
    # Get configuration from environment
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "8000"))
    reload = os.getenv("RELOAD", "false").lower() == "true"
    
    logger.info(f"Starting FastAPI server on {host}:{port}")
    
    # Import uvicorn here to avoid issues if not installed
    import uvicorn
    
    try:
        # Run the application
        await asyncio.to_thread(
            uvicorn.run,
            "web_server:app",
            host=host,
            port=port,
            reload=reload,
            log_level="info"
        )
    except KeyboardInterrupt:
        logger.info("Received keyboard interrupt, shutting down...")
    except Exception as e:
        logger.error(f"Error running server: {e}")
    finally:
        # Graceful shutdown
        logger.info("=" * 80)
        logger.info("Shutting down application")
        logger.info("=" * 80)
        
        try:
            scheduler.shutdown(wait=False)
            logger.info("APScheduler stopped")
        except Exception as e:
            logger.error(f"Error stopping scheduler: {e}")
        
        try:
            await bot_notifier.close()
            logger.info("Bot notifier closed")
        except Exception as e:
            logger.error(f"Error closing bot notifier: {e}")
        
        logger.info("=" * 80)
        logger.info("Application shutdown complete")
        logger.info("=" * 80)


# Mount static files - must be done after all routes are defined
# This catches all remaining routes and serves static files
static_dir = Path(__file__).parent / "static"
if static_dir.exists():
    app.mount("/", StaticFiles(directory=str(static_dir), html=True), name="static")
    logger.info(f"Static files mounted from: {static_dir}")
else:
    logger.warning(f"Static directory not found: {static_dir}")


if __name__ == "__main__":
    import uvicorn
    
    # Run the main function
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Application terminated by user")
        sys.exit(0)
    except Exception as e:
        logger.error(f"Fatal error: {e}")
        sys.exit(1)
