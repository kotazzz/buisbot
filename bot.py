from pyrogram import Client, filters
from pyrogram.types import Message
from pyrogram.enums import ParseMode
from database import Database, MessageImportance
from utils import generate_tags, format_chat_history, prevent_injection
from ai_service import call_gemini_api, GeminiModel
from config import API_ID, API_HASH, SESSION_NAME, DATABASE_PATH, BOT_OWNER_ID
import logging

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