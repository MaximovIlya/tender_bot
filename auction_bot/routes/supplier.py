import asyncio
from datetime import datetime, timedelta
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, FSInputFile, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.filters import Command
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import SessionLocal
from ..models import User, Tender, TenderStatus, TenderParticipant, Bid
from ..keyboards import menu_supplier
from ..services.timers import AuctionTimer

router = Router()

# Состояния для участия в аукционе
class AuctionParticipation(StatesGroup):
    waiting_for_bid = State()

@router.message(lambda message: message.text == "Активные тендеры")
async def show_active_tenders(message: Message):
    """Показать активные тендеры"""
    user_id = message.from_user.id
    
    async with SessionLocal() as session:
        stmt = select(User).where(User.telegram_id == user_id)
        result = await session.execute(stmt)
        user = result.scalar_one_or_none()

        if not user or not user.org_name:
            await message.answer("Для участия в тендерах необходимо зарегистрироваться.")
            return
        
        # Получаем активные тендеры
        stmt = select(Tender).where(
            and_(
                Tender.status == TenderStatus.active.value,
                Tender.start_at <= datetime.now()
            )
        ).order_by(Tender.start_at.desc())
        
        result = await session.execute(stmt)
        active_tenders = result.scalars().all()
        
        if not active_tenders:
            await message.answer("В данный момент нет активных тендеров.")
            return
        
        response = "🟢 Активные тендеры:\n\n"
        for tender in active_tenders:
            # Проверяем, участвует ли поставщик в этом тендере
            participant = await session.get(TenderParticipant, 
                {"tender_id": tender.id, "supplier_id": user.id})
            
            status = "✅ Участвуете" if participant else "🆕 Новый"
            
            response += (
                f"📋 <b>{tender.title}</b>\n"
                f"💰 Текущая цена: {tender.current_price} ₽\n"
                f"📅 Начало: {tender.start_at.strftime('%d.%m.%Y %H:%M')}\n"
                f"📝 Описание: {tender.description[:100]}...\n"
                f"🏆 Участников: {len(tender.participants)}\n"
                f"📈 Заявок: {len(tender.bids)}\n"
                f"📊 Статус: {status}\n\n"
            )
        
        # Создаем клавиатуру для участия в тендерах
        keyboard = InlineKeyboardMarkup(inline_keyboard=[])
        for tender in active_tenders:
            participant = await session.get(TenderParticipant, 
                {"tender_id": tender.id, "supplier_id": user.id})
            
            if not participant:
                keyboard.inline_keyboard.append([
                    InlineKeyboardButton(
                        text=f"Участвовать в '{tender.title}'",
                        callback_data=f"join_tender_{tender.id}"
                    )
                ])
            else:
                keyboard.inline_keyboard.append([
                    InlineKeyboardButton(
                        text=f"Подать заявку в '{tender.title}'",
                        callback_data=f"bid_tender_{tender.id}"
                    )
                ])
        
        await message.answer(response, reply_markup=keyboard)

@router.callback_query(lambda c: c.data.startswith("join_tender_"))
async def join_tender(callback: CallbackQuery):
    """Присоединение к тендеру"""
    tender_id = int(callback.data.split("_")[2])
    user_id = callback.from_user.id
    
    async with SessionLocal() as session:
        user = await session.get(User, user_id)
        if not user or not user.org_name:
            await callback.answer("Для участия необходимо зарегистрироваться.")
            return
        
        tender = await session.get(Tender, tender_id)
        if not tender or tender.status != TenderStatus.active.value:
            await callback.answer("Тендер недоступен.")
            return
        
        # Проверяем, не участвует ли уже поставщик
        existing_participant = await session.get(TenderParticipant, 
            {"tender_id": tender_id, "supplier_id": user.id})
        
        if existing_participant:
            await callback.answer("Вы уже участвуете в этом тендере.")
            return
        
        # Добавляем участника
        participant = TenderParticipant(
            tender_id=tender_id,
            supplier_id=user.id
        )
        session.add(participant)
        await session.commit()
        
        await callback.message.edit_text(
            f"✅ Вы присоединились к тендеру!\n\n"
            f"📋 {tender.title}\n"
            f"💰 Текущая цена: {tender.current_price} ₽\n"
            f"📅 Начало: {tender.start_at.strftime('%d.%m.%Y %H:%M')}\n\n"
            f"Теперь вы можете подавать заявки на снижение цены."
        )

@router.callback_query(lambda c: c.data.startswith("bid_tender_"))
async def start_bidding(callback: CallbackQuery, state: FSMContext):
    """Начало подачи заявки"""
    tender_id = int(callback.data.split("_")[2])
    user_id = callback.from_user.id
    
    async with SessionLocal() as session:
        user = await session.get(User, user_id)
        if not user or not user.org_name:
            await callback.answer("Для участия необходимо зарегистрироваться.")
            return
        
        tender = await session.get(Tender, tender_id)
        if not tender or tender.status != TenderStatus.active.value:
            await callback.answer("Тендер недоступен.")
            return
        
        # Проверяем участие
        participant = await session.get(TenderParticipant, 
            {"tender_id": tender_id, "supplier_id": user.id})
        
        if not participant:
            await callback.answer("Сначала присоединитесь к тендеру.")
            return
        
        # Проверяем, не истекло ли время аукциона
        if tender.last_bid_at and datetime.now() - tender.last_bid_at > timedelta(minutes=5):
            await callback.answer("Время подачи заявок истекло.")
            return
        
        await state.update_data(tender_id=tender_id)
        await state.set_state(AuctionParticipation.waiting_for_bid)
        
        await callback.message.answer(
            f"💰 Подача заявки в тендер '{tender.title}'\n\n"
            f"Текущая цена: {tender.current_price} ₽\n"
            f"Минимальное снижение: {tender.min_bid_decrease} ₽\n\n"
            f"Введите вашу цену (должна быть ниже текущей):"
        )

