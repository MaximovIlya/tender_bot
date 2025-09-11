import asyncio
import logging
from datetime import datetime, timedelta
from typing import Dict
from zoneinfo import ZoneInfo
from aiogram import Bot
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ..db import SessionLocal
from ..models import Tender, TenderStatus, Bid, User, TenderParticipant

logger = logging.getLogger(__name__)
local_tz = ZoneInfo("Europe/Moscow")

class AuctionTimer:
    """Сервис для управления таймерами аукционов"""

    def __init__(self, bot: Bot):
        self.bot = bot
        self.active_timers: Dict[int, asyncio.Task] = {}

    async def start_timer_for_tender(self, tender_id: int, delay_minutes: int = 2):
        """Запуск таймера для тендера"""
        if tender_id in self.active_timers:
            self.active_timers[tender_id].cancel()

        end_time = datetime.now() + timedelta(minutes=delay_minutes)
        task = asyncio.create_task(self._wait_and_close_tender(tender_id, delay_minutes))
        self.active_timers[tender_id] = task

        logger.info(f"⏱ Таймер запущен для тендера {tender_id}, "
                    f"длительность {delay_minutes} мин, завершение: {end_time.strftime('%d.%m.%Y %H:%M:%S')}")

    async def _wait_and_close_tender(self, tender_id: int, delay_minutes: int):
        """Ожидание и закрытие тендера"""
        try:
            await asyncio.sleep(delay_minutes * 60)

            async with SessionLocal() as session:
                tender = await session.get(Tender, tender_id, options=[selectinload(Tender.bids)])
                if not tender or tender.status != TenderStatus.active.value:
                    return

                # Перезапуск таймера, если новая ставка недавно
                if tender.last_bid_at:
                    elapsed = datetime.now() - tender.last_bid_at
                    if elapsed < timedelta(minutes=2):
                        logger.info(f"🔄 Новая ставка в тендере {tender_id}, таймер перезапускается")
                        await self.start_timer_for_tender(tender_id, 2)
                        return

            # Закрываем тендер
            await self._close_tender(tender_id)

        except asyncio.CancelledError:
            logger.info(f"⏹ Таймер для тендера {tender_id} отменен")
        except Exception as e:
            logger.error(f"⚠️ Ошибка в таймере для тендера {tender_id}: {e}")
        finally:
            self.active_timers.pop(tender_id, None)

    async def _close_tender(self, tender_id: int):
        """Закрытие тендера и уведомления"""
        try:
            async with SessionLocal() as session:
                tender = await session.get(Tender, tender_id, options=[selectinload(Tender.bids)])
                if not tender or tender.status != TenderStatus.active.value:
                    return

                tender.status = TenderStatus.closed.value
                await session.commit()

                winner = None
                winner_bid = None

                if tender.bids:
                    # Победитель по минимальной цене
                    winner_bid = min(tender.bids, key=lambda x: x.amount)
                    winner = await session.get(User, winner_bid.supplier_id)

                    # Уведомляем победителя
                    if winner:
                        try:
                            await self.bot.send_message(
                                winner.telegram_id,
                                f"🏆 Поздравляем! Вы выиграли тендер!\n\n"
                                f"📋 {tender.title}\n"
                                f"💰 Ваша цена: {winner_bid.amount} ₽\n"
                                f"📅 Время подачи: {winner_bid.created_at.astimezone(local_tz).strftime('%H:%M:%S')}\n\n"
                                f"Организатор свяжется с вами для обсуждения деталей."
                            )
                        except Exception as e:
                            logger.error(f"Ошибка отправки победителю: {e}")

                    # Уведомляем участников
                    await self._notify_participants_about_closure(tender_id, winner.id if winner else None)

                    # Уведомляем организатора
                    organizer = await session.get(User, tender.organizer_id)
                    if organizer:
                        bids_report = "📊 ХОД ТОРГОВ:\n\n"
                        for i, bid in enumerate(tender.bids, start=1):
                            supplier = await session.get(User, bid.supplier_id)
                            org_name = supplier.org_name if supplier else "Неизвестная компания"
                            bids_report += (
                                f"{i}. 🏢 {org_name}\n"
                                f"   💰 Цена: {bid.amount} ₽\n"
                                f"   ⏰ Время: {bid.created_at.astimezone(local_tz).strftime('%H:%M:%S')}\n\n"
                            )
                        try:
                            await self.bot.send_message(
                                organizer.telegram_id,
                                f"🔴 Аукцион завершен!\n\n"
                                f"📋 {tender.title}\n"
                                f"🏆 Победитель: {winner.org_name if winner else 'Неизвестно'}\n"
                                f"💰 Цена: {winner_bid.amount} ₽\n\n"
                                f"{bids_report}"
                            )
                        except Exception as e:
                            logger.error(f"Ошибка отправки организатору: {e}")

                else:
                    # Нет ставок
                    async with SessionLocal() as session:
                        organizer = await session.get(User, tender.organizer_id)
                        if organizer:
                            try:
                                await self.bot.send_message(
                                    organizer.telegram_id,
                                    f"🔴 Аукцион завершен без заявок!\n\n"
                                    f"📋 {tender.title}"
                                )
                            except Exception as e:
                                logger.error(f"Ошибка отправки организатору: {e}")

                logger.info(f"✅ Тендер {tender.id} закрыт")
        except Exception as e:
            logger.error(f"Ошибка при закрытии тендера {tender_id}: {e}")

    async def _notify_participants_about_closure(self, tender_id: int, winner_id: int = None):
        """Уведомление участников о завершении аукциона"""
        try:
            async with SessionLocal() as session:
                stmt = select(TenderParticipant).where(TenderParticipant.tender_id == tender_id)
                result = await session.execute(stmt)
                participants = result.scalars().all()

                tender = await session.get(Tender, tender_id)
                winner = await session.get(User, winner_id) if winner_id else None

                closure_text = (
                    f"🔴 Аукцион завершен!\n\n"
                    f"📋 {tender.title}\n"
                    f"🏆 Победитель: {winner.org_name if winner else '—'}\n"
                    f"💰 Цена: {tender.current_price} ₽\n"
                    f"📅 Время завершения: {datetime.now().strftime('%H:%M:%S')}\n\n"
                    f"Спасибо за участие!"
                )

                for participant in participants:
                    if participant.supplier_id != (winner.id if winner else None):
                        user = await session.get(User, participant.supplier_id)
                        if user:
                            try:
                                await self.bot.send_message(user.telegram_id, closure_text)
                            except Exception as e:
                                logger.error(f"Ошибка отправки участнику: {e}")
        except Exception as e:
            logger.error(f"Ошибка уведомления участников: {e}")

    async def reset_timer_for_tender(self, tender_id: int):
        """Сброс таймера при новой заявке"""
        if tender_id in self.active_timers:
            self.active_timers[tender_id].cancel()
        logger.info(f"🔄 Сброс таймера для тендера {tender_id}")
        await self.start_timer_for_tender(tender_id, 2)

    async def cancel_timer_for_tender(self, tender_id: int):
        """Отмена таймера"""
        if tender_id in self.active_timers:
            self.active_timers[tender_id].cancel()
            self.active_timers.pop(tender_id, None)
            logger.info(f"⏹ Таймер для тендера {tender_id} отменен")

    async def check_all_active_tenders(self):
        """Фоновая проверка активных тендеров"""
        try:
            async with SessionLocal() as session:
                stmt = select(Tender).where(Tender.status == TenderStatus.active.value)
                result = await session.execute(stmt)
                active_tenders = result.scalars().all()

                for tender in active_tenders:
                    if tender.last_bid_at:
                        elapsed = datetime.now() - tender.last_bid_at
                        if elapsed > timedelta(minutes=2):
                            await self._close_tender(tender.id)
        except Exception as e:
            logger.error(f"Ошибка при проверке тендеров: {e}")

    async def start_periodic_check(self, interval_minutes: int = 1):
        """Фоновая проверка каждые N минут"""
        while True:
            try:
                await self.check_all_active_tenders()
                await asyncio.sleep(interval_minutes * 60)
            except Exception as e:
                logger.error(f"Ошибка в периодической проверке: {e}")
                await asyncio.sleep(60)

    def get_active_timers_count(self) -> int:
        return len(self.active_timers)

    async def cleanup(self):
        """Очистка всех таймеров"""
        for tender_id in list(self.active_timers.keys()):
            await self.cancel_timer_for_tender(tender_id)
        logger.info("Все таймеры очищены")
