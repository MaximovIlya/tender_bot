import asyncio
from datetime import datetime
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.filters import Command
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ..db import SessionLocal
from ..models import User, Tender, TenderStatus
from ..keyboards import menu_admin
from ..config import settings

router = Router()

# Состояния для блокировки пользователей
class BanUser(StatesGroup):
    waiting_for_user_id = State()

@router.message(lambda message: message.text == "Пользователи")
async def show_users(message: Message):
    """Показать список пользователей"""
    user_id = message.from_user.id
    
    if user_id not in settings.ADMIN_IDS:
        await message.answer("У вас нет прав администратора.")
        return
    
    async with SessionLocal() as session:
        # Получаем всех пользователей
        stmt = select(User).order_by(User.created_at.desc())
        result = await session.execute(stmt)
        users = result.scalars().all()
        
        if not users:
            await message.answer("Пользователей пока нет.")
            return
        
        response = "👥 Список пользователей:\n\n"
        for user in users:
            role_emoji = {
                "admin": "👑",
                "organizer": "🎯",
                "supplier": "🏢"
            }
            
            status = "🚫 Заблокирован" if user.banned else "✅ Активен"
            registration = "✅ Зарегистрирован" if user.org_name else "📝 Не зарегистрирован"
            
            from zoneinfo import ZoneInfo
            from datetime import timezone as _tz
            local_tz = ZoneInfo("Europe/Moscow")
            created_local = user.created_at.astimezone(local_tz) if user.created_at.tzinfo else user.created_at.replace(tzinfo=_tz.utc).astimezone(local_tz)
            response += (
                f"{role_emoji.get(user.role, '❓')} <b>ID: {user.telegram_id}</b>\n"
                f"👤 Username: @{user.username or 'Нет'}\n"
                f"🎭 Роль: {user.role}\n"
                f"📊 Статус: {status}\n"
                f"📝 Регистрация: {registration}\n"
                f"📅 Создан: {created_local.strftime('%d.%m.%Y')}\n"
            )
            
            if user.org_name:
                response += f"🏢 Организация: {user.org_name}\n"
            
            response += "\n"
        
        # Создаем клавиатуру для управления
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Заблокировать/Разблокировать", callback_data="toggle_ban")],
            [InlineKeyboardButton(text="Статистика", callback_data="show_stats")]
        ])
        
        await message.answer(response, reply_markup=keyboard)

@router.callback_query(lambda c: c.data == "toggle_ban")
async def toggle_user_ban(callback: CallbackQuery, state: FSMContext):
    """Начало процесса блокировки/разблокировки пользователя"""
    user_id = callback.from_user.id
    
    if user_id not in settings.ADMIN_IDS:
        await callback.answer("У вас нет прав администратора.")
        return
    
    await state.set_state(BanUser.waiting_for_user_id)
    await callback.message.answer(
        "Введите Telegram ID пользователя для блокировки/разблокировки:"
    )

@router.message(BanUser.waiting_for_user_id)
async def process_ban_user_id(message: Message, state: FSMContext):
    """Обработка ID пользователя для блокировки"""
    try:
        telegram_id = int(message.text)
        
        async with SessionLocal() as session:
            # Ищем пользователя
            stmt = select(User).where(User.telegram_id == telegram_id)
            result = await session.execute(stmt)
            user = result.scalar_one_or_none()
            
            if not user:
                await message.answer("Пользователь не найден.")
                await state.clear()
                return
            
            # Переключаем статус блокировки
            old_status = "заблокирован" if user.banned else "активен"
            user.banned = not user.banned
            new_status = "заблокирован" if user.banned else "активен"
            
            await session.commit()
            
            await message.answer(
                f"✅ Статус пользователя изменен!\n\n"
                f"👤 Пользователь: {telegram_id}\n"
                f"🏢 Организация: {user.org_name or 'Не указана'}\n"
                f"🎭 Роль: {user.role}\n"
                f"📊 Старый статус: {old_status}\n"
                f"📊 Новый статус: {new_status}"
            )
            
            # Уведомляем пользователя о блокировке/разблокировке
            try:
                if user.banned:
                    await message.bot.send_message(
                        telegram_id,
                        "🚫 Ваш аккаунт был заблокирован администратором.\n"
                        "Обратитесь к администратору для разблокировки."
                    )
                else:
                    await message.bot.send_message(
                        telegram_id,
                        "✅ Ваш аккаунт был разблокирован администратором.\n"
                        "Теперь вы можете пользоваться ботом."
                    )
            except Exception as e:
                print(f"Ошибка отправки уведомления пользователю {telegram_id}: {e}")
        
        await state.clear()
        
    except ValueError:
        await message.answer("Введите корректный ID (число). Попробуйте снова:")

