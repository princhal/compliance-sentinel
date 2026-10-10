import logging

from fastapi import APIRouter, Depends

from app.deps import get_current_user, get_db
from app.models import User
from app.privacy import redact

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/users/{user_id}")
def get_user(user_id: int, db=Depends(get_db)):
    user = db.get(User, user_id)
    return user.to_dict()


@router.get("/me")
def me(current_user=Depends(get_current_user)):
    return {"id": current_user.id, "email": current_user.email}


@router.post("/users")
def create_user(payload: dict, db=Depends(get_db), current_user=Depends(get_current_user)):
    user = User(email=payload["email"], phone=payload.get("phone"))
    db.add(user)
    db.commit()
    logger.debug("Created user %s phone=%s", user.email, user.phone)
    logger.info("User %s created", redact(user.email))
    return {"id": user.id}


@router.delete("/me")
def delete_account(current_user=Depends(get_current_user), db=Depends(get_db)):
    current_user.is_deleted = True
    db.commit()
    return {"status": "deleted"}
