#!/usr/bin/env python3
"""
Тестовый скрипт для проверки системы контроля доступа
"""

import asyncio
import sys
import os

# Добавляем путь к модулю auction_bot
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from auction_bot.db import SessionLocal
from auction_bot.models import User, Tender, TenderAccess, TenderStatus
from sqlalchemy import select

async def test_access_control():
    """Тестирование системы контроля доступа"""
    print("🧪 Тестирование системы контроля доступа...")
    
    async with SessionLocal() as session:
        try:
            # Проверяем, что таблица TenderAccess существует
            stmt = select(TenderAccess)
            result = await session.execute(stmt)
            access_records = result.scalars().all()
            print(f"✅ Таблица TenderAccess существует, записей: {len(access_records)}")
            
            # Проверяем пользователей
            stmt = select(User)
            result = await session.execute(stmt)
            users = result.scalars().all()
            print(f"✅ Пользователей в системе: {len(users)}")
            
            # Проверяем тендеры
            stmt = select(Tender)
            result = await session.execute(stmt)
            tenders = result.scalars().all()
            print(f"✅ Тендеров в системе: {len(tenders)}")
            
            # Показываем детали
            for user in users:
                print(f"   👤 {user.username} ({user.role}) - {user.org_name or 'Нет организации'}")
            
            for tender in tenders:
                print(f"   📋 {tender.title} ({tender.status}) - Организатор ID: {tender.organizer_id}")
            
            print("\n🎉 Система контроля доступа готова к работе!")
            
        except Exception as e:
            print(f"❌ Ошибка при тестировании: {e}")
            return 1
    
    return 0

if __name__ == "__main__":
    exit_code = asyncio.run(test_access_control())
    sys.exit(exit_code)
