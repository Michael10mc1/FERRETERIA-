import re
from typing import Literal
from pydantic import BaseModel, Field, field_validator

class Login(BaseModel):
    email: str = Field(max_length=254)
    password: str = Field(min_length=8, max_length=128)
    @field_validator('email')
    @classmethod
    def email_valid(cls, v):
        v = v.strip().lower()
        if not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', v):
            raise ValueError('Ingresa un correo válido')
        return v
class Register(Login):
    name: str = Field(min_length=2, max_length=100)
class Address(BaseModel):
    label: str = Field(default='Casa', max_length=50)
    street: str = Field(min_length=5, max_length=250)
    district: str = Field(min_length=2, max_length=100)
    city: str = Field(default='Lima', min_length=2, max_length=100)
    reference: str = Field(default='', max_length=250)
class Profile(BaseModel):
    name: str = Field(min_length=2, max_length=100)
    phone: str = Field(default='', max_length=20)
    addresses: list[Address] = Field(default_factory=list, max_length=10)
class ProductInput(BaseModel):
    sku: str = Field(min_length=2, max_length=50, pattern=r'^[A-Za-z0-9_-]+$')
    name: str = Field(min_length=3, max_length=180)
    description: str = Field(min_length=5, max_length=3000)
    category: str = Field(min_length=2, max_length=80)
    brand: str = Field(min_length=2, max_length=80)
    features: dict[str,str] = Field(default_factory=dict)
    image: str = Field(default='/images/fallback.svg', max_length=1000)
    unit: str = Field(min_length=1, max_length=40)
    price_cents: int = Field(gt=0, le=100000000)
    cost_cents: int = Field(ge=0, le=100000000)
    stock: int = Field(ge=0, le=1000000)
    min_stock: int = Field(ge=0, le=1000000)
    active: bool = True
    discount_percent: int = Field(default=0, ge=0, le=90)
    featured: bool = False
    @field_validator('image')
    @classmethod
    def image_valid(cls,v):
        if not (v.startswith('/images/') or v.startswith('https://')):
            raise ValueError('Usa una imagen local o una URL HTTPS')
        return v
class CartItem(BaseModel):
    product_id: int = Field(gt=0)
    quantity: int = Field(gt=0, le=10000)
    expected_price_cents: int = Field(gt=0)
class Checkout(BaseModel):
    items: list[CartItem] = Field(min_length=1, max_length=100)
    idempotency_key: str = Field(min_length=16, max_length=100)
    delivery: Literal['recojo','entrega']
    address: Address | None = None
    customer_name: str = Field(min_length=2, max_length=100)
    phone: str = Field(pattern=r'^\+?[0-9\s-]{7,15}$')
    notes: str = Field(default='', max_length=500)
class MovementInput(BaseModel):
    product_id: int
    kind: Literal['entrada','salida','ajuste']
    quantity: int = Field(ge=0, le=1000000)
    reason: str = Field(min_length=4, max_length=300)
class StatusInput(BaseModel):
    status: Literal['pendiente','confirmado','preparado','enviado','entregado','cancelado']
class PaymentInput(BaseModel):
    payment_status: Literal['pendiente','pagado','reembolsado']
class TaxonomyInput(BaseModel):
    kind: Literal['category','brand']
    name: str = Field(min_length=2, max_length=80)
class StoreInput(BaseModel):
    name: str = Field(min_length=3, max_length=80)
    phone: str = Field(max_length=30)
    email: str = Field(max_length=254)
    address: str = Field(max_length=250)
    hours: str = Field(max_length=150)
    shipping_cents: int = Field(ge=0, le=100000)
