from pyrogram import Client, filters
from pyrogram.types import Message
from pyrogram.enums import ParseMode
from database import Database, MessageImportance
from utils import generate_tags, format_chat_history, prevent_injection
from ai_service import call_gemini_api, GeminiModel, download_media
from config import API_ID, API_HASH, SESSION_NAME, DATABASE_PATH, BOT_OWNER_ID
import logging
import os

# Initialize the userbot client
app = Client(SESSION_NAME, api_id=API_ID, api_hash=API_HASH)

# Initialize database
db = Database(DATABASE_PATH)

# Custom filter to check if chat is whitelisted
def whitelist_filter(_, __, message):
    return db.is_chat_whitelisted(message.chat.id)

# Create custom filters
whitelist = filters.create(whitelist_filter)

# Basic commands
@app.on_message(filters.me & filters.command("test", prefixes="!") & whitelist)
async def test_command(client, message: Message):
    await message.reply("Привет мир")

@app.on_message(filters.me & filters.command("enable", prefixes="!"))
async def enable_command(client, message: Message):
    chat_id = message.chat.id
    if db.add_chat_to_whitelist(chat_id):
        await message.edit_text(f"{message.text}\n\nChat enabled ✅")
    else:
        await message.edit_text(f"{message.text}\n\nChat already enabled ✅")

@app.on_message(filters.me & filters.command("disable", prefixes="!"))
async def disable_command(client, message: Message):
    chat_id = message.chat.id
    if db.remove_chat_from_whitelist(chat_id):
        await message.edit_text(f"{message.text}\n\nChat disabled ❌")
    else:
        await message.edit_text(f"{message.text}\n\nChat already disabled ❌")

# Debug command
@app.on_message(filters.me & filters.command("debug", prefixes="!"))
async def debug_command(client, message: Message):
    chat_id = message.chat.id
    logging.info(f"Debug command triggered in chat {chat_id}")
    messages = db.get_last_messages(chat_id, 10)
    history = format_chat_history(messages)
    await message.reply(f"Last 10 messages:\n\n{history}")

# Media analysis command
@app.on_message(filters.all & filters.command("media", prefixes="!"))
async def media_command(client, message: Message):
    # Check if the message is a reply to a message with media
    if not message.reply_to_message:
        await message.reply("Эта команда должна быть использована в ответ на сообщение с медиафайлом")
        return
    
    reply_msg = message.reply_to_message
    
    # Поддержка новых типов медиа
    if reply_msg.photo:
        media_info = f"photo (file_id: {reply_msg.photo.file_id[:20]}...)"
    elif reply_msg.video:
        media_info = f"video (file_id: {reply_msg.video.file_id[:20]}...)"
    elif reply_msg.voice:
        media_info = f"voice (file_id: {reply_msg.voice.file_id[:20]}...)"
    elif getattr(reply_msg, 'animation', None):
        media_info = f"gif (file_id: {reply_msg.animation.file_id[:20]}...)"
    elif getattr(reply_msg, 'video_note', None):
        media_info = f"video_note (file_id: {reply_msg.video_note.file_id[:20]}...)"
    elif reply_msg.audio:
        media_info = f"audio (file_id: {reply_msg.audio.file_id[:20]}...)"
    elif reply_msg.document and reply_msg.document.mime_type:
        media_info = f"document (mime: {reply_msg.document.mime_type})"
    
    # Обновленная проверка has_media
    has_media = (
        reply_msg.photo or reply_msg.video or reply_msg.voice or reply_msg.audio or
        getattr(reply_msg, 'animation', None) or getattr(reply_msg, 'video_note', None) or
        (reply_msg.document and reply_msg.document.mime_type and 
         (reply_msg.document.mime_type.startswith(("image/", "video/", "audio/")) or reply_msg.document.mime_type == "application/ogg"))
    )
    
    if not has_media:
        await message.reply("В сообщении, на которое вы отвечаете, нет поддерживаемого медиафайла (фото, видео, аудио, голос)")
        return
    
    # Get prompt from message
    prompt = message.text.split(" ", 1)
    if len(prompt) > 1:
        prompt = prompt[1].strip()
    else:
        prompt = "Опиши этот медиафайл подробно" # Default prompt
    
    processing_msg = await message.reply(f"⏳ Загрузка и обработка медиафайла ({media_info})...")
    media_path = None # Initialize media_path
    
    try:
        # Download media file locally first
        media_path = await download_media(client, reply_msg)
        
        if not media_path:
            await processing_msg.edit_text("❌ Не удалось загрузить медиафайл локально")
            return
        
        await processing_msg.edit_text(f"✅ Файл загружен локально: {os.path.basename(media_path)}\n⏳ Отправляем в Gemini для анализа...")
        logging.info(f"Local media file downloaded: {media_path}")
        
        # Check if the file exists and has content
        if not os.path.exists(media_path):
            await processing_msg.edit_text(f"❌ Локальный файл не найден после загрузки: {media_path}")
            return
            
        file_size = os.path.getsize(media_path)
        if file_size == 0:
            await processing_msg.edit_text(f"❌ Загруженный локальный файл пустой (0 байт): {media_path}")
            # Clean up empty file
            try:
                os.remove(media_path)
            except Exception as e_clean:
                logging.error(f"Failed to remove empty local file: {e_clean}")
            return
            
        logging.info(f"File size: {file_size} bytes")
        logging.info(f"Calling Gemini API for media analysis. Prompt: '{prompt[:50]}...' File: {media_path}")
        
        # Call Gemini API with media, indicating it's a media request
        response = await call_gemini_api(
            query=prompt,
            # Model selection is now handled inside call_gemini_api based on is_media_request
            media_paths=[media_path],
            is_media_request=True # Pass the flag here
        )
        
        # Проверяем, не является ли ответ сообщением об ошибке от call_gemini_api
        if response.startswith("Ошибка при вызове Gemini API:") or response.startswith("Ошибка:"):
            await processing_msg.edit_text(f"❌ {response}")
            # No return here, finally block will clean up local file
        else:
            # Send successful response
            try:
                await processing_msg.edit_text(response, parse_mode=ParseMode.MARKDOWN)
            except Exception as e:
                logging.warning(f"Failed to send with Markdown: {e}, sending as plain text.")
                await processing_msg.edit_text(response)
                
            # Store the response in database
            db.store_message(
                chat_id=message.chat.id,
                message_id=processing_msg.id,
                author="Gemini Media Analysis",
                date=processing_msg.date,
                content=response,
                tags="media_analysis",
                importance=MessageImportance.GEMINI
            )
            
    except Exception as e:
        error_msg = f"Критическая ошибка при обработке медиафайла: {str(e)}"
        logging.exception("Critical error during media command processing:") # Log full traceback
        await processing_msg.edit_text(f"❌ {error_msg}")
        
    finally:
        # Clean up the *local* downloaded file in all cases (success, API error, other exceptions)
        if media_path and os.path.exists(media_path):
            try:
                os.remove(media_path)
                logging.info(f"Removed local media file: {media_path}")
            except Exception as e_clean:
                logging.error(f"Failed to remove local media file during cleanup: {e_clean}")

