#!/usr/bin/env python3
"""
Скрипт для обновления базы данных с новой таблицей TenderAccess
"""

import asyncio
import sys
import os

# Добавляем путь к модулю auction_bot
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from auction_bot.db import init_db

async def main():
    """Основная функция для обновления базы данных"""
    print("🔄 Обновление базы данных...")
    
    try:
        await init_db()
        print("✅ База данных успешно обновлена!")
        print("📋 Добавлена таблица tender_access для контроля доступа к тендерам")
    except Exception as e:
        print(f"❌ Ошибка при обновлении базы данных: {e}")
        return 1
    
    return 0

if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
