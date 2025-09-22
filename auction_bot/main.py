import asyncio
import logging
from aiogram import Bot, Dispatcher, types
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties

from .config import settings
from .db import init_db, SessionLocal
from .keyboards import *
from sqlalchemy import select
from .routes import admin, organizer, supplier, common, auctions
from .services.timers import AuctionTimer
from .services.reports import ReportService
from .services.activate_pending_tenders import activate_pending_tenders
from .services import bids
from .services import timers
from .routes import organizer

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Инициализация бота и диспетчера
bot = Bot(token=settings.BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

# Инициализация сервисов
auction_timer = timers.AuctionTimer(bot)
organizer.set_timer(auction_timer)
supplier.set_timer(auction_timer)
report_service = ReportService()

# Состояния для регистрации поставщика
class SupplierRegistration(StatesGroup):
    waiting_for_org_name = State()
    waiting_for_inn = State()
    waiting_for_ogrn = State()
    waiting_for_phone = State()
    waiting_for_fio = State()

# Состояния для создания тендера
class TenderCreation(StatesGroup):
    waiting_for_title = State()
    waiting_for_description = State()
    waiting_for_start_price = State()
    waiting_for_start_date = State()
    waiting_for_conditions = State()

# Состояния для участия в аукционе
class AuctionParticipation(StatesGroup):
    waiting_for_bid = State()

@dp.message(Command("start"))
async def cmd_start(message: Message):
    """Начальная команда бота"""
    user_id = message.from_user.id

    async with SessionLocal() as session:
        from .models import User
        stmt = select(User).where(User.telegram_id == user_id)
        result = await session.execute(stmt)
        user = result.scalar_one_or_none()

        
        if not user:
            # Если это админ
            # if user_id in settings.ADMIN_IDS:
            #     user = User(
            #         telegram_id=user_id,
            #         username=message.from_user.username,
            #         role="admin"
            #     )
            #     session.add(user)
            #     await session.commit()
            #     await message.answer("Панель администратора", reply_markup=menu_admin)
            #     return

            # Если это организатор
            if user_id == settings.ORGANIZER_ID:
                user = User(
                    telegram_id=user_id,
                    username=message.from_user.username,
                    role="organizer"
                )
                session.add(user)
                await session.commit()
                await message.answer("Панель организатора", reply_markup=menu_organizer)
                return

            # Все остальные по умолчанию — поставщики
            user = User(
                telegram_id=user_id,
                username=message.from_user.username,
                role="supplier"
            )
            session.add(user)
            await session.commit()


        # Если пользователь заблокирован
        if user.banned:
            await message.answer("Ваш аккаунт заблокирован. Обратитесь к администратору.")
            return

        # Если это организатор
        if user.role == "organizer":
            await message.answer("Панель организатора", reply_markup=menu_organizer)
            return

        # Если это поставщик
        if user.role == "supplier":
            if user.org_name:  # Уже зарегистрирован
                await message.answer("Панель поставщика", reply_markup=menu_supplier_registered)
            else:
                await message.answer(
                    "Для участия в тендерах необходимо зарегистрироваться.\n"
                    "Нажмите кнопку 'Регистрация'",
                    reply_markup=menu_supplier_unregistered
                )




@dp.message(lambda message: message.text == "Регистрация")
async def start_registration(message: Message, state: FSMContext):
    """Начало регистрации поставщика"""
    await state.set_state(SupplierRegistration.waiting_for_org_name)
    await message.answer(
        "Введите наименование вашей организации:",
        reply_markup=types.ReplyKeyboardRemove()
    )

@dp.message(SupplierRegistration.waiting_for_org_name)
async def process_org_name(message: Message, state: FSMContext):
    """Обработка названия организации"""
    await state.update_data(org_name=message.text)
    await state.set_state(SupplierRegistration.waiting_for_inn)
    await message.answer("Введите ИНН организации:")

@dp.message(SupplierRegistration.waiting_for_inn)
async def process_inn(message: Message, state: FSMContext):
    """Обработка ИНН"""
    if not message.text.isdigit() or len(message.text) not in [10, 12]:
        await message.answer("ИНН должен содержать 10 или 12 цифр. Попробуйте снова:")
        return
    
    await state.update_data(inn=message.text)
    await state.set_state(SupplierRegistration.waiting_for_ogrn)
    await message.answer("Введите ОГРН организации:")

@dp.message(SupplierRegistration.waiting_for_ogrn)
async def process_ogrn(message: Message, state: FSMContext):
    """Обработка ОГРН"""
    if not message.text.isdigit() or len(message.text) not in [13, 15]:
        await message.answer("ОГРН должен содержать 13 или 15 цифр. Попробуйте снова:")
        return
    
    await state.update_data(ogrn=message.text)
    await state.set_state(SupplierRegistration.waiting_for_phone)
    await message.answer("Введите контактный телефон:")

@dp.message(SupplierRegistration.waiting_for_phone)
async def process_phone(message: Message, state: FSMContext):
    """Обработка телефона"""
    phone = ''.join(filter(str.isdigit, message.text))
    if len(phone) < 10:
        await message.answer("Введите корректный номер телефона:")
        return
    
    await state.update_data(phone=phone)
    await state.set_state(SupplierRegistration.waiting_for_fio)
    await message.answer("Введите ФИО участника:")

@dp.message(SupplierRegistration.waiting_for_fio)
async def process_fio(message: Message, state: FSMContext):
    """Завершение регистрации"""
    user_data = await state.get_data()
    user_data['fio'] = message.text
    
    user_id = message.from_user.id
    
    async with SessionLocal() as session:
        from .models import User
        stmt = select(User).where(User.telegram_id == user_id)
        result = await session.execute(stmt)
        user = result.scalar_one_or_none()
        
        if user:
            user.org_name = user_data['org_name']
            user.inn = user_data['inn']
            user.ogrn = user_data['ogrn']
            user.phone = user_data['phone']
            user.fio = user_data['fio']
            
            await session.commit()
            
            await message.answer(
                f"✅ Регистрация завершена!\n\n"
                f"Организация: {user_data['org_name']}\n"
                f"ИНН: {user_data['inn']}\n"
                f"ОГРН: {user_data['ogrn']}\n"
                f"Телефон: {user_data['phone']}\n"
                f"ФИО: {user_data['fio']}\n\n"
                f"Теперь вы можете участвовать в тендерах!",
                reply_markup=menu_supplier_registered
            )
        else:
            await message.answer("Ошибка при регистрации. Попробуйте снова.")
    
    await state.clear()



def register_handlers(dp: Dispatcher):
    """Регистрация всех хендлеров"""
    admin.register_handlers(dp)
    organizer.register_handlers(dp)
    supplier.register_handlers(dp)
    common.register_handlers(dp)
    auctions.register_handlers(dp)
    dp.include_router(bids.router)

async def main():
    """Главная функция"""
    # Инициализация базы данных
    await init_db()
    
    

    register_handlers(dp)

    asyncio.create_task(activate_pending_tenders())
    
    # Запуск бота
    logger.info("Бот запущен")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
    