@router.message(AuctionParticipation.waiting_for_bid)
async def process_bid(message: Message, state: FSMContext):
    """Обработка заявки"""
    try:
        bid_amount = float(message.text.replace(',', '.'))
        if bid_amount <= 0:
            await message.answer("Цена должна быть больше нуля. Попробуйте снова:")
            return
    except ValueError:
        await message.answer("Введите корректную цену (число). Попробуйте снова:")
        return
    
    user_data = await state.get_data()
    tender_id = user_data['tender_id']
    user_id = message.from_user.id
    
    async with SessionLocal() as session:
        tender = await session.get(Tender, tender_id)
        if not tender or tender.status != TenderStatus.active.value:
            await message.answer("Тендер недоступен.")
            await state.clear()
            return
        
        # Проверяем, что цена ниже текущей
        if bid_amount >= tender.current_price:
            await message.answer(
                f"Ваша цена должна быть ниже текущей ({tender.current_price} ₽).\n"
                f"Попробуйте снова:"
            )
            return
        
        # Проверяем минимальное снижение
        if tender.current_price - bid_amount < tender.min_bid_decrease:
            await message.answer(
                f"Минимальное снижение цены: {tender.min_bid_decrease} ₽\n"
                f"Попробуйте снова:"
            )
            return
        
        # Создаем заявку
        bid = Bid(
            tender_id=tender_id,
            supplier_id=user_id,
            amount=bid_amount
        )
        session.add(bid)
        
        # Обновляем текущую цену тендера
        tender.current_price = bid_amount
        tender.last_bid_at = datetime.now()
        
        await session.commit()
        
        # Получаем пользователя для уведомлений
        user = await session.get(User, user_id)
        
        # Уведомляем всех участников о новой заявке
        await notify_participants_about_bid(session, tender, bid, user)
        
        await message.answer(
            f"✅ Заявка подана!\n\n"
            f"📋 Тендер: {tender.title}\n"
            f"💰 Ваша цена: {bid_amount} ₽\n"
            f"📅 Время подачи: {bid.created_at.strftime('%H:%M:%S')}\n\n"
            f"Аукцион продолжается!",
            reply_markup=menu_supplier
        )
    
    await state.clear()

async def notify_participants_about_bid(session: AsyncSession, tender: Tender, bid: Bid, bidder: User):
    """Уведомление участников о новой заявке"""
    # Получаем всех участников тендера
    stmt = select(TenderParticipant).where(TenderParticipant.tender_id == tender.id)
    result = await session.execute(stmt)
    participants = result.scalars().all()
    
    # Находим номер участника (анонимно)
    participant_number = 1
    for i, participant in enumerate(participants):
        if participant.supplier_id == bidder.id:
            participant_number = i + 1
            break
    
    notification_text = (
        f"🔥 Новая заявка в тендере '{tender.title}'!\n\n"
        f"👤 Участник {participant_number}\n"
        f"💰 Цена: {bid.amount} ₽\n"
        f"📅 Время: {bid.created_at.strftime('%H:%M:%S')}\n\n"
        f"Текущая цена: {tender.current_price} ₽"
    )
    
    # Отправляем уведомления всем участникам
    for participant in participants:
        if participant.supplier_id != bidder.id:  # Не уведомляем подавшего заявку
            try:
                await session.bot.send_message(
                    participant.supplier.telegram_id,
                    notification_text
                )
            except Exception as e:
                print(f"Ошибка отправки уведомления: {e}")

@router.message(Command("my_bids"))
async def show_my_bids(message: Message):
    """Показать заявки поставщика"""
    user_id = message.from_user.id
    
    async with SessionLocal() as session:
        user = await session.get(User, user_id)
        if not user or not user.org_name:
            await message.answer("Для участия в тендерах необходимо зарегистрироваться.")
            return
        
        # Получаем заявки пользователя
        stmt = select(Bid).where(Bid.supplier_id == user.id).order_by(Bid.created_at.desc())
        result = await session.execute(stmt)
        bids = result.scalars().all()
        
        if not bids:
            await message.answer("У вас пока нет заявок.")
            return
        
        response = "📈 Ваши заявки:\n\n"
        for bid in bids:
            tender = await session.get(Tender, bid.tender_id)
            if tender:
                response += (
                    f"📋 {tender.title}\n"
                    f"💰 Цена: {bid.amount} ₽\n"
                    f"📅 Время: {bid.created_at.strftime('%d.%m.%Y %H:%M')}\n"
                    f"📊 Статус тендера: {tender.status}\n\n"
                )
        
        await message.answer(response, reply_markup=menu_supplier)

def register_handlers(dp):
    """Регистрация хендлеров"""
    dp.include_router(router)
