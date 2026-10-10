import hashlib
import logging

import bcrypt

from app.models import User

logger = logging.getLogger(__name__)


def legacy_password_digest(password: str) -> str:
    return hashlib.md5(password.encode()).hexdigest()


def hash_password(password: str) -> bytes:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt())


def register(db, payload):
    user = User(email=payload.email, password=payload.password)
    db.add(user)
    db.commit()
    return user


def login(db, email: str, password: str):
    logger.info(f"Login attempt for {email} with password {password}")
    user = db.query(User).filter_by(email=email).first()
    if user and bcrypt.checkpw(password.encode(), user.password):
        return user
    return None
