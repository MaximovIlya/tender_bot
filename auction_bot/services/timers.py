import asyncio
from datetime import datetime, timedelta
from typing import Dict, Set
from aiogram import Bot
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import SessionLocal
from ..models import Tender, TenderStatus, Bid, User, TenderParticipant

class AuctionTimer:
    """Сервис для управления таймерами аукционов"""
    
    def __init__(self, bot: Bot):
        self.bot = bot
        self.active_timers: Dict[int, asyncio.Task] = {}
        self.tender_checks: Set[int] = set()
    
    async def start_timer_for_tender(self, tender_id: int, delay_minutes: int = 5):
        """Запуск таймера для тендера"""
        if tender_id in self.active_timers:
            # Отменяем существующий таймер
            self.active_timers[tender_id].cancel()
        
        # Создаем новый таймер
        timer_task = asyncio.create_task(
            self._wait_and_close_tender(tender_id, delay_minutes)
        )
        self.active_timers[tender_id] = timer_task
        
        print(f"Таймер запущен для тендера {tender_id}, время: {delay_minutes} минут")
    
    async def _wait_and_close_tender(self, tender_id: int, delay_minutes: int):
        """Ожидание и закрытие тендера"""
        try:
            await asyncio.sleep(delay_minutes * 60)  # Конвертируем минуты в секунды
            
            # Проверяем, не была ли подана новая заявка
            async with SessionLocal() as session:
                tender = await session.get(Tender, tender_id)
                if not tender or tender.status != TenderStatus.active.value:
                    return
                
                # Проверяем время последней заявки
                if tender.last_bid_at:
                    time_since_last_bid = datetime.now() - tender.last_bid_at
                    if time_since_last_bid < timedelta(minutes=5):
                        # Была подана новая заявка, перезапускаем таймер
                        await self.start_timer_for_tender(tender_id, 5)
                        return
                
                # Закрываем тендер
                await self._close_tender(session, tender)
                
        except asyncio.CancelledError:
            print(f"Таймер для тендера {tender_id} отменен")
        except Exception as e:
            print(f"Ошибка в таймере для тендера {tender_id}: {e}")
        finally:
            # Удаляем таймер из активных
            if tender_id in self.active_timers:
                del self.active_timers[tender_id]
    
    async def _close_tender(self, session: AsyncSession, tender: Tender):
        """Закрытие тендера и определение победителя"""
        try:
            # Закрываем тендер
            tender.status = TenderStatus.closed.value
            await session.commit()
            
            # Определяем победителя
            if tender.bids:
                winner_bid = min(tender.bids, key=lambda x: x.amount)
                winner = await session.get(User, winner_bid.supplier_id)
                
                # Уведомляем победителя
                try:
                    await self.bot.send_message(
                        winner.telegram_id,
                        f"🏆 Поздравляем! Вы выиграли тендер!\n\n"
                        f"📋 {tender.title}\n"
                        f"💰 Ваша цена: {winner_bid.amount} ₽\n"
                        f"📅 Время подачи: {winner_bid.created_at.strftime('%H:%M:%S')}\n\n"
                        f"Организатор свяжется с вами для обсуждения деталей."
                    )
                except Exception as e:
                    print(f"Ошибка отправки уведомления победителю: {e}")
                
                # Уведомляем организатора
                organizer = await session.get(User, tender.organizer_id)
                try:
                    await self.bot.send_message(
                        organizer.telegram_id,
                        f"🔴 Аукцион завершен!\n\n"
                        f"📋 {tender.title}\n"
                        f"🏆 Победитель: {winner.org_name}\n"
                        f"💰 Цена: {winner_bid.amount} ₽\n"
                        f"📅 Время: {winner_bid.created_at.strftime('%H:%M:%S')}\n\n"
                        f"Свяжитесь с победителем для обсуждения деталей."
                    )
                except Exception as e:
                    print(f"Ошибка отправки уведомления организатору: {e}")
                
                # Уведомляем всех участников о завершении
                await self._notify_participants_about_closure(session, tender, winner)
                
                print(f"Тендер {tender.id} закрыт, победитель: {winner.org_name}")
            else:
                # Заявок не было
                organizer = await session.get(User, tender.organizer_id)
                try:
                    await self.bot.send_message(
                        organizer.telegram_id,
                        f"🔴 Аукцион завершен без заявок!\n\n"
                        f"📋 {tender.title}\n"
                        f"📊 Статус: Заявок не было подано\n\n"
                        f"Тендер можно перезапустить или отменить."
                    )
                except Exception as e:
                    print(f"Ошибка отправки уведомления организатору: {e}")
                
                print(f"Тендер {tender.id} закрыт без заявок")
                
        except Exception as e:
            print(f"Ошибка при закрытии тендера {tender.id}: {e}")
    
    async def _notify_participants_about_closure(self, session: AsyncSession, tender: Tender, winner: User):
        """Уведомление участников о завершении аукциона"""
        try:
            # Получаем всех участников
            stmt = select(TenderParticipant).where(TenderParticipant.tender_id == tender.id)
            result = await session.execute(stmt)
            participants = result.scalars().all()
            
            closure_text = (
                f"🔴 Аукцион завершен!\n\n"
                f"📋 {tender.title}\n"
                f"🏆 Победитель: {winner.org_name}\n"
                f"💰 Цена: {tender.current_price} ₽\n"
                f"📅 Время завершения: {datetime.now().strftime('%H:%M:%S')}\n\n"
                f"Спасибо за участие!"
            )
            
            # Отправляем уведомления всем участникам (кроме победителя)
            for participant in participants:
                if participant.supplier_id != winner.id:
                    try:
                        await self.bot.send_message(
                            participant.supplier.telegram_id,
                            closure_text
                        )
                    except Exception as e:
                        print(f"Ошибка отправки уведомления участнику: {e}")
                        
        except Exception as e:
            print(f"Ошибка при уведомлении участников: {e}")
    
    async def reset_timer_for_tender(self, tender_id: int):
        """Сброс таймера для тендера (при новой заявке)"""
        if tender_id in self.active_timers:
            # Отменяем текущий таймер
            self.active_timers[tender_id].cancel()
        
        # Запускаем новый таймер
        await self.start_timer_for_tender(tender_id, 5)
    
    async def cancel_timer_for_tender(self, tender_id: int):
        """Отмена таймера для тендера"""
        if tender_id in self.active_timers:
            self.active_timers[tender_id].cancel()
            del self.active_timers[tender_id]
            print(f"Таймер для тендера {tender_id} отменен")
    
    async def check_all_active_tenders(self):
        """Проверка всех активных тендеров на истечение времени"""
        try:
            async with SessionLocal() as session:
                # Получаем активные тендеры
                stmt = select(Tender).where(Tender.status == TenderStatus.active.value)
                result = await session.execute(stmt)
                active_tenders = result.scalars().all()
                
                for tender in active_tenders:
                    if tender.last_bid_at:
                        time_since_last_bid = datetime.now() - tender.last_bid_at
                        if time_since_last_bid > timedelta(minutes=5):
                            # Время истекло, закрываем тендер
                            await self._close_tender(session, tender)
                
        except Exception as e:
            print(f"Ошибка при проверке активных тендеров: {e}")
    
    async def start_periodic_check(self, interval_minutes: int = 1):
        """Запуск периодической проверки тендеров"""
        while True:
            try:
                await self.check_all_active_tenders()
                await asyncio.sleep(interval_minutes * 60)
            except Exception as e:
                print(f"Ошибка в периодической проверке: {e}")
                await asyncio.sleep(60)  # Ждем минуту при ошибке
    
    def get_active_timers_count(self) -> int:
        """Получить количество активных таймеров"""
        return len(self.active_timers)
    
    async def cleanup(self):
        """Очистка всех таймеров"""
        for tender_id in list(self.active_timers.keys()):
            await self.cancel_timer_for_tender(tender_id)
        print("Все таймеры очищены")
