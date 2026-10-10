import analytics

from app.mailer import marketing_client


def on_signup(user) -> None:
    analytics.track(user.id, "signup", {"email": user.email, "phone": user.phone})


def send_newsletter(user, issue: str) -> None:
    if not user.marketing_consent:
        return
    marketing_client.send(to=user.email, template=issue)


def track_page_view(user, page: str) -> None:
    import requests

    from app.config import ANALYTICS_URL

    requests.post(ANALYTICS_URL, json={"uid": user.id, "email": user.email, "page": page},
                  timeout=5)
