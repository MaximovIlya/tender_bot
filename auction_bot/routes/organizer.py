import asyncio
from datetime import datetime, timedelta
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, FSInputFile, ReplyKeyboardRemove, InlineKeyboardMarkup, InlineKeyboardButton, reply_keyboard_markup
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.filters import Command
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from . import organizer

from ..db import SessionLocal
from ..models import User, Tender, TenderStatus, TenderParticipant, TenderAccess
from ..keyboards import menu_organizer
from ..services.timers import AuctionTimer
auction_timer: AuctionTimer | None = None

def set_timer(timer: AuctionTimer):
    global auction_timer
    auction_timer = timer

def format_price(value: float | int) -> str:
        return f"{value:,.0f}".replace(",", " ")


router = Router()

# Состояния для создания тендера
class TenderCreation(StatesGroup):
    waiting_for_title = State()
    waiting_for_description = State()
    waiting_for_start_price = State()
    waiting_for_start_date = State()
    waiting_for_conditions = State()

# Состояния для управления доступом к тендерам
class AccessManagement(StatesGroup):
    selecting_tender = State()
    selecting_suppliers = State()

@router.message(lambda message: message.text == "Создать тендер")
async def start_tender_creation(message: Message, state: FSMContext):
    """Начало создания тендера"""
    user_id = message.from_user.id
    
    async with SessionLocal() as session:
        stmt = select(User).where(User.telegram_id == user_id)
        result = await session.execute(stmt)
        user = result.scalar_one_or_none()
        if not user or user.role != "organizer":
            await message.answer("У вас нет прав для создания тендеров.")
            return
        
        # Проверяем, не заблокирован ли пользователь
        if user.banned:
            await message.answer("Ваш аккаунт заблокирован. Обратитесь к администратору.")
            return
    
    await state.set_state(TenderCreation.waiting_for_title)
    await message.answer(
        "Создание нового тендера\n\n"
        "Введите название тендера:",
        reply_markup=ReplyKeyboardRemove()
    )

@router.message(TenderCreation.waiting_for_title)
async def process_tender_title(message: Message, state: FSMContext):
    """Обработка названия тендера"""
    await state.update_data(title=message.text)
    await state.set_state(TenderCreation.waiting_for_description)
    await message.answer("Введите описание тендера:")

@router.message(TenderCreation.waiting_for_description)
async def process_tender_description(message: Message, state: FSMContext):
    """Обработка описания тендера"""
    await state.update_data(description=message.text)
    await state.set_state(TenderCreation.waiting_for_start_price)
    await message.answer("Введите стартовую цену (в рублях):")

@router.message(TenderCreation.waiting_for_start_price)
async def process_tender_price(message: Message, state: FSMContext):
    """Обработка стартовой цены"""
    try:
        price = float(message.text.replace(',', '.'))
        if price <= 0:
            await message.answer("Цена должна быть больше нуля. Попробуйте снова:")
            return
    except ValueError:
        await message.answer("Введите корректную цену (число). Попробуйте снова:")
        return
    
    await state.update_data(start_price=price, current_price=price)
    await state.set_state(TenderCreation.waiting_for_start_date)
    await message.answer(
        "Введите дату и время начала аукциона в формате ДД.ММ.ГГГГ ЧЧ:ММ\n"
        "Например: 25.12.2024 14:00"
    )
    
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

async def notify_admins_about_new_tender(tender: Tender, bot):
    """Отправка уведомления админам о новом тендере с кнопкой подтверждения"""
    async with SessionLocal() as session:
        stmt = select(User).where(User.role == "admin")
        result = await session.execute(stmt)
        admins = result.scalars().all()
        
        if not admins:
            print("Нет администраторов для уведомления.")
            return

        # Формируем клавиатуру с кнопкой подтверждения
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Одобрить тендер",
                    callback_data=f"approve_tender_{tender.id}"  # сюда идёт ID тендера
                )
            ]
        ])

        for admin in admins:
            await bot.send_message(
                admin.telegram_id,
                f"📢 Новый тендер ожидает подтверждения:\n\n"
                f"📋 Название: {tender.title}\n"
                f"💰 Стартовая цена: {format_price(tender.start_price)} ₽\n"
                f"📅 Дата начала: {tender.start_at.strftime('%d.%m.%Y %H:%M')}\n"
                f"📝 Описание: {tender.description}",
                reply_markup=keyboard
            )

        
        


