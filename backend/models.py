from datetime import datetime, timezone
from sqlalchemy import String, Integer, Boolean, ForeignKey, JSON, CheckConstraint, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from .database import Base

def now():
    return datetime.now(timezone.utc).isoformat()
class User(Base):
    __tablename__ = 'users'
    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(254), unique=True)
    name: Mapped[str]
    password_hash: Mapped[str]
    role: Mapped[str] = mapped_column(default='cliente')
    phone: Mapped[str] = mapped_column(default='')
    addresses: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[str] = mapped_column(default=now)
class Session(Base):
    __tablename__ = 'sessions'
    token_hash: Mapped[str] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id'))
    expires: Mapped[int]
class Taxonomy(Base):
    __tablename__ = 'taxonomy'
    __table_args__ = (UniqueConstraint('kind', 'name'),)
    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str]
    name: Mapped[str]
class Product(Base):
    __tablename__ = 'products'
    __table_args__ = (CheckConstraint('stock >= 0'), CheckConstraint('price_cents > 0'), CheckConstraint('cost_cents >= 0'))
    id: Mapped[int] = mapped_column(primary_key=True)
    sku: Mapped[str] = mapped_column(unique=True)
    name: Mapped[str]
    description: Mapped[str]
    category: Mapped[str] = mapped_column(index=True)
    brand: Mapped[str] = mapped_column(index=True)
    features: Mapped[dict] = mapped_column(JSON, default=dict)
    image: Mapped[str]
    unit: Mapped[str]
    price_cents: Mapped[int]
    cost_cents: Mapped[int]
    stock: Mapped[int]
    min_stock: Mapped[int] = mapped_column(default=5)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    discount_percent: Mapped[int] = mapped_column(default=0)
    featured: Mapped[bool] = mapped_column(default=False)
class Order(Base):
    __tablename__ = 'orders'
    __table_args__ = (UniqueConstraint('user_id', 'idempotency_key'),)
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id'), index=True)
    idempotency_key: Mapped[str]
    request_hash: Mapped[str]
    created_at: Mapped[str] = mapped_column(default=now, index=True)
    status: Mapped[str] = mapped_column(default='pendiente')
    payment_status: Mapped[str] = mapped_column(default='pendiente')
    delivery: Mapped[str]
    address: Mapped[dict] = mapped_column(JSON)
    customer_name: Mapped[str]
    phone: Mapped[str]
    notes: Mapped[str] = mapped_column(default='')
    subtotal_cents: Mapped[int]
    shipping_cents: Mapped[int]
    total_cents: Mapped[int]
    restored: Mapped[bool] = mapped_column(default=False)
class OrderItem(Base):
    __tablename__ = 'order_items'
    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey('orders.id'), index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey('products.id'))
    sku: Mapped[str]
    name: Mapped[str]
    category: Mapped[str]
    image: Mapped[str]
    quantity: Mapped[int]
    original_price_cents: Mapped[int]
    unit_price_cents: Mapped[int]
    discount_percent: Mapped[int]
    cost_cents: Mapped[int]
class Movement(Base):
    __tablename__ = 'movements'
    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey('products.id'), index=True)
    order_id: Mapped[int | None] = mapped_column(ForeignKey('orders.id'), nullable=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey('users.id'), nullable=True)
    created_at: Mapped[str] = mapped_column(default=now)
    kind: Mapped[str]
    quantity: Mapped[int]
    balance: Mapped[int]
    reason: Mapped[str]
class OrderEvent(Base):
    __tablename__ = 'order_events'
    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey('orders.id'), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id'))
    created_at: Mapped[str] = mapped_column(default=now)
    message: Mapped[str]
class Setting(Base):
    __tablename__ = 'settings'
    key: Mapped[str] = mapped_column(primary_key=True)
    value: Mapped[dict] = mapped_column(JSON)