@router.callback_query(lambda c: c.data == "show_stats")
async def show_system_stats(callback: CallbackQuery):
    """Показать статистику системы"""
    user_id = callback.from_user.id
    
    if user_id not in settings.ADMIN_IDS:
        await callback.answer("У вас нет прав администратора.")
        return
    
    async with SessionLocal() as session:
        # Статистика пользователей
        stmt = select(User)
        result = await session.execute(stmt)
        users = result.scalars().all()
        
        total_users = len(users)
        suppliers = len([u for u in users if u.role == "supplier"])
        organizers = len([u for u in users if u.role == "organizer"])
        admins = len([u for u in users if u.role == "admin"])
        banned_users = len([u for u in users if u.banned])
        registered_suppliers = len([u for u in users if u.role == "supplier" and u.org_name])
        
        # Статистика тендеров
        stmt = select(Tender)
        result = await session.execute(stmt)
        tenders = result.scalars().all()
        
        total_tenders = len(tenders)
        draft_tenders = len([t for t in tenders if t.status == "draft"])
        active_tenders = len([t for t in tenders if t.status == "active"])
        closed_tenders = len([t for t in tenders if t.status == "closed"])
        
        from zoneinfo import ZoneInfo
        local_tz = ZoneInfo("Europe/Moscow")
        stats_text = (
            "📊 Статистика системы\n\n"
            f"👥 Пользователи:\n"
            f"   • Всего: {total_users}\n"
            f"   • Поставщики: {suppliers}\n"
            f"   • Организаторы: {organizers}\n"
            f"   • Администраторы: {admins}\n"
            f"   • Заблокированы: {banned_users}\n"
            f"   • Зарегистрированы: {registered_suppliers}\n\n"
            f"📋 Тендеры:\n"
            f"   • Всего: {total_tenders}\n"
            f"   • Черновики: {draft_tenders}\n"
            f"   • Активные: {active_tenders}\n"
            f"   • Завершенные: {closed_tenders}\n\n"
            f"📅 Дата: {datetime.now(local_tz).strftime('%d.%m.%Y %H:%M')}"
        )
        
        await callback.message.edit_text(stats_text)

@router.message(Command("admin"))
async def admin_command(message: Message):
    """Команда администратора"""
    user_id = message.from_user.id
    
    if user_id not in settings.ADMIN_IDS:
        await message.answer("У вас нет прав администратора.")
        return
    
    await message.answer("Панель администратора", reply_markup=menu_admin)

@router.message(Command("system_info"))
async def system_info(message: Message):
    """Информация о системе"""
    user_id = message.from_user.id
    
    if user_id not in settings.ADMIN_IDS:
        await message.answer("У вас нет прав администратора.")
        return
    
    from zoneinfo import ZoneInfo
    local_tz = ZoneInfo("Europe/Moscow")
    info_text = (
        "🔧 Информация о системе\n\n"
        f"🤖 Версия бота: 1.0.0\n"
        f"📅 Дата запуска: {datetime.now(local_tz).strftime('%d.%m.%Y %H:%M')}\n"
        f"💾 База данных: SQLite\n"
        f"🔑 Администраторы: {len(settings.ADMIN_IDS)}\n"
        f"📁 Папка файлов: {settings.FILES_DIR}\n\n"
        f"📋 Функции:\n"
        f"   • Создание и управление тендерами\n"
        f"   • Аукционы на понижение цены\n"
        f"   • Анонимное участие поставщиков\n"
        f"   • Автоматическое завершение торгов\n"
        f"   • Генерация отчетов\n"
        f"   • Управление пользователями"
    )
    
    await message.answer(info_text)

@router.message(lambda message: message.text == "Одобрить тендер")
async def approve_tender(message: Message):
    user_id = message.from_user.id

    async with SessionLocal() as session:
        stmt = select(User).where(User.telegram_id == user_id)
        result = await session.execute(stmt)
        user = result.scalar_one_or_none()

        if user_id not in settings.ADMIN_IDS:
            await message.answer("У вас нет прав для одобрения тендеров.")
            return

        # Получаем все черновики
        stmt = select(Tender).where(Tender.status == TenderStatus.draft.value)
        result = await session.execute(stmt)
        drafts = result.scalars().all()

        if not drafts:
            await message.answer("Нет тендеров для одобрения.")
            return

        response = "📝 Тендеры в черновиках:\n\n"
        keyboard = InlineKeyboardMarkup(inline_keyboard=[])

        for t in drafts:
            response += f"{t.id}: {t.title} | Начало: {t.start_at.strftime('%d.%m.%Y %H:%M')}\n"
            keyboard.inline_keyboard.append([
                InlineKeyboardButton(
                    text=f"Одобрить '{t.title}'",
                    callback_data=f"approve_tender_{t.id}"
                )
            ])

        await message.answer(response, reply_markup=keyboard)
        