@router.message(TenderCreation.waiting_for_start_date)
async def process_tender_date(message: Message, state: FSMContext):
    """Обработка даты начала"""
    try:
        start_date = datetime.strptime(message.text, "%d.%m.%Y %H:%M")
        if start_date <= datetime.now():
            await message.answer("Дата начала должна быть в будущем. Попробуйте снова:")
            return
    except ValueError:
        await message.answer(
            "Неверный формат даты. Используйте формат ДД.ММ.ГГГГ ЧЧ:ММ\n"
            "Попробуйте снова:"
        )
        return
    
    await state.update_data(start_at=start_date)
    await state.set_state(TenderCreation.waiting_for_conditions)
    await message.answer(
        "Прикрепите файл с условиями тендера (если есть) или отправьте 'нет':"
    )

@router.message(TenderCreation.waiting_for_conditions)
@router.message(TenderCreation.waiting_for_conditions)
async def process_tender_conditions(message: Message, state: FSMContext):
    """Обработка условий тендера (файл или 'нет')"""
    user_data = await state.get_data()
    user_id = message.from_user.id

    conditions_path = None
    if message.document:
        # Получаем расширение файла
        ext = message.document.file_name.split('.')[-1]
        file_path = f"files/tender_{user_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.{ext}"
        
        # Скачиваем файл
        await message.bot.download(message.document, file_path)
        conditions_path = file_path
    elif message.text.strip().lower() != "нет":
        await message.answer("Отправьте файл с условиями или напишите 'нет':")
        return  # ждем корректный ввод
    
    # Создание тендера
    async with SessionLocal() as session:
        stmt = select(User).where(User.telegram_id == user_id)
        result = await session.execute(stmt)
        user = result.scalar_one_or_none()

        if not user:
            await message.answer("❌ Пользователь не найден в базе. Попробуйте заново.")
            return

        tender = Tender(
            title=user_data['title'],
            description=user_data['description'],
            start_price=user_data['start_price'],
            current_price=user_data['current_price'],
            start_at=user_data['start_at'],
            conditions_path=conditions_path,
            organizer_id=user.id,
            status=TenderStatus.draft.value
        )

        session.add(tender)
        await session.commit()

        # Уведомление админов о новом тендере
        await notify_admins_about_new_tender(tender, message.bot)
        await auction_timer.schedule_start_notifications(tender.id)

        price_str = f"{tender.start_price:,.0f}".replace(",", " ")
        await message.answer(
            f"✅ Тендер успешно создан!\n\n"
            f"📋 Название: {tender.title}\n"
            f"💰 Стартовая цена: {price_str} ₽\n"
            f"📅 Дата начала: {tender.start_at.strftime('%d.%m.%Y %H:%M')}\n"
            f"📝 Описание: {tender.description}\n\n"
            f"Тендер будет активен с {tender.start_at.strftime('%d.%m.%Y %H:%M')}",
            reply_markup=menu_organizer
        )

    await state.clear()

