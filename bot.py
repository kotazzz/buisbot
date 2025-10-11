import logging
import os
from typing import Optional

from google import genai
from pyrogram import Client, filters
from pyrogram.enums import ParseMode
from pyrogram.types import Message

from ai_service import GeminiModel, call_gemini_api, download_media
from database import Database, MessageImportance
from utils import format_chat_history, generate_tags


class Bot:
    """
    Business Bot class - encapsulates a single bot instance with its own client, database, and handlers
    """
    
    def __init__(self, session_name: str, api_id: int, api_hash: str, bot_owner_id: int, db_path: str, gemini_api_key: str):
        """
        Initialize a bot instance
        
        Args:
            session_name: Name for the Telegram session
            api_id: Telegram API ID
            api_hash: Telegram API Hash
            bot_owner_id: Telegram user ID of the bot owner
            db_path: Path to the SQLite database file
            gemini_api_key: Google Gemini API key for this bot instance
        """
        self.session_name = session_name
        self.owner_id = bot_owner_id
        
        # Initialize Pyrogram client
        # Sessions are stored in data/ directory
        self.client = Client(f"data/{session_name}", api_id=api_id, api_hash=api_hash)
        
        # Initialize database
        self.db = Database(db_path)
        
        # Initialize personal Gemini client for this bot
        if not gemini_api_key:
            logging.error(f"Gemini API key is missing for bot {session_name}. AI features will fail.")
            self.gemini_client = None
        else:
            self.gemini_client = genai.Client(api_key=gemini_api_key)
            logging.info(f"Gemini client initialized for bot '{session_name}'")
        
        # Register handlers
        self._register_handlers()
        
        logging.info(f"Bot '{session_name}' initialized")
    
    async def start(self):
        """Start the bot"""
        await self.client.start()
        me = await self.client.get_me()
        logging.info(f"Bot '{self.session_name}' started as {me.first_name} (@{me.username})")
    
    async def stop(self):
        """Stop the bot"""
        await self.client.stop()
        logging.info(f"Bot '{self.session_name}' stopped")
    
    # --- Custom Filters ---
    
    async def _whitelist_filter_func(self, _, __, message):
        """Filter function to check if chat is whitelisted"""
        return self.db.is_chat_whitelisted(message.chat.id)
    
    @property
    def whitelist(self):
        """Custom filter for whitelisted chats"""
        return filters.create(self._whitelist_filter_func)
    
    # --- Handler Registration ---
    
    def _register_handlers(self):
        """Register all message handlers"""
        
        # Test command
        self.client.on_message(
            filters.me & filters.command("test", prefixes="!") & self.whitelist
        )(self.test_command)
        
        # Whitelist management
        self.client.on_message(filters.me & filters.command("enable", prefixes="!"))(self.enable_command)
        self.client.on_message(filters.me & filters.command("disable", prefixes="!"))(self.disable_command)
        
        # Debug command
        self.client.on_message(filters.me & filters.command("debug", prefixes="!"))(self.debug_command)
        
        # Media analysis command
        self.client.on_message(filters.all & filters.command("media", prefixes="!"))(self.media_command)
        
        # Mark as important (must be before process_gemini to take precedence)
        self.client.on_message(filters.me & filters.command("Гемини", prefixes="!"))(self.mark_important)
        
        # Process Gemini requests
        self.client.on_message(filters.all & filters.regex("Гемини"))(self.process_gemini)
        
        # Store all messages (last handler, catches everything)
        self.client.on_message(filters.all)(self.store_message)
    
    # --- Command Handlers ---
    
    async def test_command(self, client, message: Message):
        """Test command to check if bot is working"""
        await message.reply(f"Привет мир от {self.session_name}")
    
    async def enable_command(self, client, message: Message):
        """Enable bot in current chat"""
        chat_id = message.chat.id
        if self.db.add_chat_to_whitelist(chat_id):
            await message.edit_text(f"{message.text}\n\nChat enabled ✅")
        else:
            await message.edit_text(f"{message.text}\n\nChat already enabled ✅")
    
    async def disable_command(self, client, message: Message):
        """Disable bot in current chat"""
        chat_id = message.chat.id
        if self.db.remove_chat_from_whitelist(chat_id):
            await message.edit_text(f"{message.text}\n\nChat disabled ❌")
        else:
            await message.edit_text(f"{message.text}\n\nChat already disabled ❌")
    
    async def debug_command(self, client, message: Message):
        """Show last messages from database"""
        chat_id = message.chat.id
        logging.info(f"Debug command triggered in chat {chat_id} by {self.session_name}")
        messages = self.db.get_last_messages(chat_id, 10)
        history = format_chat_history(messages)
        await message.reply(f"Last 10 messages:\n\n{history}")
    
    async def media_command(self, client, message: Message):
        """Analyze media file using Gemini"""
        # Check if Gemini client is available
        if not self.gemini_client:
            await message.reply("❌ Ошибка: Gemini API key не настроен для этого бота.")
            return
        
        # Check if the message is a reply to a message with media
        if not message.reply_to_message:
            await message.reply("Эта команда должна быть использована в ответ на сообщение с медиафайлом")
            return
        
        reply_msg = message.reply_to_message
        
        # Check if reply has supported media
        has_media = (
            reply_msg.photo
            or reply_msg.video
            or reply_msg.voice
            or reply_msg.audio
            or getattr(reply_msg, "animation", None)
            or getattr(reply_msg, "video_note", None)
            or (reply_msg.document and reply_msg.document.mime_type and 
                (reply_msg.document.mime_type.startswith(("image/", "video/", "audio/")) or 
                 reply_msg.document.mime_type == "application/ogg"))
        )
        
        if not has_media:
            await message.reply("В сообщении, на которое вы отвечаете, нет поддерживаемого медиафайла")
            return
        
        # Get prompt from message
        prompt_parts = message.text.split(" ", 1)
        prompt = prompt_parts[1].strip() if len(prompt_parts) > 1 else "Опиши этот медиафайл подробно"
        
        processing_msg = await message.reply("⏳ Загрузка и обработка медиафайла...")
        media_path: Optional[str] = None
        
        try:
            # Download media file
            media_path = await download_media(client, reply_msg)
            
            if not media_path or not os.path.exists(media_path):
                await processing_msg.edit_text("❌ Не удалось загрузить медиафайл")
                return
            
            file_size = os.path.getsize(media_path)
            if file_size == 0:
                await processing_msg.edit_text("❌ Загруженный файл пустой (0 байт)")
                if os.path.exists(media_path):
                    os.remove(media_path)
                return
            
            await processing_msg.edit_text(f"✅ Файл загружен ({file_size} байт)\n⏳ Отправляем в Gemini...")
            logging.info(f"[{self.session_name}] Calling Gemini for media analysis: {media_path}")
            
            # Call Gemini API with media (using bot's personal client)
            response = await call_gemini_api(
                client=self.gemini_client,
                query=prompt,
                media_paths=[media_path],
                is_media_request=True,
            )
            
            # Check for errors
            if response.startswith("Ошибка"):
                await processing_msg.edit_text(f"❌ {response}")
            else:
                # Send successful response
                try:
                    await processing_msg.edit_text(response, parse_mode=ParseMode.MARKDOWN)
                except Exception as e:
                    logging.warning(f"Failed to send with Markdown: {e}, sending as plain text.")
                    await processing_msg.edit_text(response)
                
                # Store the response in database
                self.db.store_message(
                    chat_id=message.chat.id,
                    message_id=processing_msg.id,
                    author="Gemini Media Analysis",
                    date=processing_msg.date,
                    content=response,
                    tags="media_analysis",
                    importance=MessageImportance.GEMINI,
                )
        
        except Exception as e:
            error_msg = f"Критическая ошибка при обработке медиафайла: {str(e)}"
            logging.exception(f"[{self.session_name}] Critical error during media command:")
            await processing_msg.edit_text(f"❌ {error_msg}")
        
        finally:
            # Clean up local file
            if media_path and os.path.exists(media_path):
                try:
                    os.remove(media_path)
                    logging.info(f"Removed local media file: {media_path}")
                except Exception as e_clean:
                    logging.error(f"Failed to remove local media file: {e_clean}")
    
    async def mark_important(self, client, message: Message):
        """Mark message as important (only for owner)"""
        if not message.from_user or message.from_user.id != self.owner_id:
            return
        
        chat_id = message.chat.id
        message_id = message.id
        author = message.from_user.first_name
        content = message.text
        tags = generate_tags(message)
        
        logging.info(f"[{self.session_name}] Marking message as important: {message_id}")
        
        # Store with Important flag
        self.db.store_message(
            chat_id=chat_id,
            message_id=message_id,
            author=author,
            date=message.date,
            content=content,
            tags=tags,
            importance=MessageImportance.IMPORTANT
        )
        
        await message.edit_text(f"{message.text}\n\nОтмечено как важное ⭐")
    
    async def process_gemini(self, client, message: Message):
        """Process Gemini request with chat history"""
        # Check if Gemini client is available
        if not self.gemini_client:
            await message.reply("❌ Ошибка: Gemini API key не настроен для этого бота.")
            return
        
        chat_id = message.chat.id
        
        # Check if chat is whitelisted or message is from owner
        if not message.from_user or (message.from_user.id != self.owner_id and not self.db.is_chat_whitelisted(chat_id)):
            logging.debug(f"[{self.session_name}] Ignoring Gemini request in non-whitelisted chat: {chat_id}")
            return
        
        logging.info(f"[{self.session_name}] Processing Gemini request in chat {chat_id}")
        
        # Store original message
        self.db.store_message(
            chat_id=chat_id,
            message_id=message.id,
            author=message.from_user.first_name if message.from_user else "unknown",
            date=message.date,
            content=message.text or "",
            tags=generate_tags(message),
            importance=MessageImportance.DEFAULT,
        )
        
        # Get chat history
        messages = self.db.get_last_messages(chat_id)
        history = format_chat_history(messages)
        
        # Extract query from message
        query = message.text
        if "," in query:
            query = query.split(",", 1)[1].strip()
        elif " " in query:
            query = query.split(" ", 1)[1].strip()
        else:
            query = ""
        
        combined_query = history + "\n\nТекущий запрос пользователя: " + query
        
        # Select model based on query
        model = GeminiModel.FLASH_THINKING if "!думай" in query.lower() else GeminiModel.FLASH
        
        try:
            # Send a "Thinking..." message first
            thinking_message = await message.reply("💭 Думаю...")
            
            # Call Gemini API (using bot's personal client)
            response = await call_gemini_api(self.gemini_client, combined_query, model)
            
            # For non-owner users, we could add injection protection here if needed
            # But since we removed prevent_injection (it was unreliable),
            # we rely on command filters to prevent self-commands
            
            # Try editing with Markdown first
            try:
                await thinking_message.edit_text(response, parse_mode=ParseMode.MARKDOWN)
            except Exception as e:
                logging.warning(f"Failed to send with Markdown: {e}")
                await thinking_message.edit_text(response)
            
            # Store the Gemini response
            self.db.store_message(
                chat_id=chat_id,
                message_id=thinking_message.id,
                author="Gemini",
                date=thinking_message.date,
                content=response,
                tags="",
                importance=MessageImportance.GEMINI
            )
        
        except Exception as e:
            error_msg = f"Error processing request: {str(e)}"
            logging.error(f"[{self.session_name}] {error_msg}")
            if "thinking_message" in locals():
                await thinking_message.edit_text(f"❌ {error_msg}")
            else:
                await message.reply(f"❌ {error_msg}")
    
    async def store_message(self, client, message: Message):
        """Store all messages in the database"""
        # Skip messages without text content
        if not message.text and not message.caption:
            return
        
        # Only store messages from whitelisted chats or owner's chats
        chat_id = message.chat.id
        if not (message.from_user and message.from_user.id == self.owner_id) and not self.db.is_chat_whitelisted(chat_id):
            return
        
        message_id = message.id
        author = message.from_user.first_name if message.from_user else "unknown"
        content = message.text or message.caption or ""
        tags = generate_tags(message)
        
        # Store the message
        self.db.store_message(
            chat_id=chat_id,
            message_id=message_id,
            author=author,
            date=message.date,
            content=content,
            tags=tags,
            importance=MessageImportance.DEFAULT
        )
        
        logging.debug(f"[{self.session_name}] Stored message: {message_id} from {author}")
