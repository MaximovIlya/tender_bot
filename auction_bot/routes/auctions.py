import asyncio
from datetime import datetime, timedelta
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import SessionLocal
from ..models import User, Tender, TenderStatus, Bid, TenderParticipant
from ..services.timers import AuctionTimer
from ..services.reports import ReportService

router = Router()

@router.message(Command("check_auctions"))
async def check_auctions(message: Message):
    """Проверка активных аукционов"""
    async with SessionLocal() as session:
        # Получаем активные тендеры
        stmt = select(Tender).where(Tender.status == TenderStatus.active.value)
        result = await session.execute(stmt)
        active_tenders = result.scalars().all()
        
        if not active_tenders:
            await message.answer("Активных аукционов нет.")
            return
        
        response = "🟢 Активные аукционы:\n\n"
        for tender in active_tenders:
            # Проверяем, не истекло ли время
            time_since_last_bid = None
            if tender.last_bid_at:
                time_since_last_bid = datetime.now() - tender.last_bid_at
            
            status = "⏰ Ожидание заявок"
            if time_since_last_bid and time_since_last_bid > timedelta(minutes=5):
                status = "🔴 Время истекло"
            elif tender.last_bid_at:
                status = f"🟡 Активен ({5 - time_since_last_bid.seconds // 60} мин)"
            
            response += (
                f"📋 <b>{tender.title}</b>\n"
                f"💰 Текущая цена: {tender.current_price} ₽\n"
                f"📅 Начало: {tender.start_at.strftime('%d.%m.%Y %H:%M')}\n"
                f"🏆 Участников: {len(tender.participants)}\n"
                f"📈 Заявок: {len(tender.bids)}\n"
                f"📊 Статус: {status}\n\n"
            )
        
        await message.answer(response)

@router.message(Command("close_expired_auctions"))
async def close_expired_auctions(message: Message):
    """Закрытие истекших аукционов"""
    user_id = message.from_user.id
    
    async with SessionLocal() as session:
        # Проверяем права
        user = await session.get(User, user_id)
        if not user or user.role not in ["admin", "organizer"]:
            await message.answer("У вас нет прав для закрытия аукционов.")
            return
        
        # Находим истекшие аукционы
        expired_tenders = []
        stmt = select(Tender).where(Tender.status == TenderStatus.active.value)
        result = await session.execute(stmt)
        active_tenders = result.scalars().all()
        
        for tender in active_tenders:
            if tender.last_bid_at and datetime.now() - tender.last_bid_at > timedelta(minutes=5):
                expired_tenders.append(tender)
        
        if not expired_tenders:
            await message.answer("Истекших аукционов нет.")
            return
        
        closed_count = 0
        for tender in expired_tenders:
            # Закрываем тендер
            tender.status = TenderStatus.closed.value
            
            # Определяем победителя
            if tender.bids:
                winner_bid = min(tender.bids, key=lambda x: x.amount)
                winner = await session.get(User, winner_bid.supplier_id)
                
                # Уведомляем победителя
                try:
                    await message.bot.send_message(
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
                    await message.bot.send_message(
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
            
            closed_count += 1
        
        await session.commit()
        
        await message.answer(
            f"✅ Закрыто {closed_count} истекших аукционов.\n\n"
            f"Победители и организаторы уведомлены."
        )

@router.message(Command("auction_report"))
async def generate_auction_report(message: Message):
    """Генерация отчета по аукциону"""
    user_id = message.from_user.id
    
    async with SessionLocal() as session:
        user = await session.get(User, user_id)
        if not user or user.role not in ["admin", "organizer"]:
            await message.answer("У вас нет прав для генерации отчетов.")
            return
        
        # Получаем завершенные тендеры
        stmt = select(Tender).where(Tender.status == TenderStatus.closed.value)
        result = await session.execute(stmt)
        closed_tenders = result.scalars().all()
        
        if not closed_tenders:
            await message.answer("Завершенных тендеров для отчета нет.")
            return
        
        # Создаем клавиатуру для выбора тендера
        keyboard = InlineKeyboardMarkup(inline_keyboard=[])
        for tender in closed_tenders:
            keyboard.inline_keyboard.append([
                InlineKeyboardButton(
                    text=f"{tender.title} - {tender.current_price} ₽",
                    callback_data=f"report_tender_{tender.id}"
                )
            ])
        
        await message.answer(
            "Выберите тендер для генерации отчета:",
            reply_markup=keyboard
        )

@router.callback_query(lambda c: c.data.startswith("report_tender_"))
async def generate_tender_report(callback: CallbackQuery):
    """Генерация отчета по конкретному тендеру"""
    tender_id = int(callback.data.split("_")[2])
    
    async with SessionLocal() as session:
        tender = await session.get(Tender, tender_id)
        if not tender:
            await callback.answer("Тендер не найден.")
            return
        
        # Получаем все заявки в хронологическом порядке
        stmt = select(Bid).where(Bid.tender_id == tender_id).order_by(Bid.created_at)
        result = await session.execute(stmt)
        bids = result.scalars().all()
        
        # Получаем участников
        stmt = select(TenderParticipant).where(TenderParticipant.tender_id == tender_id)
        result = await session.execute(stmt)
        participants = result.scalars().all()
        
        # Создаем отчет
        report_text = f"📊 ОТЧЕТ ПО АУКЦИОНУ\n\n"
        report_text += f"📋 Название: {tender.title}\n"
        report_text += f"📝 Описание: {tender.description}\n"
        report_text += f"💰 Стартовая цена: {tender.start_price} ₽\n"
        report_text += f"📅 Дата начала: {tender.start_at.strftime('%d.%m.%Y %H:%M')}\n"
        report_text += f"🏆 Количество участников: {len(participants)}\n"
        report_text += f"📈 Количество заявок: {len(bids)}\n\n"
        
        if bids:
            report_text += "📈 ХОД ТОРГОВ:\n\n"
            
            # Группируем заявки по участникам для анонимности
            participant_map = {}
            for i, participant in enumerate(participants):
                participant_map[participant.supplier_id] = f"Участник {i+1}"
            
            for i, bid in enumerate(bids):
                participant_name = participant_map.get(bid.supplier_id, "Неизвестно")
                report_text += (
                    f"{i+1}. {participant_name}\n"
                    f"   💰 Цена: {bid.amount} ₽\n"
                    f"   📅 Время: {bid.created_at.strftime('%H:%M:%S')}\n\n"
                )
            
            # Победитель
            winner_bid = min(bids, key=lambda x: x.amount)
            winner = await session.get(User, winner_bid.supplier_id)
            report_text += (
                f"🏆 ПОБЕДИТЕЛЬ:\n"
                f"👤 Организация: {winner.org_name}\n"
                f"💰 Цена: {winner_bid.amount} ₽\n"
                f"📅 Время подачи: {winner_bid.created_at.strftime('%H:%M:%S')}\n"
                f"📉 Экономия: {tender.start_price - winner_bid.amount} ₽"
            )
        else:
            report_text += "📊 Заявок не было подано."
        
        await callback.message.edit_text(report_text)

@router.message(Command("auto_close_check"))
async def auto_close_check(message: Message):
    """Автоматическая проверка и закрытие истекших аукционов"""
    user_id = message.from_user.id
    
    async with SessionLocal() as session:
        user = await session.get(User, user_id)
        if not user or user.role not in ["admin", "organizer"]:
            await message.answer("У вас нет прав для автоматического закрытия.")
            return
        
        # Запускаем автоматическую проверку
        await close_expired_auctions(message)

def register_handlers(dp):
    """Регистрация хендлеров"""
    dp.include_router(router)
