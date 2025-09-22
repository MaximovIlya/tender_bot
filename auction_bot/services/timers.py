import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Dict
from zoneinfo import ZoneInfo
from aiogram import Bot
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from auction_bot.keyboards import menu_supplier_registered

from ..db import SessionLocal
from ..models import Tender, TenderStatus, Bid, User, TenderParticipant, TenderAccess

logger = logging.getLogger(__name__)
local_tz = ZoneInfo("Europe/Moscow")


class AuctionTimer:
    """Сервис для управления таймерами аукционов"""

    def __init__(self, bot: Bot):
        self.bot = bot
        self.active_timers: Dict[int, asyncio.Task] = {}
        # Уведомления о старте: {'before': task, 'start': task} для каждого тендера
        self.start_notifications: Dict[int, Dict[str, asyncio.Task]] = {}

    # 🔹 Универсальная функция для форматирования цен
    @staticmethod
    def format_price(value: float | int) -> str:
        return f"{value:,.0f}".replace(",", " ")

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

                if tender.last_bid_at:
                    elapsed = datetime.now() - tender.last_bid_at
                    if elapsed < timedelta(minutes=2):
                        logger.info(f"🔄 Новая ставка в тендере {tender_id}, таймер перезапускается")
                        await self.start_timer_for_tender(tender_id, 2)
                        return

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

                    created_at_local = winner_bid.created_at.replace(tzinfo=timezone.utc).astimezone(local_tz)
                    price_str = self.format_price(winner_bid.amount)

                    # Победитель
                    if winner:
                        try:
                            await self.bot.send_message(
                                winner.telegram_id,
                                f"🏆 Поздравляем! Вы выиграли тендер!\n\n"
                                f"📋 {tender.title}\n"
                                f"💰 Ваша цена: {price_str} ₽\n"
                                f"📅 Время подачи: {created_at_local.strftime('%H:%M:%S')}\n\n"
                                f"Организатор свяжется с вами для обсуждения деталей.",
                                reply_markup=menu_supplier_registered
                            )
                        except Exception as e:
                            logger.error(f"Ошибка отправки победителю: {e}")

                    # Участники
                    await self._notify_participants_about_closure(tender_id, winner.id if winner else None)

                    # Организатор
                    organizer = await session.get(User, tender.organizer_id)
                    if organizer:
                        # Формируем ход торгов (как у тебя было)
                        bids_report = "📊 ХОД ТОРГОВ:\n\n"
                        for i, bid in enumerate(tender.bids, start=1):
                            supplier = await session.get(User, bid.supplier_id)
                            org_name = supplier.org_name if supplier else "Неизвестная компания"
                            bids_report += (
                                f"{i}. 🏢 {org_name}\n"
                                f"   💰 Цена: {self.format_price(bid.amount)} ₽\n"
                                f"   ⏰ Время: {bid.created_at.astimezone(local_tz).strftime('%H:%M:%S')}\n\n"
                            )

                        # Формируем рейтинг участников по их самой низкой ставке
                        # Группируем ставки по участникам и находим минимальную для каждого
                        participant_best_bids = {}
                        for bid in tender.bids:
                            supplier_id = bid.supplier_id
                            if supplier_id not in participant_best_bids or bid.amount < participant_best_bids[supplier_id].amount:
                                participant_best_bids[supplier_id] = bid
                        
                        # Сортируем по лучшей ставке каждого участника
                        sorted_participants = sorted(participant_best_bids.values(), key=lambda x: x.amount)
                        rating_report = "🏅 Итоговый рейтинг участников:\n\n"
                        for i, bid in enumerate(sorted_participants, start=1):
                            supplier = await session.get(User, bid.supplier_id)
                            org_name = supplier.org_name if supplier else "Неизвестная компания"
                            bid_price_str = self.format_price(bid.amount)
                            rating_report += f"{i}. 🏢 {org_name} — {bid_price_str} ₽\n"

                        # Победитель
                        winner_name = winner.org_name if winner else "Неизвестно"

                        try:
                            await self.bot.send_message(
                                organizer.telegram_id,
                                f"🔴 Аукцион завершен!\n\n"
                                f"📋 {tender.title}\n"
                                f"🏆 Победитель: {winner_name}\n"
                                f"💰 Цена: {price_str} ₽\n\n"
                                f"{rating_report}\n"
                                f"{bids_report}"
                            )
                        except Exception as e:
                            logger.error(f"Ошибка отправки организатору: {e}")


                else:
                    # Нет ставок
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

                # Определяем номер победителя
                winner_number = None
                if winner_id:
                    for i, participant in enumerate(participants):
                        if participant.supplier_id == winner_id:
                            winner_number = i + 1
                            break

                closure_text = (
                    f"🔴 Аукцион завершен!\n\n"
                    f"📋 {tender.title}\n"
                    f"🏆 Победитель: Участник {winner_number if winner_number else '—'}\n"
                    f"💰 Цена: {self.format_price(tender.current_price)} ₽\n"
                    f"📅 Время завершения: {datetime.now().strftime('%H:%M:%S')}\n\n"
                    f"Спасибо за участие!"
                )

                # Отправляем всем, кроме победителя
                for participant in participants:
                    if participant.supplier_id != winner_id:
                        user = await session.get(User, participant.supplier_id)
                        if user:
                            try:
                                await self.bot.send_message(user.telegram_id, closure_text)
                            except Exception as e:
                                logger.error(f"Ошибка отправки участнику: {e}")
        except Exception as e:
            logger.error(f"Ошибка уведомления участников: {e}")


    async def schedule_start_notifications(self, tender_id: int):
        async with SessionLocal() as session:
            tender = await session.get(Tender, tender_id)
            if not tender:
                logger.warning(f"Tender {tender_id} not found for notifications")
                return

            # Приводим время начала к локальной зоне (Europe/Moscow) и к UTC для расчета задержек
            start_at_naive = tender.start_at
            if start_at_naive is None:
                logger.warning(f"Tender {tender_id} has no start_at, skip notifications")
                return

            if start_at_naive.tzinfo is None:
                start_at_local = start_at_naive
            else:
                start_at_local = start_at_naive.astimezone(local_tz)

            start_at_utc = start_at_local.replace(tzinfo=local_tz).astimezone(timezone.utc)
            now_utc = datetime.now(timezone.utc)

            notify_before = (start_at_utc - timedelta(minutes=10)) - now_utc
            notify_start = start_at_utc - now_utc

            if notify_before.total_seconds() > 0:
                # отменяем ранее запланированную "за 10 минут"
                if tender_id in self.start_notifications and 'before' in self.start_notifications[tender_id]:
                    self.start_notifications[tender_id]['before'].cancel()
                task_before = asyncio.create_task(self._notify_participants_at_time(
                    tender_id,
                    delay=notify_before.total_seconds(),
                    message_template=(
                        f"⏰ Тендер <b>{tender.title}</b> начнется через 10 минут!\n"
                        f"📅 Время начала: {start_at_local.strftime('%d.%m.%Y %H:%M')}"
                    )
                ))
                self.start_notifications.setdefault(tender_id, {})['before'] = task_before
                logger.info(f"Task created: 10-min notification for tender {tender_id}")
            else:
                logger.warning(f"Skipped 10-min notification for tender {tender_id}, time already passed")

            if notify_start.total_seconds() > 0:
                # отменяем ранее запланированную "начался"
                if tender_id in self.start_notifications and 'start' in self.start_notifications[tender_id]:
                    self.start_notifications[tender_id]['start'].cancel()
                task_start = asyncio.create_task(self._notify_participants_at_time(
                    tender_id,
                    delay=notify_start.total_seconds(),
                    message_template=(
                        f"🟢 Тендер <b>{tender.title}</b> начался!\n"
                        f"📅 Время начала: {start_at_local.strftime('%d.%m.%Y %H:%M')}"
                    )
                ))
                self.start_notifications.setdefault(tender_id, {})['start'] = task_start
                logger.info(f"Task created: start notification for tender {tender_id}")
            else:
                logger.warning(f"Skipped start notification for tender {tender_id}, time already passed")

    async def _notify_participants_at_time(self, tender_id: int, delay: float, message_template: str):
        logger.info(f"Tender {tender_id} → waiting {delay:.0f} sec before notification")
        await asyncio.sleep(delay)

        async with SessionLocal() as session:
            # Получаем только участников тендера
            stmt = select(TenderParticipant).where(TenderParticipant.tender_id == tender_id)
            result = await session.execute(stmt)
            participants = result.scalars().all()

            for supplier_id in {p.supplier_id for p in participants}:
                user = await session.get(User, supplier_id)
                if user:
                    try:
                        await self.bot.send_message(user.telegram_id, message_template)
                        logger.info(f"Notification sent to user {user.id}")
                    except Exception as e:
                        logger.error(f"Failed to send notification to user {user.id}: {e}")

    async def cancel_start_notifications(self, tender_id: int):
        """Отмена уведомлений (10 мин и старт) для тендера"""
        if tender_id in self.start_notifications:
            for key, task in self.start_notifications[tender_id].items():
                if task and not task.done():
                    task.cancel()
                    try:
                        await task
                    except asyncio.CancelledError:
                        pass
                    logger.info(f"⏹ Уведомление '{key}' для тендера {tender_id} отменено")
            self.start_notifications.pop(tender_id, None)

    async def cleanup(self):
        """Очистка всех таймеров и уведомлений"""
        # таймеры аукционов
        for tender_id in list(self.active_timers.keys()):
            await self.cancel_timer_for_tender(tender_id)
        # уведомления о старте
        for tender_id in list(self.start_notifications.keys()):
            await self.cancel_start_notifications(tender_id)
        logger.info("Все таймеры и уведомления очищены")

    async def reset_timer_for_tender(self, tender_id: int):
        if tender_id in self.active_timers:
            self.active_timers[tender_id].cancel()
        logger.info(f"🔄 Сброс таймера для тендера {tender_id}")
        await self.start_timer_for_tender(tender_id, 2)

    async def cancel_timer_for_tender(self, tender_id: int):
        if tender_id in self.active_timers:
            self.active_timers[tender_id].cancel()
            self.active_timers.pop(tender_id, None)
            logger.info(f"⏹ Таймер для тендера {tender_id} отменен")

    async def check_all_active_tenders(self):
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
        for tender_id in list(self.active_timers.keys()):
            await self.cancel_timer_for_tender(tender_id)
        logger.info("Все таймеры очищены")
