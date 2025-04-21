import sqlite3
import os
import datetime
import enum
from typing import List, Tuple, Optional

class MessageImportance(enum.Enum):
    GEMINI = "Gemini"
    IMPORTANT = "Important"
    DEFAULT = "None"

class Database:
    def __init__(self, db_path):
        self.db_path = db_path
        self.create_tables()
    
    def create_tables(self):
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            # Whitelist table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS whitelisted_chats (
                    chat_id INTEGER PRIMARY KEY
                )
            ''')
            # Messages table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    chat_id INTEGER,
                    message_id INTEGER,
                    author TEXT,
                    date TEXT,
                    content TEXT,
                    tags TEXT,
                    important TEXT
                )
            ''')
            conn.commit()
    
    # Whitelist methods
    def is_chat_whitelisted(self, chat_id):
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT 1 FROM whitelisted_chats WHERE chat_id = ?', (chat_id,))
            return cursor.fetchone() is not None
    
    def add_chat_to_whitelist(self, chat_id):
        if not self.is_chat_whitelisted(chat_id):
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('INSERT INTO whitelisted_chats (chat_id) VALUES (?)', (chat_id,))
                conn.commit()
                return True
        return False
    
    def remove_chat_from_whitelist(self, chat_id):
        if self.is_chat_whitelisted(chat_id):
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('DELETE FROM whitelisted_chats WHERE chat_id = ?', (chat_id,))
                conn.commit()
                return True
        return False
    
    # Message storage methods
    def store_message(self, chat_id: int, message_id: int, author: str, 
                     date: datetime.datetime, content: str, tags: str, 
                     importance: MessageImportance = MessageImportance.DEFAULT):
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO messages (chat_id, message_id, author, date, content, tags, important)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (chat_id, message_id, author, date.isoformat(), content, tags, importance.value)
            )
            conn.commit()
    
    def get_last_messages(self, chat_id: int, limit: int = 120) -> List[Tuple]:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            
            # Get all important messages
            cursor.execute(
                """
                SELECT message_id, author, date, content, tags, important
                FROM messages
                WHERE chat_id=? AND important='Important'
                ORDER BY id DESC
                """,
                (chat_id,)
            )
            important_messages = cursor.fetchall()
            
            # Get most recent normal messages
            cursor.execute(
                """
                SELECT message_id, author, date, content, tags, important
                FROM messages
                WHERE chat_id=? AND important IN ('None', 'Gemini')
                ORDER BY id DESC
                LIMIT ?
                """,
                (chat_id, limit)
            )
            normal_messages = cursor.fetchall()
            
            # Combine important and normal messages
            return normal_messages + important_messages