@router.message(F.text == "Удалить тендер")
async def delete_tender(message: Message):
    """Выбор тендера для удаления"""
    user_id = message.from_user.id

    async with SessionLocal() as session:
        # Проверяем, что это организатор
        stmt = select(User).where(User.telegram_id == user_id)
        result = await session.execute(stmt)
        user = result.scalar_one_or_none()
        if not user or user.role != "organizer":
            await message.answer("У вас нет прав для удаления тендеров.")
            return

        if user.banned:
            await message.answer("Ваш аккаунт заблокирован. Обратитесь к администратору.")
            return

        # Получаем тендеры, которые ещё не начались
        stmt = select(Tender).where(
            Tender.organizer_id == user.id,
            Tender.start_at > datetime.now(),
            Tender.status.in_([TenderStatus.draft.value, TenderStatus.active.value])
        ).order_by(Tender.start_at.asc())

        result = await session.execute(stmt)
        tenders = result.scalars().all()

        if not tenders:
            await message.answer("❌ У вас нет тендеров, которые можно удалить.")
            return

        # Клавиатура с выбором
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(
                text=f"{t.title} ({t.start_at.strftime('%d.%m.%Y %H:%M')})",
                callback_data=f"confirm_delete_{t.id}"
            )] for t in tenders
        ])

        await message.answer("Выберите тендер для удаления:", reply_markup=keyboard)


@router.callback_query(lambda c: c.data.startswith("confirm_delete_"))
async def confirm_delete_tender(callback: CallbackQuery):
    """Подтверждение удаления"""
    tender_id = int(callback.data.split("_")[2])

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Да, удалить", callback_data=f"delete_tender_{tender_id}"),
            InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_delete")
        ]
    ])

    await callback.message.edit_text(
        "Вы уверены, что хотите удалить этот тендер? Действие необратимо.",
        reply_markup=keyboard
    )


@router.callback_query(lambda c: c.data.startswith("delete_tender_"))
async def delete_tender_confirmed(callback: CallbackQuery):
    tender_id = int(callback.data.split("_")[2])
    user_id = callback.from_user.id

    async with SessionLocal() as session:
        tender = await session.get(
            Tender,
            tender_id,
            options=[selectinload(Tender.organizer)]
        )

        if not tender:
            await callback.answer("❌ Тендер не найден.")
            return

        if tender.organizer.telegram_id != user_id:
            await callback.answer("❌ У вас нет прав на удаление этого тендера.")
            return

        if tender.start_at <= datetime.now():
            await callback.answer("❌ Этот тендер уже начался, его нельзя удалить.")
            return

        # отменяем таймер и уведомления
        if auction_timer:
            await auction_timer.cancel_timer_for_tender(tender.id)
            await auction_timer.cancel_start_notifications(tender.id)

        if tender and tender.organizer.telegram_id == user_id:
            tender.status = "cancelled"
       
            await session.commit()

    await callback.message.edit_text("✅ Тендер успешно удалён.")
    await callback.message.answer(
        reply_markup=menu_organizer  # тут ReplyKeyboardMarkup
    )





@router.callback_query(F.data == "cancel_delete")
async def cancel_delete(callback: CallbackQuery):
    """Отмена удаления"""
    await callback.message.edit_text("Удаление отменено.", reply_markup=menu_organizer)

