"""
Bot Notifier module for sending Telegram notifications via Bot API.
"""

import httpx
import logging
from typing import Optional

logger = logging.getLogger(__name__)


class BotNotifier:
    """
    Handles sending notifications through Telegram Bot API.
    
    Sends notifications for:
    - Successful heartbeat operations
    - Failed heartbeat operations
    - Task cleanup/removal
    """
    
    def __init__(self, bot_token: str):
        """
        Initialize the Bot Notifier.
        
        Args:
            bot_token: Telegram Bot API token
        """
        self.bot_token = bot_token
        self.base_url = f"https://api.telegram.org/bot{bot_token}"
        self.client = httpx.AsyncClient(timeout=30.0)
    
    async def _send_message(self, chat_id: int, text: str) -> bool:
        """
        Send a message via Telegram Bot API.
        
        Args:
            chat_id: Telegram chat ID to send message to
            text: Message text to send
            
        Returns:
            True if message sent successfully, False otherwise
        """
        url = f"{self.base_url}/sendMessage"
        payload = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML"
        }
        
        try:
            response = await self.client.post(url, json=payload)
            
            if response.status_code == 200:
                logger.info(f"Notification sent successfully to chat_id={chat_id}")
                return True
            elif response.status_code == 401:
                # Unauthorized - invalid bot token
                logger.error(f"Bot token is invalid (401 Unauthorized)")
                return False
            elif response.status_code == 400:
                # Bad Request - likely user hasn't started the bot
                response_data = response.json()
                error_description = response_data.get("description", "Unknown error")
                
                if "chat not found" in error_description.lower() or "bot was blocked" in error_description.lower():
                    logger.warning(f"User {chat_id} has not started the bot or blocked it: {error_description}")
                else:
                    logger.error(f"Bad request when sending message to {chat_id}: {error_description}")
                return False
            else:
                logger.error(f"Failed to send notification: HTTP {response.status_code}")
                return False
                
        except httpx.RequestError as e:
            logger.error(f"Network error when sending notification: {e}")
            return False
        except Exception as e:
            logger.error(f"Unexpected error when sending notification: {e}")
            return False
    
    async def send_success(self, chat_id: int, uuid: str) -> bool:
        """
        Send a heartbeat success notification.
        
        Args:
            chat_id: Telegram chat ID to notify
            uuid: Task UUID
            
        Returns:
            True if notification sent successfully, False otherwise
        """
        text = (
            f"✅ <b>保活成功</b>\n\n"
            f"任务 ID: <code>{uuid}</code>\n"
            f"状态: 心跳执行成功"
        )
        return await self._send_message(chat_id, text)
    
    async def send_failure(self, chat_id: int, uuid: str, error: str) -> bool:
        """
        Send a heartbeat failure notification.
        
        Args:
            chat_id: Telegram chat ID to notify
            uuid: Task UUID
            error: Error message describing the failure
            
        Returns:
            True if notification sent successfully, False otherwise
        """
        text = (
            f"⚠️ <b>保活失败</b>\n\n"
            f"任务 ID: <code>{uuid}</code>\n"
            f"错误原因: {error}"
        )
        return await self._send_message(chat_id, text)
    
    async def send_cleanup(self, chat_id: int, uuid: str, reason: str) -> bool:
        """
        Send a task cleanup notification.
        
        Args:
            chat_id: Telegram chat ID to notify
            uuid: Task UUID
            reason: Reason for task cleanup
            
        Returns:
            True if notification sent successfully, False otherwise
        """
        text = (
            f"🗑️ <b>任务已清理</b>\n\n"
            f"任务 ID: <code>{uuid}</code>\n"
            f"清理原因: {reason}\n\n"
            f"该任务已被移除，不再执行保活操作。"
        )
        return await self._send_message(chat_id, text)
    
    async def close(self):
        """Close the HTTP client."""
        await self.client.aclose()
