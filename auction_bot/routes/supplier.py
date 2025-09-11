import asyncio
from datetime import datetime, timedelta
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, FSInputFile, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.filters import Command
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import datetime, timezone
from sqlalchemy.orm import selectinload

from ..db import SessionLocal
from ..models import User, Tender, TenderStatus, TenderParticipant, Bid, TenderAccess
from ..keyboards import menu_supplier
from ..services.timers import AuctionTimer
from ..bot import bot

auction_timer = AuctionTimer(bot)

router = Router()

# Состояния для участия в аукционе
class AuctionParticipation(StatesGroup):
    waiting_for_bid = State()

@router.message(F.text == "Активные тендеры")
async def show_active_tenders(message: Message):
    """Показать активные тендеры"""
    user_id = message.from_user.id

    async with SessionLocal() as session:
        # Проверяем пользователя
        stmt = select(User).where(User.telegram_id == user_id)
        result = await session.execute(stmt)
        user = result.scalar_one_or_none()

        if not user or not user.org_name:
            await message.answer("Для участия в тендерах необходимо зарегистрироваться.")
            return

        # Получаем активные тендеры с учетом доступа (локальное время)
        # ВАЖНО: Время в БД хранится в локальном времени, поэтому используем его для сравнения
        now_utc = datetime.now(timezone.utc)
        now_local = datetime.now()  # Локальное время системы
        
        # Получаем тендеры, к которым у пользователя есть доступ
        stmt = (
            select(Tender)
            .join(TenderAccess, Tender.id == TenderAccess.tender_id)
            .where(
                and_(
                    Tender.status == TenderStatus.active.value,
                    Tender.start_at <= now_local,  # Тендер уже начался (локальное время)
                    TenderAccess.supplier_id == user.id  # У пользователя есть доступ
                )
            )
            .options(
                selectinload(Tender.participants),
                selectinload(Tender.bids),
            )
            .order_by(Tender.start_at.desc())
        )
        result = await session.execute(stmt)
        active_tenders = result.scalars().all()

        # Получаем также тендеры, ожидающие активации, с учетом доступа
        stmt_pending = (
            select(Tender)
            .join(TenderAccess, Tender.id == TenderAccess.tender_id)
            .where(
                and_(
                    Tender.status == TenderStatus.active_pending.value,
                    Tender.start_at > now_local,  # Тендер еще не начался (локальное время)
                    TenderAccess.supplier_id == user.id  # У пользователя есть доступ
                )
            )
            .options(
                selectinload(Tender.participants),
                selectinload(Tender.bids),
            )
            .order_by(Tender.start_at.asc())
        )
        result_pending = await session.execute(stmt_pending)
        pending_tenders = result_pending.scalars().all()
        
        # Отладочная информация
        print(f"DEBUG: Локальное время: {now_local.strftime('%d.%m.%Y %H:%M:%S')}")
        print(f"DEBUG: UTC время: {now_utc.strftime('%d.%m.%Y %H:%M:%S')}")
        print(f"DEBUG: Найдено активных тендеров: {len(active_tenders)}")
        print(f"DEBUG: Найдено ожидающих тендеров: {len(pending_tenders)}")
        
        # Получаем ВСЕ тендеры для отладки
        stmt_debug = select(Tender)
        result_debug = await session.execute(stmt_debug)
        all_tenders = result_debug.scalars().all()
        print(f"DEBUG: Всего тендеров в БД: {len(all_tenders)}")
        for t in all_tenders:
            print(f"DEBUG: Тендер '{t.title}' - статус: {t.status}, время начала: {t.start_at}")

        if not active_tenders and not pending_tenders:
            await message.answer(
                "В данный момент нет активных или предстоящих тендеров, к которым у вас есть доступ.\n\n"
                "Обратитесь к организатору для получения доступа к тендерам."
            )
            return

        response = "🟢 Активные тендеры:\n\n"
        keyboard = InlineKeyboardMarkup(inline_keyboard=[])

        for tender in active_tenders:
            # Проверяем участие пользователя
            stmt = select(TenderParticipant).where(
                TenderParticipant.tender_id == tender.id,
                TenderParticipant.supplier_id == user.id
            )
            result = await session.execute(stmt)
            participant = result.scalar_one_or_none()

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

            # Кнопки участия или подачи заявки
            if not participant:
                keyboard.inline_keyboard.append([
                    InlineKeyboardButton(
                        text=f"Участвовать в '{tender.title}'",
                        callback_data=f"join_tender_{tender.id}"
                    )
                ])
            else:
                # Пользователь уже участвует - показываем кнопку подачи заявки
                keyboard.inline_keyboard.append([
                    InlineKeyboardButton(
                        text=f"Подать заявку в '{tender.title}'",
                        callback_data=f"bid_tender_{tender.id}"
                    )
                ])

        # Добавляем предстоящие тендеры
        if pending_tenders:
            response += "\n🕐 Предстоящие тендеры:\n\n"
            
            for tender in pending_tenders:
                # Проверяем участие пользователя
                stmt = select(TenderParticipant).where(
                    TenderParticipant.tender_id == tender.id,
                    TenderParticipant.supplier_id == user.id
                )
                result = await session.execute(stmt)
                participant = result.scalar_one_or_none()

                status = "✅ Участвуете" if participant else "🆕 Новый"

                response += (
                    f"📋 <b>{tender.title}</b>\n"
                    f"💰 Стартовая цена: {tender.start_price} ₽\n"
                    f"📅 Начало: {tender.start_at.strftime('%d.%m.%Y %H:%M')}\n"
                    f"📝 Описание: {tender.description[:100]}...\n"
                    f"🏆 Участников: {len(tender.participants)}\n"
                    f"📊 Статус: {status}\n\n"
                )

                # Кнопки участия для предстоящих тендеров
                if not participant:
                    keyboard.inline_keyboard.append([
                        InlineKeyboardButton(
                            text=f"Участвовать в '{tender.title}'",
                            callback_data=f"join_tender_{tender.id}"
                        )
                    ])
                else:
                    # Пользователь уже участвует в предстоящем тендере
                    keyboard.inline_keyboard.append([
                        InlineKeyboardButton(
                            text=f"Подать заявку в '{tender.title}' (ожидает активации)",
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
        stmt = select(User).where(User.telegram_id == user_id)
        result = await session.execute(stmt)
        user = result.scalar_one_or_none()
        
        if not user or not user.org_name:
            await callback.answer("Для участия необходимо зарегистрироваться.")
            return
        
        tender = await session.get(Tender, tender_id)
        if not tender or tender.status not in [TenderStatus.active.value, TenderStatus.active_pending.value]:
            await callback.answer("Тендер недоступен.")
            return
        
        # Проверяем, есть ли у пользователя доступ к тендеру
        stmt = select(TenderAccess).where(
            TenderAccess.tender_id == tender_id,
            TenderAccess.supplier_id == user.id
        )
        result = await session.execute(stmt)
        access = result.scalar_one_or_none()
        
        if not access:
            await callback.answer("У вас нет доступа к этому тендеру. Обратитесь к организатору.")
            return
        
        # Проверяем, не участвует ли уже поставщик
        stmt = select(TenderParticipant).where(
            TenderParticipant.tender_id == tender_id,
            TenderParticipant.supplier_id == user.id
        )
        result = await session.execute(stmt)
        existing_participant = result.scalar_one_or_none()

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
        
        # Создаем клавиатуру с кнопкой подачи заявки
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(
                text=f"Подать заявку в '{tender.title}'",
                callback_data=f"bid_tender_{tender.id}"
            )]
        ])
        
        await callback.message.edit_text(
            f"✅ Вы присоединились к тендеру!\n\n"
            f"📋 {tender.title}\n"
            f"💰 Текущая цена: {tender.current_price} ₽\n"
            f"📅 Начало: {tender.start_at.strftime('%d.%m.%Y %H:%M')}\n\n"
            f"Теперь вы можете подавать заявки на снижение цены.",
            reply_markup=keyboard
        )

