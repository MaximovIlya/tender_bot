import asyncio
from datetime import datetime
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardRemove
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.filters import Command
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import SessionLocal
from ..models import User, Tender, TenderStatus, Role
from ..keyboards import menu_admin
from ..config import settings

router = Router()

# Состояния для назначения ролей
class RoleAssignment(StatesGroup):
    waiting_for_user_id = State()
    waiting_for_role = State()

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
            
            response += (
                f"{role_emoji.get(user.role, '❓')} <b>ID: {user.telegram_id}</b>\n"
                f"👤 Username: @{user.username or 'Нет'}\n"
                f"🎭 Роль: {user.role}\n"
                f"📊 Статус: {status}\n"
                f"📝 Регистрация: {registration}\n"
                f"📅 Создан: {user.created_at.strftime('%d.%m.%Y')}\n"
            )
            
            if user.org_name:
                response += f"🏢 Организация: {user.org_name}\n"
            
            response += "\n"
        
        # Создаем клавиатуру для управления
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Назначить роль", callback_data="assign_role")],
            [InlineKeyboardButton(text="Заблокировать/Разблокировать", callback_data="toggle_ban")],
            [InlineKeyboardButton(text="Статистика", callback_data="show_stats")]
        ])
        
        await message.answer(response, reply_markup=keyboard)

@router.message(lambda message: message.text == "Назначить роль")
async def start_role_assignment(message: Message, state: FSMContext):
    """Начало назначения роли"""
    user_id = message.from_user.id
    
    if user_id not in settings.ADMIN_IDS:
        await message.answer("У вас нет прав администратора.")
        return
    
    await state.set_state(RoleAssignment.waiting_for_user_id)
    await message.answer(
        "Введите Telegram ID пользователя, которому хотите назначить роль:",
        reply_markup=ReplyKeyboardRemove()
    )

@router.message(RoleAssignment.waiting_for_user_id)
async def process_user_id(message: Message, state: FSMContext):
    """Обработка ID пользователя"""
    try:
        telegram_id = int(message.text)
        await state.update_data(telegram_id=telegram_id)
        await state.set_state(RoleAssignment.waiting_for_role)
        
        # Создаем клавиатуру для выбора роли
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Поставщик", callback_data="role_supplier")],
            [InlineKeyboardButton(text="Организатор", callback_data="role_organizer")],
            [InlineKeyboardButton(text="Администратор", callback_data="role_admin")]
        ])
        
        await message.answer(
            f"Выберите роль для пользователя {telegram_id}:",
            reply_markup=keyboard
        )
    except ValueError:
        await message.answer("Введите корректный ID (число). Попробуйте снова:")

@router.callback_query(lambda c: c.data.startswith("role_"))
async def assign_role(callback: CallbackQuery, state: FSMContext):
    """Назначение роли"""
    role = callback.data.split("_")[1]
    user_data = await state.get_data()
    telegram_id = user_data['telegram_id']
    
    async with SessionLocal() as session:
        # Ищем пользователя
        stmt = select(User).where(User.telegram_id == telegram_id)
        result = await session.execute(stmt)
        user = result.scalar_one_or_none()
        
        if not user:
            await callback.answer("Пользователь не найден.")
            return
        
        # Назначаем роль
        old_role = user.role
        user.role = role
        await session.commit()
        
        await callback.message.edit_text(
            f"✅ Роль успешно изменена!\n\n"
            f"👤 Пользователь: {telegram_id}\n"
            f"🎭 Старая роль: {old_role}\n"
            f"🎭 Новая роль: {role}"
        )
        
        # Уведомляем пользователя
        try:
            await callback.bot.send_message(
                telegram_id,
                f"🎉 Вам назначена роль: <b>{role}</b>\n\n"
                f"Теперь у вас есть доступ к соответствующим функциям бота."
            )
        except Exception as e:
            print(f"Ошибка отправки уведомления: {e}")
    
    await state.clear()

@router.callback_query(lambda c: c.data == "toggle_ban")
async def toggle_user_ban(callback: CallbackQuery):
    """Переключение блокировки пользователя"""
    user_id = callback.from_user.id
    
    if user_id not in settings.ADMIN_IDS:
        await callback.answer("У вас нет прав администратора.")
        return
    
    await callback.message.answer(
        "Введите Telegram ID пользователя для блокировки/разблокировки:"
    )

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
            f"📅 Дата: {datetime.now().strftime('%d.%m.%Y %H:%M')}"
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
    
    info_text = (
        "🔧 Информация о системе\n\n"
        f"🤖 Версия бота: 1.0.0\n"
        f"📅 Дата запуска: {datetime.now().strftime('%d.%m.%Y %H:%M')}\n"
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

def register_handlers(dp):
    """Регистрация хендлеров"""
    dp.include_router(router)