@router.message(F.text == "Мои тендеры")
async def show_my_tenders(message: Message):
    """Показать тендеры организатора"""
    user_id = message.from_user.id

    async with SessionLocal() as session:
        # Находим пользователя по telegram_id
        stmt = select(User).where(User.telegram_id == user_id)
        result = await session.execute(stmt)
        user = result.scalar_one_or_none()

        if not user or user.role != "organizer":
            await message.answer("У вас нет прав для просмотра тендеров.")
            return
        
        # Проверяем, не заблокирован ли пользователь
        if user.banned:
            await message.answer("Ваш аккаунт заблокирован. Обратитесь к администратору.")
            return

        # Получаем только активные тендеры организатора (исключаем завершенные)
        stmt = (
            select(Tender)
            .where(
                Tender.organizer_id == user.id,
                Tender.status.not_in([TenderStatus.closed.value, TenderStatus.cancelled.value])
            )
            .options(
                selectinload(Tender.participants),
                selectinload(Tender.bids),
            )
            .order_by(Tender.created_at.desc())
        )
        result = await session.execute(stmt)
        tenders = result.scalars().all()

        if not tenders:
            await message.answer("У вас пока нет тендеров.")
            return

        # Формируем ответ
        response = "📋 Ваши тендеры:\n\n"
        from zoneinfo import ZoneInfo
        from datetime import timezone as _tz
        local_tz = ZoneInfo("Europe/Moscow")
        for tender in tenders:
            created_local = tender.created_at.replace(tzinfo=_tz.utc).astimezone(local_tz) if tender.created_at and tender.created_at.tzinfo is None else (tender.created_at.astimezone(local_tz) if tender.created_at else None)
            status_emoji = {
                "draft": "📝",
                "active": "🟢",
                "closed": "🔴",
                "cancelled": "❌",
            }

            response += (
                f"{status_emoji.get(tender.status, '❓')} <b>{tender.title}</b>\n"
                f"💰 Цена: {format_price(tender.current_price)} ₽\n"
                f"📅 Дата: {tender.start_at.strftime('%d.%m.%Y %H:%M') if tender.start_at else 'Не указана'}\n"
                f"📊 Статус: {tender.status}\n"
                f"🏆 Участников: {len(tender.participants)}\n"
                f"📈 Заявок: {len(tender.bids)}\n\n"
            )

        await message.answer(response, reply_markup=menu_organizer)

@router.message(F.text == "История")
async def show_tender_history(message: Message):
    """Показать историю завершенных тендеров организатора"""
    user_id = message.from_user.id

    async with SessionLocal() as session:
        # Находим пользователя по telegram_id
        stmt = select(User).where(User.telegram_id == user_id)
        result = await session.execute(stmt)
        user = result.scalar_one_or_none()

        if not user or user.role != "organizer":
            await message.answer("У вас нет прав для просмотра истории тендеров.")
            return
        
        # Проверяем, не заблокирован ли пользователь
        if user.banned:
            await message.answer("Ваш аккаунт заблокирован. Обратитесь к администратору.")
            return

        # Получаем только завершенные тендеры организатора
        stmt = (
            select(Tender)
            .where(
                Tender.organizer_id == user.id,
                Tender.status.in_([TenderStatus.closed.value, TenderStatus.cancelled.value])
            )
            .options(
                selectinload(Tender.participants),
                selectinload(Tender.bids),
            )
            .order_by(Tender.created_at.desc())
        )

        result = await session.execute(stmt)
        closed_tenders = result.scalars().all()

        if not closed_tenders:
            await message.answer("У вас пока нет завершенных тендеров.", reply_markup=menu_organizer)
            return

        # Формируем ответ
        response = "📚 История завершенных тендеров:\n\n"
        for tender in closed_tenders:
            from zoneinfo import ZoneInfo
            from datetime import timezone as _tz
            local_tz = ZoneInfo("Europe/Moscow")
            created_local = tender.created_at.astimezone(local_tz) if tender.created_at.tzinfo else tender.created_at.replace(tzinfo=_tz.utc).astimezone(local_tz)
            
            # Находим победителя (самую низкую ставку)
            winner_info = ""
            if tender.bids:
                winner_bid = min(tender.bids, key=lambda x: x.amount)
                winner = await session.get(User, winner_bid.supplier_id)
                if winner:
                    winner_info = f"🏆 Победитель: {winner.org_name} ({winner_bid.amount:,.0f} ₽)"

            status_text = {
                TenderStatus.closed.value: "Завершён",
                "cancelled": "Отменён"
            }.get(tender.status, "Неизвестно")
            response += (
                f"🔴 <b>{tender.title}</b> — {status_text}\n"
                f"💰 Стартовая цена: {format_price(tender.start_price)} ₽\n"
                f"💰 Финальная цена: {format_price(tender.current_price)} ₽\n"
                f"📅 Дата начала: {tender.start_at.strftime('%d.%m.%Y %H:%M')}\n"
                f"📅 Создан: {created_local.strftime('%d.%m.%Y %H:%M')}\n"
                f"🏆 Участников: {len(tender.participants)}\n"
                f"📈 Заявок: {len(tender.bids)}\n"
                f"{winner_info}\n\n"
            )

        await message.answer(response, reply_markup=menu_organizer)

