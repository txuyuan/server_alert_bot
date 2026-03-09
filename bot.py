#!/usr/bin/env python3
"""
Telegram Bot for Server Alerts
Handles authorization and forwards alerts to authorized users
"""

import os
import subprocess
import logging
import asyncio
from pathlib import Path
from datetime import datetime
from typing import Set, Dict, Any

from dotenv import load_dotenv
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

load_dotenv()

logging.basicConfig(
    format='%(asctime)s [%(levelname)s] [%(name)s] %(message)s',
    level=logging.INFO
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

class AlertBot:
    def __init__(self):
        self.config = self.load_config()
        self.authorized_users = self.load_authorized_users()
        self.application = None
        self._loop = None  # Store the event loop

    def load_config(self) -> Dict[str, Any]:
        return {
            'bot_token': os.getenv('BOT_TOKEN'),
            'alert_server_host': os.getenv('ALERT_SERVER_HOST', 'localhost'),
            'alert_server_port': int(os.getenv('ALERT_SERVER_PORT', 8080))
        }

    def load_authorized_users(self) -> Set[int]:
        authorized = set()
        users_file = Path("authorized_users.txt")
        if not users_file.exists():
            logger.warning("authorized_users.txt not found. Creating empty file.")
            users_file.touch()
            return authorized
        with open(users_file, 'r') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#'):
                    try:
                        user_id = int(line.split('#')[0].strip())
                        authorized.add(user_id)
                    except ValueError:
                        logger.warning(f"Invalid user ID in line: {line}")
        logger.info(f"Loaded {len(authorized)} authorized users")
        return authorized

    def is_authorized(self, user_id: int) -> bool:
        return user_id in self.authorized_users

    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user = update.effective_user
        if not self.is_authorized(user.id):
            await update.message.reply_text(
                "❌ You are not authorized to use this bot.\n"
                "Please contact the administrator."
            )
            logger.warning(f"Unauthorized access attempt by user {user.id}")
            return
        await update.message.reply_text(
            f"✅ Welcome {user.first_name}!\n"
            f"Server Alert Bot is active.\n"
            f"You will receive alerts from your servers here."
        )

    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self.is_authorized(update.effective_user.id):
            return
        help_text = f"""
🤖 *Server Alert Bot Commands*

*Basic Commands:*
/start - Initialize the bot
/help - Show this help message
/status - Check bot status

*Alert Server Info:*
The alert server is running on:
Host: {self.config['alert_server_host']}
Port: {self.config['alert_server_port']}

To send alerts, use:
curl -X POST http://{self.config['alert_server_host']}:{self.config['alert_server_port']}/alert \
-H "Content-Type: application/json" \
-d '{{"program": "backup", "message": "Backup completed"}}'
        """
        await update.message.reply_text(help_text, parse_mode='Markdown')

    async def status_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self.is_authorized(update.effective_user.id):
            return
        status_text = f"""
📊 *Bot Status*
Authorized users: {len(self.authorized_users)}
Alert server: {'Running' if self.check_alert_server() else 'Not running'}

📊 *Server Status*
Uptime: {subprocess.run(["uptime"], capture_output=True).stdout.decode('utf-8')} 

        """
        await update.message.reply_text(status_text, parse_mode='Markdown')

    def check_alert_server(self) -> bool:
        import socket
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            result = sock.connect_ex((
                self.config['alert_server_host'],
                self.config['alert_server_port']
            ))
            sock.close()
            return result == 0
        except:
            return False

    async def _broadcast_alert_async(self, program: str, message: str, timestamp: str, ignore_errors: bool = False):
        """Asynchronous method that actually sends the messages."""
        alert_message = f"""
⚠️ *Server Alert*
*Program:* `{program}`
*Time:* `{timestamp}`

```alert
{message}
```
        """
        success_count = 0
        failed_users = []
        for user_id in self.authorized_users:
            try:
                await self.application.bot.send_message(
                    chat_id=user_id,
                    text=alert_message,
                    parse_mode='Markdown'
                )
                success_count += 1
                await asyncio.sleep(0.05)  # rate limit
            except Exception as e:
                logger.error(f"Failed to send alert to user {user_id}: {e}")
                failed_users += [user_id]

        if failed_users and not ignore_errors:
            follow_up_message = f"""
Some users failed to receive the previous alert.
Delivered to: {success_count}/{len(self.authorized_users)} users
Failed users: {', '.join(failed_users)}
            """
            await self._broadcast_alert_async(
                program="system",
                message=follow_up_message,
                timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            ignore_errors=True
            )

        logger.info(f"Alert broadcast to {success_count}/{len(self.authorized_users)} users")

    def send_alert(self, program: str, message: str):
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        if self.application is None:
            logger.error("Bot application not ready; alert dropped.")
            return

        if self._loop is None:
            logger.error("Event loop not available; alert dropped.")
            return

        # Schedule the async broadcast in the bot's event loop
        asyncio.run_coroutine_threadsafe(
            self._broadcast_alert_async(program, message, timestamp),
            self._loop
        )

    async def post_init(self, application):
        """Called after application initialization to capture the event loop."""
        self._loop = asyncio.get_running_loop()
        logger.info(f"Event loop captured: {self._loop}")

    def run(self):
        if not self.config['bot_token']:
            raise ValueError("BOT_TOKEN not set in .env file")
        
        # Build the application with post_init hook
        self.application = Application.builder()\
            .token(self.config['bot_token'])\
            .post_init(self.post_init)\
            .build()
        
        self.application.add_handler(CommandHandler("start", self.start_command))
        self.application.add_handler(CommandHandler("help", self.help_command))
        self.application.add_handler(CommandHandler("status", self.status_command))

        logger.info("Starting bot...")
        # This blocks; the bot's event loop runs here
        self.application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    bot = AlertBot()
    bot.run()
