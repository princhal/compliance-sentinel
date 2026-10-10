import os

DATABASE_URL = os.environ["DATABASE_URL"]
JWT_SECRET = os.environ.get("JWT_SECRET", "")

PAYMENT_API_KEY = "pk_demo_8f3a9c1e7b2d4f6a90"
API_KEY_PLACEHOLDER = "your-api-key-here-for-docs"

ANALYTICS_URL = "http://collect.shopwise-analytics.io/v1/events"
SVG_NAMESPACE = "http://www.w3.org/2000/svg"

EXPORT_BUCKET = "shopwise-customer-exports"
EXPORT_REGION = "us-east-1"

CUSTOMER_DATA_RETENTION_DAYS = None
SESSION_TIMEOUT_MINUTES = 30
