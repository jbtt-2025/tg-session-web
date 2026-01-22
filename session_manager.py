"""
Session Manager module for managing Telegram session keepalive tasks.
Handles task creation, scheduling, execution, and cleanup.
"""

import asyncio
import json
import logging
import os
import random
import uuid as uuid_module
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from pydantic import ValidationError

from models import SessionData
from telegram_client import TelegramClientWrapper
from bot_notifier import BotNotifier


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


class Config:
    """Configuration class for session manager settings."""
    
    def __init__(
        self,
        api_id: int,
        api_hash: str,
        interval_seconds: int = 86400,
        jitter_seconds: int = 300,
        notify_bot_token: str = "",
        notify_bot_name: str = "",
        max_failures: int = 3,
        data_dir: str = "./data"
    ):
        self.api_id = api_id
        self.api_hash = api_hash
        self.interval_seconds = interval_seconds
        self.jitter_seconds = jitter_seconds
        self.notify_bot_token = notify_bot_token
        self.notify_bot_name = notify_bot_name
        self.max_failures = max_failures
        self.data_dir = data_dir


class SessionManager:
    """
    Manages multiple Telegram session keepalive tasks.
    
    Responsibilities:
    - Load and save session files from/to disk
    - Create and manage heartbeat tasks
    - Execute heartbeat operations
    - Handle failures and cleanup
    """
    
    def __init__(
        self,
        scheduler: AsyncIOScheduler,
        config: Config,
        telegram_client: TelegramClientWrapper,
        bot_notifier: BotNotifier
    ):
        """
        Initialize the Session Manager.
        
        Args:
            scheduler: APScheduler instance for task scheduling
            config: Configuration object with settings
            telegram_client: Telegram client wrapper instance
            bot_notifier: Bot notifier instance for sending notifications
        """
        self.scheduler = scheduler
        self.config = config
        self.telegram_client = telegram_client
        self.bot_notifier = bot_notifier
        
        # Ensure data directory exists
        self.data_dir = Path(config.data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        
        # In-memory cache of session data
        self.sessions: Dict[str, SessionData] = {}
        
        # TG_ID to UUID mapping for uniqueness constraint
        self.tg_id_to_uuid: Dict[int, str] = {}
        
        # File locks for concurrent file access protection
        self._file_locks: Dict[str, asyncio.Lock] = {}
        
        logger.info(f"SessionManager initialized with data_dir={self.data_dir}")
    
    async def initialize(self):
        """
        Initialize the session manager by loading all session files from disk.
        Scans the data directory and creates heartbeat tasks for all valid sessions.
        Detects and handles duplicate TG_IDs by keeping the newer task.
        """
        logger.info("Initializing SessionManager: scanning data directory")
        
        loaded_count = 0
        error_count = 0
        
        # Scan data directory for JSON files
        if not self.data_dir.exists():
            logger.warning(f"Data directory does not exist: {self.data_dir}")
            return
        
        # Phase 1: Load all session files into a temporary dict
        all_sessions = {}  # uuid -> SessionData
        for json_file in self.data_dir.glob("*.json"):
            try:
                session_data = self._load_session_file(json_file.stem)
                if session_data:
                    all_sessions[session_data.uuid] = session_data
            except Exception as e:
                error_count += 1
                logger.error(f"Failed to load session file {json_file}: {e}")
        
        # Phase 2: Group by TG_ID and find the newest for each
        tg_id_groups = {}  # tg_id -> list of (uuid, created_at)
        for uuid, session_data in all_sessions.items():
            tg_id = session_data.tg_id
            if tg_id not in tg_id_groups:
                tg_id_groups[tg_id] = []
            tg_id_groups[tg_id].append((uuid, session_data.created_at))
        
        # Phase 3: For each TG_ID, keep only the newest task
        tasks_to_keep = set()
        tasks_to_delete = set()
        
        for tg_id, uuid_list in tg_id_groups.items():
            if len(uuid_list) == 1:
                # No duplicates, keep this task
                tasks_to_keep.add(uuid_list[0][0])
            else:
                # Multiple tasks with same TG_ID, find the newest
                newest_uuid = max(uuid_list, key=lambda x: x[1])[0]
                tasks_to_keep.add(newest_uuid)
                
                # Mark others for deletion
                for uuid, _ in uuid_list:
                    if uuid != newest_uuid:
                        tasks_to_delete.add(uuid)
                        logger.warning(
                            f"Found duplicate tg_id {tg_id}: "
                            f"will delete old UUID {uuid}, keeping newer UUID {newest_uuid}"
                        )
        
        # Phase 4: Load tasks to keep and delete old ones
        for uuid in tasks_to_keep:
            session_data = all_sessions[uuid]
            
            # Store in cache
            self.sessions[session_data.uuid] = session_data
            self.tg_id_to_uuid[session_data.tg_id] = session_data.uuid
            
            # Start heartbeat task
            await self.start_heartbeat(session_data.uuid)
            
            loaded_count += 1
            logger.info(f"Loaded session: {session_data.uuid}")
        
        # Delete old duplicate files
        for uuid in tasks_to_delete:
            session_data = all_sessions[uuid]
            
            # Send cleanup notification
            await self.bot_notifier.send_cleanup(
                session_data.notify_chat_id,
                uuid,
                "被新任务替换"
            )
            
            # Delete file
            file_path = self.data_dir / f"{uuid}.json"
            try:
                if file_path.exists():
                    file_path.unlink()
                    logger.info(f"Deleted duplicate session file: {file_path}")
            except Exception as e:
                logger.error(f"Failed to delete session file {file_path}: {e}")
        
        logger.info(
            f"SessionManager initialization complete: "
            f"{loaded_count} tasks loaded, {error_count} errors"
        )
    
    def _load_session_file(self, uuid: str) -> Optional[SessionData]:
        """
        Load a session file from disk and parse it.
        
        Args:
            uuid: UUID of the session to load
            
        Returns:
            SessionData object if successful, None otherwise
            
        Raises:
            FileNotFoundError: If the session file does not exist
            json.JSONDecodeError: If the file contains invalid JSON
            ValidationError: If the data doesn't match SessionData schema
        """
        file_path = self.data_dir / f"{uuid}.json"
        
        if not file_path.exists():
            raise FileNotFoundError(f"Session file not found: {file_path}")
        
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            # Parse and validate with Pydantic
            session_data = SessionData(**data)
            
            logger.debug(f"Loaded session file: {uuid}")
            return session_data
            
        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON in session file {file_path}: {e}")
            raise
        except ValidationError as e:
            logger.error(f"Invalid session data in {file_path}: {e}")
            raise
        except PermissionError as e:
            logger.error(f"Permission denied reading {file_path}: {e}")
            raise
        except Exception as e:
            logger.error(f"Unexpected error loading {file_path}: {e}")
            raise
    
    def _write_json_file(self, file_path: Path, session_data: SessionData):
        """
        Synchronous method to write session data to a JSON file.
        This method is called from asyncio.to_thread to avoid blocking.
        
        Args:
            file_path: Path to the file to write
            session_data: SessionData object to save
            
        Raises:
            PermissionError: If unable to write to the file
            OSError: If other file system errors occur
        """
        try:
            # Convert to dict and handle datetime serialization
            data = session_data.model_dump(mode='json')
            
            # Write to file
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            
            logger.debug(f"Saved session file: {session_data.uuid}")
            
        except PermissionError as e:
            logger.error(f"Permission denied writing to {file_path}: {e}")
            raise
        except OSError as e:
            logger.error(f"File system error writing to {file_path}: {e}")
            raise
        except Exception as e:
            logger.error(f"Unexpected error saving {file_path}: {e}")
            raise
    
    async def _save_session_file(self, session_data: SessionData):
        """
        Asynchronously save a session data object to disk as JSON.
        Uses file locks to ensure thread-safe concurrent access.
        
        Args:
            session_data: SessionData object to save
            
        Raises:
            PermissionError: If unable to write to the file
            OSError: If other file system errors occur
        """
        file_path = self.data_dir / f"{session_data.uuid}.json"
        lock = self._get_file_lock(session_data.uuid)
        
        async with lock:
            # Use asyncio.to_thread to execute I/O in thread pool
            await asyncio.to_thread(self._write_json_file, file_path, session_data)
    
    async def create_task(self, session_string: str, notify_chat_id: int) -> str:
        """
        Create a new keepalive task.
        If a task with the same TG_ID already exists, it will be cleaned up first.
        
        Args:
            session_string: Telethon StringSession
            notify_chat_id: Chat ID to receive notifications
            
        Returns:
            UUID of the created task
            
        Raises:
            ValueError: If session validation fails
        """
        logger.info("Creating new keepalive task")
        
        # Validate session and get account info
        logger.debug(f"Validating session: {mask_sensitive_data(session_string)}")
        account_info = await self.telegram_client.validate_session(session_string)
        tg_id = account_info['tg_id']
        
        # Check if a task already exists for this TG_ID
        if tg_id in self.tg_id_to_uuid:
            old_uuid = self.tg_id_to_uuid[tg_id]
            logger.info(f"Found existing task for tg_id {tg_id}: {old_uuid}, will replace it")
            await self.cleanup_task(old_uuid, "被新任务替换")
        
        # Generate unique UUID
        task_uuid = str(uuid_module.uuid4())
        
        # Create session data
        session_data = SessionData(
            uuid=task_uuid,
            tg_id=tg_id,
            session_string=session_string,
            notify_chat_id=notify_chat_id,
            consecutive_failures=0,
            created_at=datetime.utcnow(),
            last_heartbeat=None
        )
        
        # Save to disk asynchronously
        await self._save_session_file(session_data)
        
        # Store in cache
        self.sessions[task_uuid] = session_data
        
        # Update TG_ID mapping
        self.tg_id_to_uuid[tg_id] = task_uuid
        
        # Start heartbeat task
        await self.start_heartbeat(task_uuid)
        
        logger.info(f"Created task {task_uuid} for user {tg_id}")
        return task_uuid
    
    async def start_heartbeat(self, uuid: str):
        """
        Start a heartbeat task for the given UUID.
        
        Args:
            uuid: UUID of the task to start
        """
        if uuid not in self.sessions:
            logger.error(f"Cannot start heartbeat: session {uuid} not found")
            return
        
        # Calculate first execution time (current time + interval + jitter)
        interval_seconds = self._calculate_next_interval()
        first_run_time = datetime.now() + timedelta(seconds=interval_seconds)
        
        # Use date trigger to schedule first execution
        self.scheduler.add_job(
            self._execute_heartbeat_and_reschedule,
            'date',
            run_date=first_run_time,
            id=uuid,
            args=[uuid],
            replace_existing=True
        )
        
        logger.info(f"Scheduled first heartbeat for {uuid} at {first_run_time}")
    
    async def stop_heartbeat(self, uuid: str):
        """
        Stop a heartbeat task for the given UUID.
        
        Args:
            uuid: UUID of the task to stop
        """
        try:
            self.scheduler.remove_job(uuid)
            logger.info(f"Stopped heartbeat task for {uuid}")
        except Exception as e:
            logger.warning(f"Failed to stop heartbeat task {uuid}: {e}")
    
    def _calculate_next_interval(self) -> int:
        """
        Calculate the next heartbeat interval with random jitter.
        
        Returns:
            Interval in seconds (base interval + random jitter)
        """
        jitter = random.randint(0, self.config.jitter_seconds)
        interval = self.config.interval_seconds + jitter
        return interval
    
    def _get_file_lock(self, uuid: str) -> asyncio.Lock:
        """
        Get or create a file lock for the given UUID.
        
        Args:
            uuid: UUID of the task
            
        Returns:
            asyncio.Lock for the given UUID
        """
        if uuid not in self._file_locks:
            self._file_locks[uuid] = asyncio.Lock()
        return self._file_locks[uuid]
    
    async def _execute_heartbeat_and_reschedule(self, uuid: str):
        """
        Execute a heartbeat operation and reschedule the next execution.
        
        Args:
            uuid: UUID of the task to execute heartbeat for
        """
        # Execute the heartbeat
        await self.execute_heartbeat(uuid)
        
        # If task still exists, schedule next execution
        if uuid in self.sessions:
            interval_seconds = self._calculate_next_interval()
            next_run_time = datetime.now() + timedelta(seconds=interval_seconds)
            
            self.scheduler.add_job(
                self._execute_heartbeat_and_reschedule,
                'date',
                run_date=next_run_time,
                id=uuid,
                args=[uuid],
                replace_existing=True
            )
            
            logger.info(f"Scheduled next heartbeat for {uuid} at {next_run_time}")
    
    async def execute_heartbeat(self, uuid: str):
        """
        Execute a heartbeat operation for the given task.
        
        Args:
            uuid: UUID of the task to execute heartbeat for
        """
        logger.info(f"Executing heartbeat for task {uuid}")
        
        if uuid not in self.sessions:
            logger.error(f"Cannot execute heartbeat: session {uuid} not found")
            return
        
        session_data = self.sessions[uuid]
        
        try:
            # Execute heartbeat
            logger.debug(f"Executing heartbeat for session: {mask_sensitive_data(session_data.session_string)}")
            success = await self.telegram_client.heartbeat(session_data.session_string)
            
            if success:
                await self._handle_success(uuid)
            else:
                await self._handle_failure(uuid, Exception("Heartbeat returned False"))
                
        except Exception as e:
            await self._handle_failure(uuid, e)
    
    async def _handle_success(self, uuid: str):
        """
        Handle successful heartbeat operation.
        
        Args:
            uuid: UUID of the task
        """
        session_data = self.sessions[uuid]
        
        # Reset failure count and update last heartbeat
        session_data.consecutive_failures = 0
        session_data.last_heartbeat = datetime.utcnow()
        
        # Save to disk asynchronously
        await self._save_session_file(session_data)
        
        # Send success notification
        await self.bot_notifier.send_success(
            session_data.notify_chat_id,
            uuid
        )
        
        logger.info(f"Heartbeat success for task {uuid}")
    
    async def _handle_failure(self, uuid: str, error: Exception):
        """
        Handle failed heartbeat operation.
        
        Args:
            uuid: UUID of the task
            error: Exception that caused the failure
        """
        session_data = self.sessions[uuid]
        
        # Increment failure count
        session_data.consecutive_failures += 1
        
        # Save to disk asynchronously
        await self._save_session_file(session_data)
        
        # Send failure notification
        await self.bot_notifier.send_failure(
            session_data.notify_chat_id,
            uuid,
            str(error)
        )
        
        logger.warning(
            f"Heartbeat failure for task {uuid}: "
            f"{session_data.consecutive_failures}/{self.config.max_failures}"
        )
        
        # Check if we've reached the failure threshold
        if session_data.consecutive_failures >= self.config.max_failures:
            reason = f"连续失败 {self.config.max_failures} 次"
            await self.cleanup_task(uuid, reason)
    
    async def cleanup_task(self, uuid: str, reason: str):
        """
        Clean up a task by deleting its file and stopping the heartbeat.
        Also cleans up the TG_ID to UUID mapping.
        
        Args:
            uuid: UUID of the task to clean up
            reason: Reason for cleanup
        """
        logger.info(f"Cleaning up task {uuid}: {reason}")
        
        if uuid not in self.sessions:
            logger.warning(f"Cannot cleanup: session {uuid} not found")
            return
        
        session_data = self.sessions[uuid]
        
        # Send cleanup notification
        await self.bot_notifier.send_cleanup(
            session_data.notify_chat_id,
            uuid,
            reason
        )
        
        # Stop heartbeat task
        await self.stop_heartbeat(uuid)
        
        # Delete session file
        file_path = self.data_dir / f"{uuid}.json"
        try:
            if file_path.exists():
                file_path.unlink()
                logger.info(f"Deleted session file: {file_path}")
        except Exception as e:
            logger.error(f"Failed to delete session file {file_path}: {e}")
        
        # Remove from cache
        del self.sessions[uuid]
        
        # Clean up TG_ID mapping (verify UUID matches before removing)
        if session_data.tg_id in self.tg_id_to_uuid:
            if self.tg_id_to_uuid[session_data.tg_id] == uuid:
                del self.tg_id_to_uuid[session_data.tg_id]
                logger.debug(f"Removed TG_ID mapping for {session_data.tg_id}")
            else:
                logger.warning(
                    f"TG_ID mapping mismatch for {session_data.tg_id}: "
                    f"expected {uuid}, found {self.tg_id_to_uuid[session_data.tg_id]}"
                )
        
        logger.info(f"Task {uuid} cleaned up successfully")
