#!/usr/bin/env python3
"""
Utility script to add new Telegram session for a bot

This script helps you create a new session file by authenticating with Telegram.
After creating the session, don't forget to add the bot configuration to config.json
"""

import asyncio
import os
import sys

from pyrogram import Client


async def main():
    print("=" * 60)
    print("   Утилита для добавления новой сессии Telegram   ")
    print("=" * 60)
    print()
    
    # Get session details from user
    session_name = input("Введите имя сессии (например, my_bot): ").strip()
    if not session_name:
        print("❌ Ошибка: имя сессии не может быть пустым")
        return
    
    api_id_str = input("Введите ваш API ID: ").strip()
    if not api_id_str:
        print("❌ Ошибка: API ID не может быть пустым")
        return
    
    try:
        api_id = int(api_id_str)
    except ValueError:
        print("❌ Ошибка: API ID должен быть числом")
        return
    
    api_hash = input("Введите ваш API Hash: ").strip()
    if not api_hash:
        print("❌ Ошибка: API Hash не может быть пустым")
        return
    
    owner_id_str = input("Введите ваш Telegram User ID (владельца бота): ").strip()
    if not owner_id_str:
        print("❌ Ошибка: User ID не может быть пустым")
        return
    
    try:
        owner_id = int(owner_id_str)
    except ValueError:
        print("❌ Ошибка: User ID должен быть числом")
        return
    
    print()
    print("-" * 60)
    print("Начинаем создание сессии...")
    print("-" * 60)
    print()
    
    # Ensure data directory exists
    os.makedirs("data", exist_ok=True)
    
    # Create client (session will be saved in data/ directory)
    client = Client(f"data/{session_name}", api_id=api_id, api_hash=api_hash)
    
    try:
        # Start the client (will prompt for phone and code)
        await client.start()
        
        # Get user info
        me = await client.get_me()
        
        print()
        print("=" * 60)
        print("✅ Сессия успешно создана!")
        print("=" * 60)
        print(f"Пользователь: {me.first_name} {me.last_name or ''}")
        print(f"Username: @{me.username}")
        print(f"User ID: {me.id}")
        print(f"Файл сессии: data/{session_name}.session")
        print()
        print("-" * 60)
        print("Следующие шаги:")
        print("-" * 60)
        print()
        print("1. Добавьте следующую конфигурацию в ваш config.json:")
        print()
        print("  {")
        print(f'    "session_name": "{session_name}",')
        print(f'    "api_id": {api_id},')
        print(f'    "api_hash": "{api_hash}",')
        print(f'    "bot_owner_id": {owner_id},')
        print(f'    "database_path": "data/{session_name}.db"')
        print("  }")
        print()
        print("2. Перезапустите бота:")
        print("   docker compose up -d --build")
        print()
        print("=" * 60)
        
        # Stop the client
        await client.stop()
        
    except Exception as e:
        print()
        print("=" * 60)
        print(f"❌ Ошибка при создании сессии: {e}")
        print("=" * 60)
        sys.exit(1)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n\nПрервано пользователем")
        sys.exit(0)
