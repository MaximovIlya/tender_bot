import asyncio
from datetime import datetime
from typing import List, Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import SessionLocal
from ..models import Tender, Bid, User, TenderParticipant

class ReportService:
    """Сервис для генерации отчетов по аукционам"""
    
    async def generate_tender_report(self, tender_id: int) -> str:
        """Генерация отчета по конкретному тендеру"""
        async with SessionLocal() as session:
            tender = await session.get(Tender, tender_id)
            if not tender:
                return "Тендер не найден."
            
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
            report_text += f"📈 Количество заявок: {len(bids)}\n"
            report_text += f"📊 Статус: {tender.status}\n\n"
            
            if bids:
                report_text += "📈 ХОД ТОРГОВ:\n\n"
                
                # Группируем заявки по участникам для анонимности
                participant_map = {}
                for i, participant in enumerate(participants):
                    participant_map[participant.supplier_id] = f"Участник {i+1}"
                
                for i, bid in enumerate(bids):
                    participant_name = participant_map.get(bid.supplier_id, "Неизвестно")
                    from zoneinfo import ZoneInfo
                    from datetime import timezone as _tz
                    local_tz = ZoneInfo("Europe/Moscow")
                    bid_time_local = bid.created_at.astimezone(local_tz) if bid.created_at.tzinfo else bid.created_at.replace(tzinfo=_tz.utc).astimezone(local_tz)
                    report_text += (
                        f"{i+1}. {participant_name}\n"
                        f"   💰 Цена: {bid.amount} ₽\n"
                        f"   📅 Время: {bid_time_local.strftime('%H:%M:%S')}\n\n"
                    )
                
                # Победитель
                winner_bid = min(bids, key=lambda x: x.amount)
                winner = await session.get(User, winner_bid.supplier_id)
                from zoneinfo import ZoneInfo
                from datetime import timezone as _tz
                local_tz = ZoneInfo("Europe/Moscow")
                winner_time_local = winner_bid.created_at.astimezone(local_tz) if winner_bid.created_at.tzinfo else winner_bid.created_at.replace(tzinfo=_tz.utc).astimezone(local_tz)
                report_text += (
                    f"🏆 :\n"
                    f"👤 Организация: {winner.org_name}\n"
                    f"💰 Цена: {winner_bid.amount} ₽\n"
                    f"📅 Время подачи: {winner_time_local.strftime('%H:%M:%S')}\n"
                    f"📉 Экономия: {tender.start_price - winner_bid.amount} ₽"
                )
            else:
                report_text += "📊 Заявок не было подано."
            
            return report_text
    
    async def generate_detailed_report(self, tender_id: int) -> str:
        """Генерация детального отчета с расшифровкой участников"""
        async with SessionLocal() as session:
            tender = await session.get(Tender, tender_id)
            if not tender:
                return "Тендер не найден."
            
            # Получаем все заявки
            stmt = select(Bid).where(Bid.tender_id == tender_id).order_by(Bid.created_at)
            result = await session.execute(stmt)
            bids = result.scalars().all()
            
            # Получаем участников
            stmt = select(TenderParticipant).where(TenderParticipant.tender_id == tender_id)
            result = await session.execute(stmt)
            participants = result.scalars().all()
            
            # Создаем детальный отчет
            report_text = f"📊 ДЕТАЛЬНЫЙ ОТЧЕТ ПО АУКЦИОНУ\n\n"
            report_text += f"📋 Название: {tender.title}\n"
            report_text += f"📝 Описание: {tender.description}\n"
            report_text += f"💰 Стартовая цена: {tender.start_price} ₽\n"
            report_text += f"📅 Дата начала: {tender.start_at.strftime('%d.%m.%Y %H:%M')}\n"
            report_text += f"🏆 Количество участников: {len(participants)}\n"
            report_text += f"📈 Количество заявок: {len(bids)}\n"
            report_text += f"📊 Статус: {tender.status}\n\n"
            
            # Список участников
            report_text += "👥 УЧАСТНИКИ АУКЦИОНА:\n\n"
            for i, participant in enumerate(participants):
                supplier = await session.get(User, participant.supplier_id)
                if supplier:
                    report_text += (
                        f"{i+1}. {supplier.org_name}\n"
                        f"   📧 ИНН: {supplier.inn}\n"
                        f"   📋 ОГРН: {supplier.ogrn}\n"
                        f"   📞 Телефон: {supplier.phone}\n"
                        f"   👤 ФИО: {supplier.fio}\n\n"
                    )
            
            if bids:
                report_text += "📈 ХОД ТОРГОВ:\n\n"
                
                # Группируем заявки по участникам
                participant_map = {}
                for i, participant in enumerate(participants):
                    participant_map[participant.supplier_id] = f"Участник {i+1}"
                
                for i, bid in enumerate(bids):
                    participant_name = participant_map.get(bid.supplier_id, "Неизвестно")
                    supplier = await session.get(User, bid.supplier_id)
                    report_text += (
                        f"{i+1}. {participant_name} ({supplier.org_name if supplier else 'Неизвестно'})\n"
                        f"   💰 Цена: {bid.amount} ₽\n"
                        f"   📅 Время: {bid.created_at.strftime('%H:%M:%S')}\n\n"
                    )
                
                # 
                winner_bid = min(bids, key=lambda x: x.amount)
                winner = await session.get(User, winner_bid.supplier_id)
                report_text += (
                    f"🏆 :\n"
                    f"👤 Организация: {winner.org_name}\n"
                    f"💰 Цена: {winner_bid.amount} ₽\n"
                    f"📅 Время подачи: {winner_bid.created_at.strftime('%H:%M:%S')}\n"
                    f"📉 Экономия: {tender.start_price - winner_bid.amount} ₽\n"
                    f"📧 ИНН: {winner.inn}\n"
                    f"📋 ОГРН: {winner.ogrn}\n"
                    f"📞 Телефон: {winner.phone}\n"
                    f"👤 ФИО: {winner.fio}"
                )
            else:
                report_text += "📊 Заявок не было подано."
            
            return report_text
    
    async def generate_system_report(self) -> str:
        """Генерация общего отчета по системе"""
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
            cancelled_tenders = len([t for t in tenders if t.status == "cancelled"])
            
            # Статистика заявок
            stmt = select(Bid)
            result = await session.execute(stmt)
            bids = result.scalars().all()
            
            total_bids = len(bids)
            if bids:
                avg_bid = sum(bid.amount for bid in bids) / len(bids)
                min_bid = min(bid.amount for bid in bids)
                max_bid = max(bid.amount for bid in bids)
            else:
                avg_bid = min_bid = max_bid = 0
            
            report_text = (
                "📊 ОТЧЕТ ПО СИСТЕМЕ АУКЦИОНОВ\n\n"
                f"📅 Дата генерации: {datetime.now().strftime('%d.%m.%Y %H:%M')}\n\n"
                
                "👥 ПОЛЬЗОВАТЕЛИ:\n"
                f"   • Всего: {total_users}\n"
                f"   • Поставщики: {suppliers}\n"
                f"   • Организаторы: {organizers}\n"
                f"   • Администраторы: {admins}\n"
                f"   • Заблокированы: {banned_users}\n"
                f"   • Зарегистрированы: {registered_suppliers}\n\n"
                
                "📋 ТЕНДЕРЫ:\n"
                f"   • Всего: {total_tenders}\n"
                f"   • Черновики: {draft_tenders}\n"
                f"   • Активные: {active_tenders}\n"
                f"   • Завершенные: {closed_tenders}\n"
                f"   • Отмененные: {cancelled_tenders}\n\n"
                
                "📈 ЗАЯВКИ:\n"
                f"   • Всего: {total_bids}\n"
                f"   • Средняя цена: {avg_bid:.2f} ₽\n"
                f"   • Минимальная цена: {min_bid} ₽\n"
                f"   • Максимальная цена: {max_bid} ₽\n\n"
                
                "📊 АКТИВНОСТЬ:\n"
                f"   • Поставщиков на тендер: {total_tenders / max(suppliers, 1):.1f}\n"
                f"   • Заявок на тендер: {total_bids / max(total_tenders, 1):.1f}\n"
                f"   • Заявок на поставщика: {total_bids / max(registered_suppliers, 1):.1f}"
            )
            
            return report_text
    
    async def generate_user_report(self, user_id: int) -> str:
        """Генерация отчета по конкретному пользователю"""
        async with SessionLocal() as session:
            user = await session.get(User, user_id)
            if not user:
                return "Пользователь не найден."
            
            # Статистика тендеров пользователя
            if user.role == "organizer":
                stmt = select(Tender).where(Tender.organizer_id == user.id)
                result = await session.execute(stmt)
                user_tenders = result.scalars().all()
                
                report_text = f"👤 ОТЧЕТ ПО ПОЛЬЗОВАТЕЛЮ\n\n"
                report_text += f"🆔 Telegram ID: {user.telegram_id}\n"
                report_text += f"👤 Username: @{user.username or 'Не указан'}\n"
                report_text += f"🎭 Роль: {user.role}\n"
                report_text += f"📅 Дата регистрации: {user.created_at.strftime('%d.%m.%Y')}\n\n"
                
                report_text += f"📋 ТЕНДЕРЫ ОРГАНИЗАТОРА:\n"
                report_text += f"   • Всего: {len(user_tenders)}\n"
                
                if user_tenders:
                    draft_count = len([t for t in user_tenders if t.status == "draft"])
                    active_count = len([t for t in user_tenders if t.status == "active"])
                    closed_count = len([t for t in user_tenders if t.status == "closed"])
                    
                    report_text += f"   • Черновики: {draft_count}\n"
                    report_text += f"   • Активные: {active_count}\n"
                    report_text += f"   • Завершенные: {closed_count}\n\n"
                    
                    # Детали по тендерам
                    for tender in user_tenders:
                        report_text += (
                            f"📋 {tender.title}\n"
                            f"   💰 Цена: {tender.current_price} ₽\n"
                            f"   📊 Статус: {tender.status}\n"
                            f"   🏆 Участников: {len(tender.participants)}\n"
                            f"   📈 Заявок: {len(tender.bids)}\n\n"
                        )
                else:
                    report_text += "   • Тендеров нет\n"
            
            elif user.role == "supplier":
                # Получаем тендеры, в которых участвовал поставщик
                stmt = select(TenderParticipant).where(TenderParticipant.supplier_id == user.id)
                result = await session.execute(stmt)
                participations = result.scalars().all()
                
                report_text = f"👤 ОТЧЕТ ПО ПОЛЬЗОВАТЕЛЮ\n\n"
                report_text += f"🆔 Telegram ID: {user.telegram_id}\n"
                report_text += f"👤 Username: @{user.username or 'Не указан'}\n"
                report_text += f"🎭 Роль: {user.role}\n"
                report_text += f"🏢 Организация: {user.org_name}\n"
                report_text += f"📅 Дата регистрации: {user.created_at.strftime('%d.%m.%Y')}\n\n"
                
                report_text += f"🏆 УЧАСТИЕ В ТЕНДЕРАХ:\n"
                report_text += f"   • Всего участий: {len(participations)}\n"
                
                if participations:
                    # Получаем заявки пользователя
                    stmt = select(Bid).where(Bid.supplier_id == user.id)
                    result = await session.execute(stmt)
                    user_bids = result.scalars().all()
                    
                    report_text += f"   • Всего заявок: {len(user_bids)}\n"
                    
                    if user_bids:
                        avg_bid = sum(bid.amount for bid in user_bids) / len(user_bids)
                        min_bid = min(bid.amount for bid in user_bids)
                        report_text += f"   • Средняя цена: {avg_bid:.2f} ₽\n"
                        report_text += f"   • Минимальная цена: {min_bid} ₽\n"
                    
                    report_text += "\n📋 ДЕТАЛИ УЧАСТИЯ:\n"
                    for participation in participations:
                        tender = await session.get(Tender, participation.tender_id)
                        if tender:
                            report_text += (
                                f"📋 {tender.title}\n"
                                f"   💰 Текущая цена: {tender.current_price} ₽\n"
                                f"   📊 Статус: {tender.status}\n"
                                f"   📅 Дата участия: {participation.joined_at.strftime('%d.%m.%Y')}\n\n"
                            )
                else:
                    report_text += "   • Участий нет\n"
            
            else:
                report_text = f"👤 ОТЧЕТ ПО ПОЛЬЗОВАТЕЛЮ\n\n"
                report_text += f"🆔 Telegram ID: {user.telegram_id}\n"
                report_text += f"👤 Username: @{user.username or 'Не указан'}\n"
                report_text += f"🎭 Роль: {user.role}\n"
                report_text += f"📅 Дата регистрации: {user.created_at.strftime('%d.%m.%Y')}\n\n"
                report_text += "Для данной роли детальная статистика не доступна."
            
            return report_text
