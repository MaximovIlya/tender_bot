# tasks.py
import asyncio
import logging
from datetime import datetime, timezone
from ..models import Tender, TenderStatus
from ..db import SessionLocal
from sqlalchemy import select

logger = logging.getLogger(__name__)

async def activate_pending_tenders():
    """Активирует тендеры, когда наступает их время начала"""
    logger.info("🚀 Сервис активации тендеров запущен")
    
    while True:
        try:
            async with SessionLocal() as session:
                # Получаем текущее время в UTC и локальное время
                # UTC - стандартное время, не зависит от часового пояса
                # Локальное время - время вашей системы/часового пояса
                # ВАЖНО: Время в БД хранится в локальном времени, поэтому используем его для сравнения
                now_utc = datetime.now(timezone.utc)
                now_local = datetime.now()  # Локальное время системы
                
                # Ищем тендеры, которые ожидают активации и время которых наступило
                # Время в БД хранится в локальном времени, поэтому сравниваем с локальным временем
                stmt = select(Tender).where(
                    Tender.status == TenderStatus.active_pending.value,
                    Tender.start_at <= now_local
                )
                result = await session.execute(stmt)
                pending_tenders = result.scalars().all()
                
                logger.info(f"🔍 Проверка активации тендеров")
                logger.info(f"📅 Локальное время: {now_local.strftime('%d.%m.%Y %H:%M:%S')}")
                logger.info(f"🌍 UTC время: {now_utc.strftime('%d.%m.%Y %H:%M:%S')}")
                logger.info(f"📋 Найдено тендеров для активации: {len(pending_tenders)}")

                for tender in pending_tenders:
                    logger.info(f"⏰ Активируем тендер '{tender.title}' (время начала: {tender.start_at})")
                    # Активируем тендер
                    tender.status = TenderStatus.active.value
                    tender.current_price = tender.start_price  # Устанавливаем текущую цену
                    await session.commit()
                    logger.info(f"✅ Тендер '{tender.title}' активирован!")
                    logger.info(f"   📅 Локальное время: {now_local.strftime('%d.%m.%Y %H:%M:%S')}")
                    logger.info(f"   🌍 UTC время: {now_utc.strftime('%d.%m.%Y %H:%M:%S')}")
                    
        except Exception as e:
            logger.error(f"❌ Ошибка в activate_pending_tenders: {e}")
            
        await asyncio.sleep(60)  # проверка каждые 60 секунд
