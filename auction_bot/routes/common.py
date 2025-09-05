import asyncio
from datetime import datetime
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import Command
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import SessionLocal
from ..models import User, Tender, TenderStatus, TenderParticipant
from ..keyboards import menu_main

router = Router()

@router.message(Command("help"))
async def show_help(message: Message):
    """Показать справку"""
    help_text = (
        "🤖 <b>Справка по боту</b>\n\n"
        "📋 <b>Основные команды:</b>\n"
        "• /start - Запуск бота\n"
        "• /help - Показать эту справку\n"
        "• /profile - Ваш профиль\n"
        "• /tenders - Список тендеров\n\n"
        
        "🎯 <b>Для организаторов:</b>\n"
        "• Создание тендеров\n"
        "• Управление аукционами\n"
        "• Просмотр результатов\n\n"
        
        "🏢 <b>Для поставщиков:</b>\n"
        "• Регистрация организации\n"
        "• Участие в тендерах\n"
        "• Подача заявок\n\n"
        
        "👑 <b>Для администраторов:</b>\n"
        "• Управление пользователями\n"
        "• Мониторинг системы\n"
        "• Назначение ролей\n\n"
        
        "📞 <b>Поддержка:</b>\n"
        "По всем вопросам обращайтесь к администратору."
    )
    
    await message.answer(help_text)

@router.message(Command("profile"))
async def show_profile(message: Message):
    """Показать профиль пользователя"""
    user_id = message.from_user.id
    
    async with SessionLocal() as session:
        user = await session.get(User, user_id)
        if not user:
            await message.answer("Профиль не найден.")
            return
        
        role_names = {
            "admin": "👑 Администратор",
            "organizer": "🎯 Организатор",
            "supplier": "🏢 Поставщик"
        }
        
        profile_text = f"👤 <b>Ваш профиль</b>\n\n"
        profile_text += f"🆔 Telegram ID: {user.telegram_id}\n"
        profile_text += f"👤 Username: @{user.username or 'Не указан'}\n"
        profile_text += f"🎭 Роль: {role_names.get(user.role, 'Неизвестно')}\n"
        profile_text += f"📅 Дата регистрации: {user.created_at.strftime('%d.%m.%Y')}\n"
        profile_text += f"📊 Статус: {'🚫 Заблокирован' if user.banned else '✅ Активен'}\n"
        
        if user.org_name:
            profile_text += f"\n🏢 <b>Данные организации:</b>\n"
            profile_text += f"Название: {user.org_name}\n"
            profile_text += f"ИНН: {user.inn}\n"
            profile_text += f"ОГРН: {user.ogrn}\n"
            profile_text += f"Телефон: {user.phone}\n"
            profile_text += f"ФИО: {user.fio}\n"
        
        # Статистика
        if user.role == "organizer":
            stmt = select(Tender).where(Tender.organizer_id == user.id)
            result = await session.execute(stmt)
            tenders = result.scalars().all()
            profile_text += f"\n📋 <b>Ваши тендеры:</b> {len(tenders)}\n"
        
        elif user.role == "supplier":
            stmt = select(Tender).join(TenderParticipant).where(TenderParticipant.supplier_id == user.id)
            result = await session.execute(stmt)
            participated_tenders = result.scalars().all()
            profile_text += f"\n🏆 <b>Участие в тендерах:</b> {len(participated_tenders)}\n"
        
        await message.answer(profile_text)

@router.message(Command("tenders"))
async def show_tenders(message: Message):
    """Показать список тендеров"""
    async with SessionLocal() as session:
        # Получаем все тендеры
        stmt = select(Tender).order_by(Tender.created_at.desc())
        result = await session.execute(stmt)
        tenders = result.scalars().all()
        
        if not tenders:
            await message.answer("Тендеров пока нет.")
            return
        
        response = "📋 <b>Список тендеров:</b>\n\n"
        for tender in tenders:
            status_emoji = {
                "draft": "📝",
                "active": "🟢",
                "closed": "🔴",
                "cancelled": "❌"
            }
            
            status_name = {
                "draft": "Черновик",
                "active": "Активен",
                "closed": "Завершен",
                "cancelled": "Отменен"
            }
            
            response += (
                f"{status_emoji.get(tender.status, '❓')} <b>{tender.title}</b>\n"
                f"💰 Цена: {tender.current_price} ₽\n"
                f"📅 Дата: {tender.start_at.strftime('%d.%m.%Y %H:%M') if tender.start_at else 'Не указана'}\n"
                f"📊 Статус: {status_name.get(tender.status, tender.status)}\n"
                f"🏆 Участников: {len(tender.participants)}\n"
                f"📈 Заявок: {len(tender.bids)}\n\n"
            )
        
        await message.answer(response)

