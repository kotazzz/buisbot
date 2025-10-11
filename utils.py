import datetime
from typing import List, Tuple
from pyrogram.types import Message

def format_duration(seconds: int) -> str:
    """Format duration in seconds to 'minutes:seconds' format"""
    minutes = seconds // 60
    sec = seconds % 60
    return f"{minutes}:{sec:02d}"

def generate_tags(msg: Message) -> str:
    """Generate descriptive tags for a message based on its content"""
    tags = []

    if msg.photo:
        tags.append("содержит фото")
    if msg.voice:
        duration = msg.voice.duration
        tags.append(f"содержит голосовое длительностью {format_duration(duration)}")
    if msg.document:
        doc = msg.document
        tags.append(f'содержит файл "{doc.file_name}" ({doc.file_size} байт)')
    if msg.audio:
        audio = msg.audio
        title = audio.title if audio.title else "неизвестно"
        performer = audio.performer if audio.performer else "неизвестен"
        tags.append(
            f'содержит музыку "{title}" {performer} длительностью {format_duration(audio.duration)}'
        )
    if msg.video:
        video = msg.video
        tags.append(f"содержит видео длительностью {format_duration(video.duration)}")
    if msg.video_note:
        tags.append("содержит видео-сообщение")
    if msg.contact:
        contact = msg.contact
        tags.append(f'содержит контакт "{contact.first_name}"')
    if msg.location:
        tags.append("содержит локацию")
    if msg.venue:
        tags.append("содержит мероприятие")
    if msg.sticker:
        tags.append("содержит стикер")
    if msg.animation:
        tags.append("содержит анимацию")
    if msg.forward_from:
        tags.append(f'переслано из "{msg.forward_from.full_name}"')
    elif msg.forward_from_chat:
        title = msg.forward_from_chat.title if msg.forward_from_chat.title else "неизвестно"
        tags.append(f'переслано из "{title}"')
    if msg.reply_to_message:
        tags.append(f"в ответ на сообщение {msg.reply_to_message.id}")
    if msg.sender_chat:
        tags.append(f'отправлено от имени канала "{msg.sender_chat.title}"')
    if msg.via_bot:
        tags.append(f'via bot "{msg.via_bot.first_name}"')

    return ", ".join(tags)

def format_chat_history(messages: List[Tuple]) -> str:
    """Format chat history for display and AI processing"""
    
    lines = []
    # Reverse to show messages from oldest to newest
    for m in reversed(messages):
        msg_id, author, date_str, content, tags, important = m
        i = "[СООБЩЕНИЕ ОТМЕЧЕНО ВАЖНЫМ] " if important == "Important" else ""
        
        if important == "Gemini":
            author = "Gemini"
            
        date_obj = datetime.datetime.fromisoformat(date_str)
        date_formatted = date_obj.strftime('%Y-%m-%d %H:%M:%S')
        
        if tags:
            line = f"{i}{msg_id} {date_formatted} {author} ({tags}): {content}"
        else:
            line = f"{i}{msg_id} {date_formatted} {author}: {content}"
            
        lines.append(line)
        
    return "\n".join(lines)