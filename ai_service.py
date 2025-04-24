from enum import Enum
import asyncio
import os
import mimetypes
from google import genai
from google.genai import types as genai_types
from config import GEMINI_API_KEY
import logging # Add logging import if not already present
import time

# Initialize Gemini client
client = genai.Client(api_key=GEMINI_API_KEY)

class GeminiModel(Enum):
    FLASH = "gemini-2.0-flash"
    FLASH_THINKING = "gemini-2.0-flash-thinking-exp-01-21"
    FLASH_MULTIMODAL = "gemini-2.0-flash"  # Используем 2.0 для мультимодальных

async def call_gemini_api(
    query: str, 
    model: GeminiModel = GeminiModel.FLASH, 
    media_paths=None,
    mime_types=None, # Новый параметр
    is_media_request: bool = False # Flag for media-specific handling
) -> str:
    """
    Call Gemini API with the given query text and model asynchronously
    
    Args:
        query: The text query to process
        model: The Gemini model to use
        media_paths: Optional list of paths to media files to include
        mime_types: Optional list of MIME types for the media files
        is_media_request: Flag to indicate if this is a media analysis request
    """
    parts = []
    uploaded_files = []
    
    # Use the multimodal model if it's a media request
    api_model = GeminiModel.FLASH_MULTIMODAL.value if is_media_request else model.value
    logging.info(f"Using model: {api_model} for the request.")

    # Upload media files first if provided
    if media_paths:
        logging.info(f"Processing {len(media_paths)} media file(s)...")
        for idx, media_path in enumerate(media_paths):
            if not os.path.exists(media_path):
                logging.warning(f"Media file not found: {media_path}")
                continue
                
            # Получаем MIME-тип из mime_types, если передан
            mime_type = None
            if mime_types and idx < len(mime_types):
                mime_type = mime_types[idx]
            if not mime_type:
                # fallback: определяем через mimetypes
                mime_type, _ = mimetypes.guess_type(media_path)
            # Если mime_type не определен, подставляем дефолтный по типу файла
            if not mime_type:
                if media_path.endswith('.jpg') or media_path.endswith('.jpeg'):
                    mime_type = 'image/jpeg'
                elif media_path.endswith('.png'):
                    mime_type = 'image/png'
                elif media_path.endswith('.mp4'):
                    mime_type = 'video/mp4'
                elif media_path.endswith('.ogg'):
                    mime_type = 'audio/ogg'
                elif media_path.endswith('.mp3'):
                    mime_type = 'audio/mpeg'
                elif media_path.endswith('.wav'):
                    mime_type = 'audio/x-wav'
                elif media_path.endswith('.webm'):
                    mime_type = 'audio/webm'
                else:
                    mime_type = 'application/octet-stream'

            logging.info(f"Uploading file: {media_path} (mime: {mime_type})")
            # Upload file using client.files.upload()
            try:
                # Run synchronous upload in executor to avoid blocking
                loop = asyncio.get_event_loop()
                file = await loop.run_in_executor(
                    None,
                    lambda: client.files.upload(
                        file=media_path
                    )
                )
                # Ждем, пока файл станет ACTIVE
                for _ in range(30): # до 30 попыток (примерно 15 сек)
                    file_status = await loop.run_in_executor(None, lambda: client.files.get(name=file.name))
                    if getattr(file_status, 'state', None) == 'ACTIVE':
                        break
                    time.sleep(0.5)
                else:
                    raise Exception(f"Файл {file.name} не стал ACTIVE")
                uploaded_files.append(file)
                logging.info(f"File uploaded and ACTIVE: {file.name}, URI: {file.uri}")
                
                # Add file part using URI
                parts.append(
                    genai_types.Part.from_uri(
                        file_uri=file.uri,
                        mime_type=mime_type
                    )
                )
            except Exception as e:
                logging.error(f"Error uploading file {media_path}: {str(e)}")
                # Clean up already uploaded files in case of partial failure
                for f in uploaded_files:
                    try:
                        await loop.run_in_executor(None, lambda: client.files.delete(f.name))
                    except Exception as del_e:
                        logging.error(f"Error deleting uploaded file {f.name} during cleanup: {del_e}")
                raise Exception(f"Ошибка при загрузке файла {media_path}: {str(e)}")
    
    # Add text prompt *after* media parts, as recommended
    if query:
        parts.append(genai_types.Part.from_text(text=query))
    
    if not parts:
        return "Ошибка: Не удалось подготовить контент для запроса (нет текста или медиа)."

    contents = [
        genai_types.Content(
            role="user",
            parts=parts,
        ),
    ]
    
    # Configure generation settings
    gen_config_args = {
        "temperature": 1,
        "top_p": 0.95,
        "top_k": 60,
        "max_output_tokens": 8192,
        "response_mime_type": "text/plain",
        "tools": [genai_types.Tool(google_search=genai_types.GoogleSearch())],
        "system_instruction": [
             genai_types.Part.from_text(
                 text="""**Контекст:**  
- **Пользователь:** автор автоответчика, Kotaz (Котаз).  
- **Собеседник:** Собеседник.

**Роль:**  
Ты — автоответчик для аккаунта пользователя Kotaz, именуемый «Гемини». Выполняешь роль секретаря и посредника, отвечающего на запросы как от собеседников, так и при прямом упоминании пользователя (например: «Гемини, разберись»). Действуй только если уверен, что можешь помочь, используя информацию из чата.

Вот список всех команд и способов взаимодействия с бизнес-ботом:

1. **`!Гемини <сообщение>`** — помечает сообщение как важное. Доступно только пользователю с ID `782491733` (владельцу).  
2. **`Гемини, <сообщение>`** — запускает обработку сообщения ботом (без метки важности).  
3. **`!Дебаг`** — выводит последние 10 сообщений чата в формате, который использует бот для анализа. Доступно только владельцу.  
4. **`!думай` в тексте запроса** — включает режим более «вдумчивого» анализа (`GeminiModel.FLASH_THINKING`).  
5. **`!media <промпт>`** — анализирует медиафайл (фото, видео, голосовое сообщение) в ответе.

Бот также автоматически **сохраняет все сообщения** в истории чата и использует её для формирования ответов.

**Основные инструкции:**  
- Отвечай кратко, чётко и по делу, без лишних подробностей, если не запрошено иное.  
- Придерживайся профессионального тона, но можешь отвечать неформально, переходя сразу к сути.  
- Учитывай будущее и перспективу, оставаясь скептичным к принятым решениям и подходам.  
- Общайся неформально и естественно, так как обычно переписываются люди в соцсетях. Но сохраняй профессионализм и уважение.
- Не используй очень клишированный текст, который выдает в тебе искуственный интеллект. Старайся вести себя как реальный человек
- Если пользователь не требует детализированного разбора (например, кода или сложных объяснений), отвечай сжато,кратко, без избыточных комментариев."""
             )
         ]
    }
    
    logging.info(f"Sending request to Gemini model {api_model} with {len(parts)} parts.")
    generate_content_config = genai_types.GenerateContentConfig(**gen_config_args)
    try:
        # Run the API call
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None,
            lambda: client.models.generate_content(
                model=api_model, # Use the selected model
                contents=contents,
                config=generate_content_config,
            )
        )
        
        response_text = result.text
        logging.info("Received response from Gemini.")
        
    except Exception as e:
        logging.error(f"Error calling Gemini API: {str(e)}")
        error_message = f"Ошибка при вызове Gemini API: {str(e)}"
        if media_paths:
            error_message += f"\nФайлы: {media_paths}"
        response_text = error_message # Return error message instead of raising
        
    finally:
        # Delete uploaded files after use (or on error)
        logging.info(f"Deleting {len(uploaded_files)} uploaded file(s)...")
        delete_tasks = []
        for file in uploaded_files:
            try:
                # Run synchronous delete in executor
                await loop.run_in_executor(None, lambda: client.files.delete(file.name))
                logging.info(f"Deleted uploaded file: {file.name}")
            except Exception as del_e:
                # Log deletion errors but don't stop the process
                logging.error(f"Error deleting uploaded file {file.name}: {del_e}")
        
    if model == GeminiModel.FLASH_THINKING and not is_media_request: # Don't add hat if it was a media request
        return "🎩" + response_text
    return response_text