@router.message(Command("about"))
async def show_about(message: Message):
    """Информация о боте"""
    about_text = (
        "🏛️ <b>Система аукционов на понижение цены</b>\n\n"
        "🤖 <b>Описание:</b>\n"
        "Бот предназначен для проведения электронных аукционов между поставщиками "
        "с автоматическим снижением цены. Система обеспечивает прозрачность и "
        "эффективность закупочных процедур.\n\n"
        
        "🎯 <b>Основные возможности:</b>\n"
        "• Создание и управление тендерами\n"
        "• Аукционы на понижение цены\n"
        "• Анонимное участие поставщиков\n"
        "• Автоматическое завершение торгов\n"
        "• Генерация детальных отчетов\n"
        "• Управление пользователями и ролями\n\n"
        
        "⚡ <b>Принцип работы:</b>\n"
        "1. Организатор создает тендер\n"
        "2. Поставщики присоединяются к аукциону\n"
        "3. Участники подают заявки на снижение цены\n"
        "4. Торги автоматически завершаются через 5 минут\n"
        "5. Побеждает наименьшая цена\n\n"
        
        "📱 <b>Версия:</b> 1.0.0\n"
        "🔧 <b>Разработчик:</b> AI Assistant\n"
        "📅 <b>Дата:</b> 2024"
    )
    
    await message.answer(about_text)

@router.message(Command("rules"))
async def show_rules(message: Message):
    """Правила участия в аукционах"""
    rules_text = (
        "📜 <b>Правила участия в аукционах</b>\n\n"
        "🎯 <b>Общие положения:</b>\n"
        "• Участие в аукционах бесплатное\n"
        "• Все участники равны в правах\n"
        "• Аукционы проводятся на понижение цены\n\n"
        
        "⏰ <b>Временные ограничения:</b>\n"
        "• Торги прекращаются через 5 минут после последней заявки\n"
        "• Время подачи заявок ограничено\n"
        "• Аукцион автоматически завершается по истечении времени\n\n"
        
        "💰 <b>Правила ценообразования:</b>\n"
        "• Каждая новая заявка должна быть ниже предыдущей\n"
        "• Минимальное снижение: 10000.00 ₽\n"
        "• Побеждает наименьшая цена\n\n"
        
        "👥 <b>Анонимность:</b>\n"
        "• Участники видят друг друга как 'Участник 1', 'Участник 2' и т.д.\n"
        "• Реальные названия организаций скрыты до завершения\n"
        "• В отчете все участники расшифровываются\n\n"
        
        "🏆 <b>Определение победителя:</b>\n"
        "• Победителем становится участник с наименьшей ценой\n"
        "• При равных ценах побеждает тот, кто подал заявку раньше\n"
        "• Организатор связывается с победителем\n\n"
        
        "⚠️ <b>Запрещено:</b>\n"
        "• Подача заявок выше текущей цены\n"
        "• Использование нескольких аккаунтов\n"
        "• Нарушение временных ограничений\n"
        "• Любые формы сговора между участниками"
    )
    
    await message.answer(rules_text)

@router.message(lambda message: message.text == "Главное меню")
async def back_to_main_menu(message: Message):
    """Возврат в главное меню"""
    await message.answer(
        "🏠 Главное меню\n\n"
        "Выберите ваш статус:",
        reply_markup=menu_main
    )

def register_handlers(dp):
    """Регистрация хендлеров"""
    dp.include_router(router)
