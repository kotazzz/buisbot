import asyncio
import logging
import mimetypes
import os
import time
from enum import Enum
from typing import List, Optional, Tuple

from google import genai
from google.genai import types as genai_types

# Removed global client - each bot now has its own client instance
# Global client was removed to support per-session API keys

# Load system prompt from file
SYSTEM_PROMPT_PATH = "system_prompt.txt"


def load_system_prompt() -> str:
    """Load system prompt from external file"""
    try:
        with open(SYSTEM_PROMPT_PATH, 'r', encoding='utf-8') as f:
            return f.read().strip()
    except FileNotFoundError:
        logging.warning(f"System prompt file not found: {SYSTEM_PROMPT_PATH}, using empty prompt")
        return ""
    except Exception as e:
        logging.error(f"Error loading system prompt: {e}")
        return ""


class GeminiModel(Enum):
    # FLASH = "gemini-flash-lite-latest"
    FLASH = "gemini-flash-latest"
    FLASH_THINKING = "gemini-2.5-pro"
    # FLASH_MULTIMODAL = "gemini-flash-latest"
    FLASH_MULTIMODAL = "gemini-2.5-pro"


def get_mime_type(file_path: str) -> str:
    """
    Determine MIME type for a file using mimetypes library with fallback logic
    
    Args:
        file_path: Path to the file
        
    Returns:
        MIME type string
    """
    # Try to guess using mimetypes library
    mime_type, _ = mimetypes.guess_type(file_path)
    
    if mime_type:
        return mime_type
    
    # Fallback: manual extension mapping for common cases
    ext = os.path.splitext(file_path)[1].lower()
    fallback_types = {
        '.jpg': 'image/jpeg',
        '.jpeg': 'image/jpeg',
        '.png': 'image/png',
        '.gif': 'image/gif',
        '.webp': 'image/webp',
        '.mp4': 'video/mp4',
        '.webm': 'video/webm',
        '.ogg': 'audio/ogg',
        '.mp3': 'audio/mpeg',
        '.wav': 'audio/x-wav',
        '.m4a': 'audio/mp4',
    }
    
    return fallback_types.get(ext, 'application/octet-stream')


async def _upload_and_wait_for_file(client: genai.Client, file_path: str) -> Tuple[Optional[genai_types.File], Optional[str]]:
    """
    Upload a file to Gemini and wait for it to become active
    
    Args:
        client: An initialized google.genai.Client instance
        file_path: Path to the file to upload
        
    Returns:
        Tuple of (uploaded file object, error message if any)
    """
    loop = asyncio.get_event_loop()
    
    try:
        # Upload file
        uploaded_file = await loop.run_in_executor(
            None, 
            lambda c=client, p=file_path: c.files.upload(file=p)
        )
        
        # Wait for file to become ACTIVE (max 15 seconds)
        max_attempts = 30
        for attempt in range(max_attempts):
            file_status = await loop.run_in_executor(
                None, 
                lambda c=client, n=uploaded_file.name: c.files.get(name=n)
            )
            
            if getattr(file_status, "state", None) == "ACTIVE":
                logging.info(f"File uploaded and ACTIVE: {uploaded_file.name}")
                return uploaded_file, None
            
            await asyncio.sleep(0.5)
        
        # Timeout
        return None, f"Файл {uploaded_file.name} не стал ACTIVE за {max_attempts * 0.5} секунд"
        
    except Exception as e:
        logging.error(f"Error uploading file {file_path}: {str(e)}")
        return None, f"Ошибка при загрузке файла {file_path}: {str(e)}"


async def _upload_media_files(client: genai.Client, media_paths: List[str], mime_types: Optional[List[str]] = None) -> Tuple[List[genai_types.Part], List[genai_types.File], Optional[str]]:
    """
    Upload multiple media files to Gemini
    
    Args:
        client: An initialized google.genai.Client instance
        media_paths: List of file paths to upload
        mime_types: Optional list of MIME types (if None, will be auto-detected)
        
    Returns:
        Tuple of (list of content parts, list of uploaded files, error message if any)
    """
    parts = []
    uploaded_files = []
    
    for idx, media_path in enumerate(media_paths):
        if not os.path.exists(media_path):
            logging.warning(f"Media file not found: {media_path}")
            continue
        
        # Determine MIME type
        if mime_types and idx < len(mime_types):
            mime_type = mime_types[idx]
        else:
            mime_type = get_mime_type(media_path)
        
        logging.info(f"Uploading file: {media_path} (mime: {mime_type})")
        
        # Upload and wait for activation
        uploaded_file, error = await _upload_and_wait_for_file(client, media_path)
        
        if error:
            # Clean up already uploaded files
            await _cleanup_uploaded_files(client, uploaded_files)
            return [], [], error
        
        uploaded_files.append(uploaded_file)
        parts.append(genai_types.Part.from_uri(file_uri=uploaded_file.uri, mime_type=mime_type))
    
    return parts, uploaded_files, None


async def _cleanup_uploaded_files(client: genai.Client, uploaded_files: List[genai_types.File]):
    """
    Delete uploaded files from Gemini
    
    Args:
        client: An initialized google.genai.Client instance
        uploaded_files: List of file objects to delete
    """
    if not uploaded_files:
        return
    
    logging.info(f"Cleaning up {len(uploaded_files)} uploaded file(s)...")
    loop = asyncio.get_event_loop()
    
    for file in uploaded_files:
        try:
            await loop.run_in_executor(None, lambda c=client, f=file: c.files.delete(f.name))
            logging.info(f"Deleted uploaded file: {file.name}")
        except Exception as e:
            logging.error(f"Error deleting uploaded file {file.name}: {e}")