@router.message(Command("start_auction"))
async def start_auction(message: Message):
    """Запуск аукциона"""
    user_id = message.from_user.id
    
    async with SessionLocal() as session:
        user = await session.get(User, user_id)
        if not user or user.role != "organizer":
            await message.answer("У вас нет прав для запуска аукционов.")
            return
        
        # Проверяем, не заблокирован ли пользователь
        if user.banned:
            await message.answer("Ваш аккаунт заблокирован. Обратитесь к администратору.")
            return
        
        # Получаем черновики тендеров
        stmt = select(Tender).where(
            Tender.organizer_id == user.id,
            Tender.status == TenderStatus.draft
        )
        result = await session.execute(stmt)
        draft_tenders = result.scalars().all()
        
        if not draft_tenders:
            await message.answer("У вас нет черновиков тендеров для запуска.")
            return
        
        # Создаем клавиатуру для выбора тендера
        keyboard = InlineKeyboardMarkup(inline_keyboard=[])
        for tender in draft_tenders:
            keyboard.inline_keyboard.append([
                InlineKeyboardButton(
                    text=f"{tender.title} - {tender.start_price} ₽",
                    callback_data=f"start_tender_{tender.id}"
                )
            ])
        
        await message.answer(
            "Выберите тендер для запуска:",
            reply_markup=keyboard
        )

@router.callback_query(lambda c: c.data.startswith("start_tender_"))
async def process_start_tender(callback: CallbackQuery):
    """Обработка запуска тендера"""
    tender_id = int(callback.data.split("_")[2])
    
    async with SessionLocal() as session:
        tender = await session.get(Tender, tender_id)
        if not tender:
            await callback.answer("Тендер не найден.")
            return
        
        if tender.status != TenderStatus.draft:
            await callback.answer("Тендер уже запущен или завершен.")
            return
        
        # Активируем тендер
        tender.status = TenderStatus.active.value
        await session.commit()
        
        await callback.message.edit_text(
            f"✅ Аукцион запущен!\n\n"
            f"📋 {tender.title}\n"
            f"💰 Стартовая цена: {format_price(tender.start_price)} ₽\n"
            f"📅 Начало: {tender.start_at.strftime('%d.%m.%Y %H:%M')}\n\n"
            f"Поставщики могут подавать заявки!"
        )

@router.message(F.text == "Управление доступом")
async def start_access_management(message: Message, state: FSMContext):
    """Начало управления доступом к тендерам"""
    user_id = message.from_user.id
    
    async with SessionLocal() as session:
        stmt = select(User).where(User.telegram_id == user_id)
        result = await session.execute(stmt)
        user = result.scalar_one_or_none()
        if not user or user.role != "organizer":
            await message.answer("У вас нет прав для управления доступом к тендерам.")
            return
        
        # Проверяем, не заблокирован ли пользователь
        if user.banned:
            await message.answer("Ваш аккаунт заблокирован. Обратитесь к администратору.")
            return
        
        # Получаем тендеры организатора
        stmt = (
            select(Tender)
            .where(
                Tender.organizer_id == user.id,
                Tender.status != TenderStatus.closed.value   # исключаем закрытые
            )
            .order_by(Tender.created_at.desc())
        )

        result = await session.execute(stmt)
        tenders = result.scalars().all()
        
        if not tenders:
            await message.answer("У вас пока нет тендеров для управления доступом.")
            return
        
        # Создаем клавиатуру для выбора тендера
        keyboard = InlineKeyboardMarkup(inline_keyboard=[])
        for tender in tenders:
            keyboard.inline_keyboard.append([
                InlineKeyboardButton(
                    text=f"{tender.title} ({tender.status})",
                    callback_data=f"manage_access_{tender.id}"
                )
            ])
        
        await message.answer(
            "Выберите тендер для управления доступом:",
            reply_markup=keyboard
        )