@router.message(lambda message: message.text == "Статус тендеров")
async def show_tender_statuses(message: Message):
    """Показать статусы всех тендеров"""
    user_id = message.from_user.id

    if user_id not in settings.ADMIN_IDS:
        await message.answer("У вас нет прав для просмотра статусов тендеров.")
        return

    async with SessionLocal() as session:
        # Получаем все тендеры с их статусами
        stmt = select(Tender).order_by(Tender.created_at.desc())
        result = await session.execute(stmt)
        tenders = result.scalars().all()

        if not tenders:
            await message.answer("Нет тендеров в системе.")
            return

        response = "📊 Статусы тендеров:\n\n"
        
        for t in tenders:
            status_emoji = {
                TenderStatus.draft.value: "📝",
                TenderStatus.active_pending.value: "⏳",
                TenderStatus.active.value: "🟢",
                TenderStatus.closed.value: "🔴",
                TenderStatus.cancelled.value: "❌"
            }.get(t.status, "❓")
            
            status_text = {
                TenderStatus.draft.value: "Черновик",
                TenderStatus.active_pending.value: "Ожидает активации",
                TenderStatus.active.value: "Активен",
                TenderStatus.closed.value: "Завершен",
                TenderStatus.cancelled.value: "Отменен"
            }.get(t.status, "Неизвестно")
            
            from zoneinfo import ZoneInfo
            from datetime import timezone as _tz
            local_tz = ZoneInfo("Europe/Moscow")
            created_local = t.created_at.astimezone(local_tz) if t.created_at.tzinfo else t.created_at.replace(tzinfo=_tz.utc).astimezone(local_tz)
            response += (
                f"{status_emoji} <b>{t.title}</b>\n"
                f"   ID: {t.id}\n"
                f"   Статус: {status_text}\n"
                f"   Начало: {t.start_at.strftime('%d.%m.%Y %H:%M') if t.start_at else 'Не указано'}\n"
                f"   Создан: {created_local.strftime('%d.%m.%Y %H:%M')}\n\n"
            )

        await message.answer(response)


@router.callback_query(lambda c: c.data.startswith("approve_tender_"))
async def process_approve_tender(callback: CallbackQuery):
    tender_id = int(callback.data.split("_")[-1])

    async with SessionLocal() as session:
        tender = await session.get(Tender, tender_id)
        if not tender:
            await callback.answer("Тендер не найден.", show_alert=True)
            return

        # Тендер переходит в статус "ожидающий активации"
        tender.status = TenderStatus.active_pending.value
        await session.commit()

    await callback.message.edit_text(f"✅ Тендер '{tender.title}' одобрен! Он будет активирован в {tender.start_at.strftime('%d.%m.%Y %H:%M')}")

@router.message(F.text == "История")
async def show_admin_history(message: Message):
    """Показать историю всех завершенных тендеров для админа"""
    user_id = message.from_user.id
    
    if user_id not in settings.ADMIN_IDS:
        await message.answer("У вас нет прав администратора.")
        return
    
    async with SessionLocal() as session:
        # Получаем все завершенные тендеры
        stmt = (
            select(Tender)
            .where(Tender.status == TenderStatus.closed.value)
            .options(
                selectinload(Tender.participants),
                selectinload(Tender.bids),
            )
            .order_by(Tender.created_at.desc())
        )
        result = await session.execute(stmt)
        closed_tenders = result.scalars().all()

        if not closed_tenders:
            await message.answer("Завершенных тендеров пока нет.", reply_markup=menu_admin)
            return

        # Формируем ответ
        response = "📚 История всех завершенных тендеров:\n\n"
        for tender in closed_tenders:
            from zoneinfo import ZoneInfo
            from datetime import timezone as _tz
            local_tz = ZoneInfo("Europe/Moscow")
            created_local = tender.created_at.astimezone(local_tz) if tender.created_at.tzinfo else tender.created_at.replace(tzinfo=_tz.utc).astimezone(local_tz)
            
            # Получаем информацию об организаторе
            organizer = await session.get(User, tender.organizer_id)
            organizer_name = organizer.org_name if organizer else "Неизвестный организатор"
            
            # Находим победителя (самую низкую ставку)
            winner_info = ""
            if tender.bids:
                winner_bid = min(tender.bids, key=lambda x: x.amount)
                winner = await session.get(User, winner_bid.supplier_id)
                if winner:
                    winner_info = f"🏆 Победитель: {winner.org_name} ({winner_bid.amount:,.0f} ₽)"

            response += (
                f"🔴 <b>{tender.title}</b>\n"
                f"👤 Организатор: {organizer_name}\n"
                f"💰 Стартовая цена: {tender.start_price:,.0f} ₽\n"
                f"💰 Финальная цена: {tender.current_price:,.0f} ₽\n"
                f"📅 Дата начала: {tender.start_at.strftime('%d.%m.%Y %H:%M')}\n"
                f"📅 Создан: {created_local.strftime('%d.%m.%Y %H:%M')}\n"
                f"🏆 Участников: {len(tender.participants)}\n"
                f"📈 Заявок: {len(tender.bids)}\n"
                f"{winner_info}\n\n"
            )

        await message.answer(response, reply_markup=menu_admin)

def register_handlers(dp):
    """Регистрация хендлеров"""
    dp.include_router(router)