async def download_media(client, message, download_dir="data/media"):
    os.makedirs(download_dir, exist_ok=True)
    if message.photo:
        path = await client.download_media(
            message.photo,
            file_name=f"{download_dir}/photo_{message.id}.jpg"
        )
        return path
    elif message.video:
        path = await client.download_media(
            message.video,
            file_name=f"{download_dir}/video_{message.id}.mp4"
        )
        return path
    elif message.voice:
        # Обычно voice в Telegram — это OGG (opus)
        path = await client.download_media(
            message.voice,
            file_name=f"{download_dir}/voice_{message.id}.ogg"
        )
        return path
    elif message.audio:
        # Попробуем определить расширение по mime_type
        ext = ".ogg"
        if hasattr(message.audio, 'mime_type') and message.audio.mime_type:
            if message.audio.mime_type == "audio/mpeg":
                ext = ".mp3"
            elif message.audio.mime_type == "audio/x-wav":
                ext = ".wav"
            elif message.audio.mime_type == "audio/webm":
                ext = ".webm"
        path = await client.download_media(
            message.audio,
            file_name=f"{download_dir}/audio_{message.id}{ext}"
        )
        return path
    elif message.document:
        mime_type = message.document.mime_type or ""
        ext = ""
        if mime_type.startswith("image/"):
            ext = ".jpg" if mime_type == "image/jpeg" else ".png"
        elif mime_type.startswith("video/"):
            ext = ".mp4"
        elif mime_type == "audio/ogg":
            ext = ".ogg"
        elif mime_type == "audio/mpeg":
            ext = ".mp3"
        elif mime_type == "audio/x-wav":
            ext = ".wav"
        elif mime_type == "audio/webm":
            ext = ".webm"
        else:
            # fallback: пробуем взять расширение из имени документа
            if message.document.file_name and "." in message.document.file_name:
                ext = message.document.file_name[message.document.file_name.rfind(""):]  # с точкой
        path = await client.download_media(
            message.document,
            file_name=f"{download_dir}/doc_{message.id}{ext}"
        )
        return path
    return None