# Mark messages as important - use command filter instead of regex
@app.on_message(filters.me & filters.command("Гемини", prefixes="!"))
async def mark_important(client, message: Message):
    chat_id = message.chat.id
    message_id = message.id
    author = message.from_user.first_name
    content = message.text
    tags = generate_tags(message)
    
    logging.info(f"Marking message as important: {message_id}")
    
    # Store with Important flag
    db.store_message(
        chat_id=chat_id,
        message_id=message_id,
        author=author,
        date=message.date,
        content=content,
        tags=tags,
        importance=MessageImportance.IMPORTANT
    )
    
    await message.edit_text(f"{message.text}\n\nОтмечено как важное ⭐")

# Process Gemini requests - modified to send a "Thinking..." message first
@app.on_message(filters.all & filters.regex("Гемини"))
async def process_gemini(client, message: Message):
    chat_id = message.chat.id
    
    # Check if chat is whitelisted 
    if not message.from_user or (message.from_user.id != BOT_OWNER_ID and not db.is_chat_whitelisted(chat_id)):
        logging.info(f"Ignoring Gemini request in non-whitelisted chat: {chat_id}")
        return
    
    logging.info(f"Processing Gemini request in chat {chat_id}: {message.text[:20]}...")
    
    # Store original message
    db.store_message(
        chat_id=chat_id,
        message_id=message.id,
        author=message.from_user.first_name if message.from_user else "unknown",
        date=message.date,
        content=message.text or "",
        tags=generate_tags(message),
        importance=MessageImportance.DEFAULT
    )
    
    # Get chat history
    messages = db.get_last_messages(chat_id)
    history = format_chat_history(messages)
    
    # Extract query from message - more flexible pattern matching
    query = message.text
    if "," in query:
        query = query[query.find(",")+1:].strip()
    elif " " in query:
        query = query[query.find(" ")+1:].strip()
    else:
        query = ""
        
    combined_query = history + "\n\nТекущий запрос пользователя: " + query
    
    # Select model based on query
    model = GeminiModel.FLASH_THINKING if "!думай" in query.lower() else GeminiModel.FLASH
    
    try:
        # Send a "Thinking..." message first
        thinking_message = await message.reply("💭 Думаю...")
        
        # Call Gemini API asynchronously
        response = await call_gemini_api(combined_query, model)
        
        if not (message.from_user and message.from_user.id == BOT_OWNER_ID):
            # Disabled due edit instead of reply
            response = prevent_injection(response)
        # Try editing with Markdown first
        try:
            await thinking_message.edit_text(response, parse_mode=ParseMode.MARKDOWN)
        except Exception as e:
            logging.error(f"Failed to send with Markdown: {e}")
            # If Markdown fails, send as plain text
            await thinking_message.edit_text(response)
        
        # Store the Gemini response
        db.store_message(
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
        logging.error(error_msg)
        if 'thinking_message' in locals():
            await thinking_message.edit_text(f"❌ {error_msg}")
        else:
            await message.reply(error_msg)

# Store all messages in the database
@app.on_message(filters.all)
async def store_message(client, message: Message):
    # Skip messages without text content
    if not message.text and not message.caption:
        return

    chat_id = message.chat.id
    message_id = message.id
    author = message.from_user.first_name if message.from_user else "unknown"
    content = message.text or message.caption or ""
    tags = generate_tags(message)
    
    # Check if message should be marked as important
    importance = MessageImportance.DEFAULT
    
    # Store the message
    db.store_message(
        chat_id=chat_id,
        message_id=message_id,
        author=author,
        date=message.date,
        content=content,
        tags=tags,
        importance=importance
    )
    
    logging.info(f"Stored message: {message_id} from {author}")