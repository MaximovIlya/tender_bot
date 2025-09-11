from __future__ import annotations
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy import String, Integer, BigInteger, Text, ForeignKey, DateTime, Float, Boolean, Enum
from datetime import datetime
import enum


class Base(DeclarativeBase):
    pass


class Role(str, enum.Enum):
    admin = "admin"
    organizer = "organizer"
    supplier = "supplier"


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    username: Mapped[str | None] = mapped_column(String(64), nullable=True)
    role: Mapped[str] = mapped_column(String(16), default=Role.supplier.value)
    banned: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    # supplier fields
    org_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    inn: Mapped[str | None] = mapped_column(String(32), nullable=True)
    ogrn: Mapped[str | None] = mapped_column(String(32), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(32), nullable=True)
    fio: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # relationships
    tenders: Mapped[list["Tender"]] = relationship(back_populates="organizer")
    bids: Mapped[list["Bid"]] = relationship(back_populates="supplier")


class TenderStatus(str, enum.Enum):
    draft = "draft"
    active_pending = "active_pending"
    active = "active"
    closed = "closed"
    cancelled = "cancelled"


class Tender(Base):
    __tablename__ = "tenders"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(Text)
    start_price: Mapped[float] = mapped_column(Float)
    start_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    status: Mapped[str] = mapped_column(String(16), default=TenderStatus.draft.value)
    conditions_path: Mapped[str | None] = mapped_column(String(255), nullable=True)
    organizer_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    
    # auction fields
    last_bid_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    current_price: Mapped[float] = mapped_column(Float)
    min_bid_decrease: Mapped[float] = mapped_column(Float, default=10000.0)  # минимальное снижение цены
    
    # relationships
    organizer: Mapped[User] = relationship(back_populates="tenders")
    bids: Mapped[list["Bid"]] = relationship(back_populates="tender", order_by="Bid.created_at")
    participants: Mapped[list["TenderParticipant"]] = relationship(back_populates="tender")
    access_grants: Mapped[list["TenderAccess"]] = relationship()


class TenderParticipant(Base):
    __tablename__ = "tender_participants"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tender_id: Mapped[int] = mapped_column(ForeignKey("tenders.id"))
    supplier_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    joined_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    
    # relationships
    tender: Mapped[Tender] = relationship(back_populates="participants")
    supplier: Mapped[User] = relationship()


class TenderAccess(Base):
    __tablename__ = "tender_access"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tender_id: Mapped[int] = mapped_column(ForeignKey("tenders.id"))
    supplier_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    granted_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    
    # relationships
    tender: Mapped[Tender] = relationship()
    supplier: Mapped[User] = relationship()


class Bid(Base):
    __tablename__ = "bids"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tender_id: Mapped[int] = mapped_column(ForeignKey("tenders.id"))
    supplier_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    amount: Mapped[float] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    
    # relationships
    tender: Mapped[Tender] = relationship(back_populates="bids")
    supplier: Mapped[User] = relationship(back_populates="bids")