@router.callback_query(lambda c: c.data.startswith("manage_access_"))
async def manage_tender_access(callback: CallbackQuery, state: FSMContext = None):
    """Управление доступом к конкретному тендеру"""
    tender_id = int(callback.data.split("_")[2])
    user_id = callback.from_user.id
    
    async with SessionLocal() as session:
        # Проверяем права
        stmt = select(User).where(User.telegram_id == user_id)
        result = await session.execute(stmt)
        user = result.scalar_one_or_none()
        if not user or user.role != "organizer":
            await callback.answer("У вас нет прав для управления доступом.")
            return
        
        # Проверяем, не заблокирован ли пользователь
        if user.banned:
            await callback.answer("Ваш аккаунт заблокирован. Обратитесь к администратору.")
            return
        
        # Получаем тендер
        tender = await session.get(Tender, tender_id)
        if not tender or tender.organizer_id != user.id:
            await callback.answer("Тендер не найден или у вас нет прав.")
            return
        
        # Получаем всех поставщиков
        stmt = select(User).where(User.role == "supplier", User.org_name.isnot(None))
        result = await session.execute(stmt)
        suppliers = result.scalars().all()
        
        if not suppliers:
            await callback.answer("Нет зарегистрированных поставщиков.")
            return
        
        # Получаем текущие права доступа
        stmt = select(TenderAccess).where(TenderAccess.tender_id == tender_id)
        result = await session.execute(stmt)
        current_access = result.scalars().all()
        current_supplier_ids = {access.supplier_id for access in current_access}
        
        # Создаем клавиатуру для выбора поставщиков
        keyboard = InlineKeyboardMarkup(inline_keyboard=[])
        
        for supplier in suppliers:
            status = "✅" if supplier.id in current_supplier_ids else "❌"
            keyboard.inline_keyboard.append([
                InlineKeyboardButton(
                    text=f"{status} {supplier.org_name}",
                    callback_data=f"toggle_access_{tender_id}_{supplier.id}"
                )
            ])
        
        # Добавляем кнопку завершения
        keyboard.inline_keyboard.append([
            InlineKeyboardButton(
                text="✅ Завершить настройку",
                callback_data=f"finish_access_{tender_id}"
            )
        ])
        
        # Формируем сообщение
        response = f"🔐 Управление доступом к тендеру\n\n"
        response += f"📋 <b>{tender.title}</b>\n"
        response += f"📊 Статус: {tender.status}\n"
        response += f"👥 Доступ предоставлен: {len(current_supplier_ids)} поставщикам\n\n"
        response += f"Выберите поставщиков, которым предоставить доступ:\n"
        response += f"✅ - доступ предоставлен\n"
        response += f"❌ - доступ не предоставлен\n\n"
        response += f"Нажмите на поставщика, чтобы изменить его статус доступа."
        
        try:
            await callback.message.edit_text(response, reply_markup=keyboard)
        except Exception as e:
            # Если не удается отредактировать сообщение, отправляем новое
            print(f"Ошибка при редактировании сообщения в manage_tender_access: {e}")
            await callback.message.answer(response, reply_markup=keyboard)