@router.callback_query(lambda c: c.data.startswith("bid_tender_"))
async def start_bidding(callback: CallbackQuery, state: FSMContext):
    """Начало подачи заявки"""
    tender_id = int(callback.data.split("_")[2])
    user_id = callback.from_user.id
    
    async with SessionLocal() as session:
        # Получаем пользователя по telegram_id
        stmt = select(User).where(User.telegram_id == user_id)
        result = await session.execute(stmt)
        user = result.scalar_one_or_none()
        
        if not user or not user.org_name:
            await callback.answer("Для участия необходимо зарегистрироваться.")
            return
        
        tender = await session.get(Tender, tender_id)
        if not tender or tender.status not in [TenderStatus.active.value, TenderStatus.active_pending.value]:
            await callback.answer("Тендер недоступен.")
            return
        
        # Проверяем, есть ли у пользователя доступ к тендеру
        stmt = select(TenderAccess).where(
            TenderAccess.tender_id == tender_id,
            TenderAccess.supplier_id == user.id
        )
        result = await session.execute(stmt)
        access = result.scalar_one_or_none()
        
        if not access:
            await callback.answer("У вас нет доступа к этому тендеру. Обратитесь к организатору.")
            return
        
        # Проверяем участие
        stmt = select(TenderParticipant).where(
            TenderParticipant.tender_id == tender_id,
            TenderParticipant.supplier_id == user.id
        )
        result = await session.execute(stmt)
        participant = result.scalar_one_or_none()
        
        if not participant:
            await callback.answer("Сначала присоединитесь к тендеру.")
            return
        
        # Проверяем, что тендер активен (не ожидает активации)
        if tender.status == TenderStatus.active_pending.value:
            await callback.answer("Тендер еще не начался. Дождитесь активации.")
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
        if not tender or tender.status not in [TenderStatus.active.value, TenderStatus.active_pending.value]:
            await message.answer("Тендер недоступлен.")
            await state.clear()
            return
        
        # Получаем пользователя для проверки доступа
        stmt = select(User).where(User.telegram_id == user_id)
        result = await session.execute(stmt)
        user = result.scalar_one_or_none()
        
        if not user:
            await message.answer("Пользователь не найден.")
            await state.clear()
            return
        
        # Проверяем, есть ли у пользователя доступ к тендеру
        stmt = select(TenderAccess).where(
            TenderAccess.tender_id == tender_id,
            TenderAccess.supplier_id == user.id
        )
        result = await session.execute(stmt)
        access = result.scalar_one_or_none()
        
        if not access:
            await message.answer("У вас нет доступа к этому тендеру. Обратитесь к организатору.")
            await state.clear()
            return
        
        # Проверяем, что тендер активен (не ожидает активации)
        if tender.status == TenderStatus.active_pending.value:
            await message.answer("Тендер еще не начался. Дождитесь активации.")
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
            supplier_id=user.id,
            amount=bid_amount
        )
        session.add(bid)
        
        # Обновляем текущую цену тендера
        tender.current_price = bid_amount
        tender.last_bid_at = datetime.now()
        
        await session.commit()

        await auction_timer.reset_timer_for_tender(tender.id)
        
        # Получаем пользователя для уведомлений
        stmt = select(User).where(User.telegram_id == user_id)
        result = await session.execute(stmt)
        user = result.scalar_one_or_none()
        
        # Уведомляем всех участников о новой заявке
        await notify_participants_about_bid(session, tender, bid, user)
        
        await message.answer(
            f"✅ Заявка подана!\n\n"
            f"📋 Тендер: {tender.title}\n"
            f"💰 Ваша цена: {bid_amount} ₽\n"
            f"📅 Время подачи: {tender.last_bid_at.strftime('%H:%M:%S')}\n\n"
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
                # Получаем пользователя-участника для отправки уведомления
                stmt = select(User).where(User.id == participant.supplier_id)
                result = await session.execute(stmt)
                participant_user = result.scalar_one_or_none()
                
                if participant_user:
                    await bot.send_message(
                    participant_user.telegram_id,
                    notification_text
                )
            except Exception as e:
                print(f"Ошибка отправки уведомления: {e}")

@router.message(Command("debug_tenders"))
async def debug_tenders(message: Message):
    """Отладочная команда для проверки тендеров"""
    user_id = message.from_user.id
    
    async with SessionLocal() as session:
        # Проверяем пользователя
        stmt = select(User).where(User.telegram_id == user_id)
        result = await session.execute(stmt)
        user = result.scalar_one_or_none()
        
        if not user or not user.org_name:
            await message.answer("Для участия в тендерах необходимо зарегистрироваться.")
            return
        
        # Получаем текущее время в UTC и локальное время
        now_utc = datetime.now(timezone.utc)
        now_local = datetime.now()  # Локальное время системы
        
        # Получаем ВСЕ тендеры
        stmt = select(Tender).order_by(Tender.created_at.desc())
        result = await session.execute(stmt)
        all_tenders = result.scalars().all()
        
        if not all_tenders:
            await message.answer("В базе данных нет тендеров.")
            return
        
        response = f"🔍 Отладочная информация о тендерах\n"
        response += f"📅 Локальное время: {now_local.strftime('%d.%m.%Y %H:%M:%S')}\n"
        response += f"🌍 UTC время: {now_utc.strftime('%d.%m.%Y %H:%M:%S')}\n"
        response += f"📊 Всего тендеров: {len(all_tenders)}\n\n"
        
        for tender in all_tenders:
            status_emoji = {
                TenderStatus.draft.value: "📝",
                TenderStatus.active_pending.value: "⏳",
                TenderStatus.active.value: "🟢",
                TenderStatus.closed.value: "🔴",
                TenderStatus.cancelled.value: "❌"
            }.get(tender.status, "❓")
            
            status_text = {
                TenderStatus.draft.value: "Черновик",
                TenderStatus.active_pending.value: "Ожидает активации",
                TenderStatus.active.value: "Активен",
                TenderStatus.closed.value: "Завершен",
                TenderStatus.cancelled.value: "Отменен"
            }.get(tender.status, "Неизвестно")
            
            # Проверяем, должен ли тендер быть активным
            should_be_active = (
                tender.status == TenderStatus.active_pending.value and 
                tender.start_at <= now_local
            )
            
            response += (
                f"{status_emoji} <b>{tender.title}</b>\n"
                f"   ID: {tender.id}\n"
                f"   Статус: {status_text}\n"
                f"   Время начала: {tender.start_at.strftime('%d.%m.%Y %H:%M:%S') if tender.start_at else 'Не указано'}\n"
                f"   Создан: {tender.created_at.strftime('%d.%m.%Y %H:%M:%S')}\n"
            )
            
            if should_be_active:
                response += f"   ⚠️ ДОЛЖЕН БЫТЬ АКТИВНЫМ!\n"
            
            response += "\n"
        
        await message.answer(response, reply_markup=menu_supplier)

@router.message(Command("force_activate"))
async def force_activate_tenders(message: Message):
    """Принудительная активация тендеров (для отладки)"""
    user_id = message.from_user.id
    
    async with SessionLocal() as session:
        # Проверяем пользователя
        stmt = select(User).where(User.telegram_id == user_id)
        result = await session.execute(stmt)
        user = result.scalar_one_or_none()
        
        if not user or not user.org_name:
            await message.answer("Для участия в тендерах необходимо зарегистрироваться.")
            return
        
        # Получаем текущее время в UTC и локальное время
        now_utc = datetime.now(timezone.utc)
        now_local = datetime.now()  # Локальное время системы
        
        # Ищем тендеры, которые должны быть активными
        stmt = select(Tender).where(
            Tender.status == TenderStatus.active_pending.value,
            Tender.start_at <= now_local
        )
        result = await session.execute(stmt)
        pending_tenders = result.scalars().all()
        
        if not pending_tenders:
            await message.answer("Нет тендеров для принудительной активации.")
            return
        
        response = f"🔧 Принудительная активация тендеров\n"
        response += f"📅 Локальное время: {now_local.strftime('%d.%m.%Y %H:%M:%S')}\n"
        response += f"🌍 UTC время: {now_utc.strftime('%d.%m.%Y %H:%M:%S')}\n\n"
        
        for tender in pending_tenders:
            # Активируем тендер
            tender.status = TenderStatus.active.value
            tender.current_price = tender.start_price
            response += f"✅ Активирован: {tender.title}\n"
        
        await session.commit()
        response += f"\n🎉 Активировано тендеров: {len(pending_tenders)}"
        
        await message.answer(response, reply_markup=menu_supplier)

@router.message(Command("my_bids"))
async def show_my_bids(message: Message):
    """Показать заявки поставщика"""
    user_id = message.from_user.id
    
    async with SessionLocal() as session:
        # Получаем пользователя по telegram_id
        stmt = select(User).where(User.telegram_id == user_id)
        result = await session.execute(stmt)
        user = result.scalar_one_or_none()
        
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
