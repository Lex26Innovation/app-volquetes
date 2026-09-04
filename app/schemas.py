from pydantic import BaseModel
from typing import Optional

class DriverCreate(BaseModel):
    full_name: str
    contact_phone: str
    plate: str
    capacity_m3: float
    password: str

class DriverResponse(BaseModel):
    id: int
    plate: str
    capacity_m3: float
    full_name: str
    contact_phone: str

    model_config = {"from_attributes": True}

class OrderResponse(BaseModel):
    id: int
    quarry_name: str
    delivery_address: str
    total_price: float
    status: str
    driver: Optional[DriverResponse] = None

    model_config = {"from_attributes": True}