@router.callback_query(lambda c: c.data.startswith("toggle_access_"))
async def toggle_supplier_access(callback: CallbackQuery):
    """Переключение доступа поставщика к тендеру"""
    parts = callback.data.split("_")
    tender_id = int(parts[2])
    supplier_id = int(parts[3])
    user_id = callback.from_user.id
    
    async with SessionLocal() as session:
        # Проверяем права
        stmt = select(User).where(User.telegram_id == user_id)
        result = await session.execute(stmt)
        user = result.scalar_one_or_none()
        if not user or user.role != "organizer":
            await callback.answer("У вас нет прав для управления доступом.")
            return
        
        # Проверяем, не заблокирован ли пользователь
        if user.banned:
            await callback.answer("Ваш аккаунт заблокирован. Обратитесь к администратору.")
            return
        
        # Получаем тендер
        tender = await session.get(Tender, tender_id)
        if not tender or tender.organizer_id != user.id:
            await callback.answer("Тендер не найден или у вас нет прав.")
            return
        
        # Проверяем текущий доступ
        stmt = select(TenderAccess).where(
            TenderAccess.tender_id == tender_id,
            TenderAccess.supplier_id == supplier_id
        )
        result = await session.execute(stmt)
        existing_access = result.scalar_one_or_none()
        
        if existing_access:
            # Удаляем доступ
            await session.delete(existing_access)
            action = "отозван"
        else:
            # Предоставляем доступ
            access = TenderAccess(
                tender_id=tender_id,
                supplier_id=supplier_id
            )
            session.add(access)
            action = "предоставлен"
        
        await session.commit()
        
        # Получаем поставщика для уведомления
        supplier = await session.get(User, supplier_id)
        if supplier:
            await callback.answer(f"Доступ {action} для {supplier.org_name}")
        
        # Обновляем интерфейс
        await manage_tender_access(callback, None)

@router.callback_query(lambda c: c.data.startswith("finish_access_"))
async def finish_access_management(callback: CallbackQuery):
    """Завершение управления доступом"""
    try:
        tender_id = int(callback.data.split("_")[2])
        user_id = callback.from_user.id
        print(f"DEBUG: Завершение настройки доступа для тендера {tender_id}, пользователь {user_id}")
    except Exception as e:
        print(f"DEBUG: Ошибка при парсинге callback data: {e}")
        await callback.answer("Ошибка при обработке запроса.")
        return
    
    try:
        async with SessionLocal() as session:
            # Проверяем права
            stmt = select(User).where(User.telegram_id == user_id)
            result = await session.execute(stmt)
            user = result.scalar_one_or_none()
            if not user or user.role != "organizer":
                await callback.answer("У вас нет прав для управления доступом.")
                return
            
            # Получаем тендер
            tender = await session.get(Tender, tender_id)
            if not tender or tender.organizer_id != user.id:
                await callback.answer("Тендер не найден или у вас нет прав.")
                return
            
            # Получаем количество предоставленных доступов
            stmt = select(TenderAccess).where(TenderAccess.tender_id == tender_id)
            result = await session.execute(stmt)
            access_count = len(result.scalars().all())
            
            print(f"DEBUG: Найдено {access_count} доступов для тендера {tender_id}")
            
            try:
                await callback.message.edit_text(
                    f"✅ Настройка доступа завершена!\n\n"
                    f"📋 Тендер: {tender.title}\n"
                    f"👥 Доступ предоставлен: {access_count} поставщикам\n\n"
                    f"Теперь только выбранные поставщики смогут видеть этот тендер.",
                    reply_markup=menu_organizer
                )
            except Exception as e:
                # Если не удается отредактировать сообщение, отправляем новое
                print(f"Ошибка при редактировании сообщения: {e}")
                await callback.message.answer(
                    f"✅ Настройка доступа завершена!\n\n"
                    f"📋 Тендер: {tender.title}\n"
                    f"👥 Доступ предоставлен: {access_count} поставщикам\n\n"
                    f"Теперь только выбранные поставщики смогут видеть этот тендер.",
                    reply_markup=menu_organizer
                )
    except Exception as e:
        print(f"DEBUG: Общая ошибка в finish_access_management: {e}")
        await callback.answer("Произошла ошибка при завершении настройки доступа.")

def register_handlers(dp):
    """Регистрация хендлеров"""
    dp.include_router(router)
