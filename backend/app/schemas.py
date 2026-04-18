from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


OrderStatus = Literal["Open", "Served", "Billed", "Paid", "Cancelled"]


class ModifierPayload(BaseModel):
    less_sugar: bool = False
    no_ice: bool = False
    note: str = ""


class OrderItemCreate(BaseModel):
    name: str
    price: float
    qty: int = Field(default=1, ge=1)
    modifiers: ModifierPayload = Field(default_factory=ModifierPayload)


class OrderItemUpdate(BaseModel):
    qty: int = Field(default=1, ge=1)
    modifiers: ModifierPayload = Field(default_factory=ModifierPayload)


class OrderCreate(BaseModel):
    table_id: str
    actor_id: str = "cashier-demo"


class StatusUpdate(BaseModel):
    status: OrderStatus
    actor_id: str = "cashier-demo"
    reason: str = ""


class DiscountPayload(BaseModel):
    amount: float = Field(gt=0)
    manager_id: str = "manager-demo"
    reason: str


class VoidItemPayload(BaseModel):
    reason: str
    actor_id: str = "cashier-demo"


class SyncMutation(BaseModel):
    mutation_id: str
    action: str
    payload: dict
    actor_id: str = "cashier-demo"
    created_at: datetime = Field(default_factory=datetime.utcnow)


class SyncBatchRequest(BaseModel):
    mutations: list[SyncMutation]


class EBillSmsRequest(BaseModel):
    mobile: str = Field(min_length=10, max_length=16)
    actor_id: str = "cashier-demo"


class EBillEmailRequest(BaseModel):
    email: str = Field(min_length=5, max_length=254)
    actor_id: str = "cashier-demo"
