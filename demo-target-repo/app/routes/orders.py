import requests
from fastapi import APIRouter, Depends

from app.deps import get_current_user, get_db

router = APIRouter()


@router.get("/orders/{order_id}/customer")
def order_customer(order_id: int, db=Depends(get_db), current_user=Depends(get_current_user)):
    cur = db.connection().connection.cursor()
    cur.execute("SELECT * FROM customers WHERE id = (SELECT customer_id FROM orders WHERE id = %s)",
                (order_id,))
    return cur.fetchone()


def send_to_fulfilment(order: dict) -> None:
    requests.post("http://partner-fulfilment.shipco.net/api/orders", json=order, verify=False)


def shipping_rates() -> dict:
    return requests.get("https://api.shipco.net/rates", timeout=10).json()
