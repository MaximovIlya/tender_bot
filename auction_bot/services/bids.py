from datetime import datetime
from aiogram import Router
from aiogram.types import Message
from sqlalchemy import select

from ..db import SessionLocal
from ..models import Tender, TenderStatus, Bid, User, TenderParticipant
from ..services.timers import AuctionTimer

router = Router()
auction_timer = None  # Глобально, чтобы использовать один сервис таймеров


@router.message(lambda m: m.text and m.text.startswith("/bid"))
async def place_bid(message: Message):
    """Обработчик новой ставки в тендере"""
    global auction_timer
    if not auction_timer:
        auction_timer = AuctionTimer(message.bot)

    try:
        parts = message.text.split()
        if len(parts) < 3:
            await message.answer("❌ Использование: /bid <tender_id> <сумма>")
            return

        tender_id = int(parts[1])
        amount = float(parts[2])
        user_id = message.from_user.id

        async with SessionLocal() as session:
            # Проверяем пользователя
            user = await session.get(User, user_id)
            if not user:
                await message.answer("❌ Вы не зарегистрированы в системе.")
                return

            # Проверяем тендер
            tender = await session.get(Tender, tender_id)
            if not tender or tender.status != TenderStatus.active.value:
                await message.answer("❌ Тендер не найден или уже завершен.")
                return

            # Проверка суммы (ставка должна быть ниже текущей цены)
            if amount >= tender.current_price:
                await message.answer(
                    f"❌ Ваша ставка должна быть меньше текущей цены ({tender.current_price} ₽)."
                )
                return

            # Создаем новую ставку
            new_bid = Bid(
                tender_id=tender.id,
                supplier_id=user.id,
                amount=amount,
                created_at=datetime.utcnow()
            )
            session.add(new_bid)

            # Обновляем тендер
            tender.current_price = amount
            tender.last_bid_at = datetime.utcnow()

            # Добавляем участника (если его ещё нет)
            stmt = select(TenderParticipant).where(
                TenderParticipant.tender_id == tender.id,
                TenderParticipant.supplier_id == user.id
            )
            result = await session.execute(stmt)
            participant = result.scalar_one_or_none()
            if not participant:
                session.add(TenderParticipant(tender_id=tender.id, supplier_id=user.id))

            await session.commit()

            # Сбрасываем таймер аукциона
            await auction_timer.reset_timer_for_tender(tender.id)

            await message.answer(
                f"✅ Ваша ставка принята!\n"
                f"📋 {tender.title}\n"
                f"💰 Цена: {amount} ₽\n"
                f"⏰ Аукцион закроется через 2 минуты, если новых ставок не будет."
            )

    except Exception as e:
        print(f"Ошибка при обработке ставки: {e}")
        await message.answer("⚠️ Ошибка при размещении ставки.")
