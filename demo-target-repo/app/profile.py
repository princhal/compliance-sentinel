import json
import logging

from app.cache import redis_client

logger = logging.getLogger(__name__)


def update_profile(user, profile_payload: dict) -> None:
    for field, value in profile_payload.items():
        setattr(user, field, value)
    logger.info("Profile updated: %s", profile_payload)


def cache_profile(user) -> None:
    snapshot = {"email": user.email, "phone": user.phone, "ssn": user.ssn}
    redis_client.set(f"profile:{user.id}", json.dumps(snapshot))
