import os


class SubscriptionConfig:
    """Subscription Configuration Constants"""

    # DynamoDB Table Name (from env or default)
    SUBSCRIPTIONS_TABLE = os.environ.get(
        "SUBSCRIPTIONS_TABLE", "ChatBooking-Subscriptions"
    )

    # Promotion Settings
    PROMO_PRICE = 1000
    PROMO_DURATION_MONTHS = 1

    # Plan Prices (CLP)
    PLAN_PRICES = {"lite": 9990, "pro": 29990, "business": 89990}

    # WhatsApp Prepaid Packages (CLP)
    WHATSAPP_PACKAGES = {
        "starter":  {"messages": 100, "price": 9990},
        "standard": {"messages": 300, "price": 24990},
        "pro":      {"messages": 600, "price": 39990},
    }