def _build_generation_config(model: GeminiModel, is_media_request: bool = False) -> Tuple[str, genai_types.GenerateContentConfig]:
    """
    Build generation configuration for Gemini API
    
    Args:
        model: The model to use
        is_media_request: Whether this is a media analysis request
        
    Returns:
        Tuple of (model name, GenerateContentConfig object)
    """
    # Select model
    api_model = GeminiModel.FLASH_MULTIMODAL.value if is_media_request else model.value
    
    # Load system prompt
    system_prompt_text = load_system_prompt()
    
    config_args = {
        "temperature": 1,
        "top_p": 0.95,
        "top_k": 60,
        "max_output_tokens": 8192,
        "response_mime_type": "text/plain",
        "tools": [genai_types.Tool(google_search=genai_types.GoogleSearch())],
    }
    
    # Add system instruction if available
    if system_prompt_text:
        config_args["system_instruction"] = [
            genai_types.Part.from_text(text=system_prompt_text)
        ]
    
    return api_model, genai_types.GenerateContentConfig(**config_args)


async def call_gemini_api(
    client: genai.Client,
    query: str,
    model: GeminiModel = GeminiModel.FLASH,
    media_paths: Optional[List[str]] = None,
    mime_types: Optional[List[str]] = None,
    is_media_request: bool = False,
) -> str:
    """
    Call Gemini API with the given query text and model asynchronously

    Args:
        client: An initialized google.genai.Client instance
        query: The text query to process
        model: The Gemini model to use
        media_paths: Optional list of paths to media files to include
        mime_types: Optional list of MIME types for the media files
        is_media_request: Flag to indicate if this is a media analysis request

    Returns:
        Response text from Gemini
    """
    parts = []
    uploaded_files = []
    
    try:
        # Upload media files if provided
        if media_paths:
            logging.info(f"Processing {len(media_paths)} media file(s)...")
            media_parts, uploaded_files, error = await _upload_media_files(client, media_paths, mime_types)
            
            if error:
                return f"Ошибка: {error}"
            
            parts.extend(media_parts)
        
        # Add text query (after media parts, as recommended)
        if query:
            parts.append(genai_types.Part.from_text(text=query))
        
        if not parts:
            return "Ошибка: Не удалось подготовить контент для запроса (нет текста или медиа)."
        
        # Build content
        contents = [genai_types.Content(role="user", parts=parts)]
        
        # Get generation config
        api_model, gen_config = _build_generation_config(model, is_media_request)
        
        logging.info(f"Sending request to Gemini model {api_model} with {len(parts)} parts.")
        
        # Call API
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None,
            lambda c=client, m=api_model, ct=contents, cfg=gen_config: c.models.generate_content(
                model=m,
                contents=ct,
                config=cfg,
            ),
        )
        
        response_text = result.text
        logging.info("Received response from Gemini.")
        
        # Add thinking hat emoji for thinking model
        if model == GeminiModel.FLASH_THINKING and not is_media_request:
            response_text = "🎩" + response_text
        
        return response_text
        
    except Exception as e:
        logging.error(f"Error calling Gemini API: {str(e)}")
        error_message = f"Ошибка при вызове Gemini API: {str(e)}"
        if media_paths:
            error_message += f"\nФайлы: {media_paths}"
        return error_message
        
    finally:
        # Clean up uploaded files
        await _cleanup_uploaded_files(client, uploaded_files)


async def download_media(client, message, download_dir="data/media"):
    """
    Download media from a Telegram message
    
    Args:
        client: Pyrogram client
        message: Message object with media
        download_dir: Directory to save downloaded media
        
    Returns:
        Path to downloaded file or None
    """
    os.makedirs(download_dir, exist_ok=True)
    
    # Photo
    if message.photo:
        return await client.download_media(
            message.photo, 
            file_name=f"{download_dir}/photo_{message.id}.jpg"
        )
    
    # Video
    if message.video:
        return await client.download_media(
            message.video, 
            file_name=f"{download_dir}/video_{message.id}.mp4"
        )
    
    # Voice
    if message.voice:
        return await client.download_media(
            message.voice, 
            file_name=f"{download_dir}/voice_{message.id}.ogg"
        )
    
    # Audio
    if message.audio:
        ext = ".ogg"  # default
        if hasattr(message.audio, "mime_type") and message.audio.mime_type:
            mime_to_ext = {
                "audio/mpeg": ".mp3",
                "audio/x-wav": ".wav",
                "audio/webm": ".webm",
            }
            ext = mime_to_ext.get(message.audio.mime_type, ".ogg")
        
        return await client.download_media(
            message.audio, 
            file_name=f"{download_dir}/audio_{message.id}{ext}"
        )
    
    # Document
    if message.document:
        mime_type = message.document.mime_type or ""
        
        # Determine extension from MIME type
        ext = ""
        if mime_type.startswith("image/"):
            ext = ".jpg" if mime_type == "image/jpeg" else ".png"
        elif mime_type.startswith("video/"):
            ext = ".mp4"
        elif mime_type in ["audio/ogg", "audio/mpeg", "audio/x-wav", "audio/webm"]:
            mime_to_ext = {
                "audio/ogg": ".ogg",
                "audio/mpeg": ".mp3",
                "audio/x-wav": ".wav",
                "audio/webm": ".webm",
            }
            ext = mime_to_ext.get(mime_type, "")
        
        # Fallback: try to get extension from filename
        if not ext and message.document.file_name and "." in message.document.file_name:
            ext = message.document.file_name[message.document.file_name.rfind("."):]
        
        return await client.download_media(
            message.document, 
            file_name=f"{download_dir}/doc_{message.id}{ext}"
        )
    
    return None
