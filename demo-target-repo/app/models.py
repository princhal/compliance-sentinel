from sqlalchemy import Boolean, Column, DateTime, Integer, String, Text
from sqlalchemy.orm import declarative_base
from sqlalchemy_utils import EncryptedType

from app.config import JWT_SECRET

Base = declarative_base()


class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    email = Column(String(320), unique=True, nullable=False)
    phone = Column(String(32))
    password = Column(String(128))
    ssn = Column(String(11))
    passport_number = Column(EncryptedType(String, JWT_SECRET))
    is_deleted = Column(Boolean, default=False)
    marketing_consent = Column(Boolean, default=False)


class PaymentMethod(Base):
    __tablename__ = "payment_methods"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer)
    card_number = Column(String(19))
    expires = Column(String(5))


class Appointment(Base):
    __tablename__ = "appointments"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer)
    starts_at = Column(DateTime)
    diagnosis = Column(Text)
