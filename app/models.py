from sqlalchemy import Column, Integer, String, Float, ForeignKey
from sqlalchemy.orm import relationship
from .database import Base

class Driver(Base):
    __tablename__ = "drivers"

    id = Column(Integer, primary_key=True, index=True)
    full_name = Column(String, nullable=False)
    contact_phone = Column(String, unique=True, index=True, nullable=False)
    plate = Column(String, nullable=False)
    capacity_m3 = Column(Float, nullable=False)
    hashed_password = Column(String, nullable=False)

    orders = relationship("Order", back_populates="driver")

class Order(Base):
    __tablename__ = "orders"

    id = Column(Integer, primary_key=True, index=True)
    quarry_name = Column(String, nullable=False)
    delivery_address = Column(String, nullable=False)
    total_price = Column(Float, nullable=False)
    status = Column(String, default="pending_payment")

    origin_lat = Column(Float, default=-16.3533)
    origin_lng = Column(Float, default=-71.5831)
    dest_lat = Column(Float, default=-16.3683)
    dest_lng = Column(Float, default=-71.5458)

    driver_id = Column(Integer, ForeignKey("drivers.id"), nullable=True)
    driver = relationship("Driver", back_populates="orders")