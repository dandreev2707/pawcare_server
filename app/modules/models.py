from sqlalchemy import Column, String, Boolean, DateTime, Float, Text, ForeignKey, Enum
from sqlalchemy.orm import relationship
from sqlalchemy.dialects.postgresql import UUID
from datetime import datetime
import uuid
import enum
from app.database import Base

class User(Base):
    __tablename__ = "users"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email = Column(String, unique=True, nullable=False, index=True)
    name = Column(String, nullable=False)
    password_hash = Column(String, nullable=False)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    pets = relationship("Pet", back_populates="owner")


class Pet(Base):
    __tablename__ = "pets"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    owner_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    name = Column(String, nullable=False)
    breed = Column(String)
    birth_date = Column(String)
    sex = Column(String)
    is_deleted = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    owner = relationship("User", back_populates="pets")
    health_records = relationship("HealthRecord", back_populates="pet")
    weight_logs = relationship("WeightLog", back_populates="pet")


class HealthRecord(Base):
    __tablename__ = "health_records"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    pet_id = Column(UUID(as_uuid=True), ForeignKey("pets.id"), nullable=False)
    record_type = Column(String, nullable=False)
    title = Column(String, nullable=False)
    description = Column(Text)
    record_date = Column(String, nullable=False)
    next_date = Column(String)
    created_at = Column(DateTime, default=datetime.utcnow)

    pet = relationship("Pet", back_populates="health_records")


class WeightLog(Base):
    __tablename__ = "weight_logs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    pet_id = Column(UUID(as_uuid=True), ForeignKey("pets.id"), nullable=False)
    weight_kg = Column(Float, nullable=False)
    measured_at = Column(DateTime, default=datetime.utcnow)

    pet = relationship("Pet", back_populates="weight_logs")