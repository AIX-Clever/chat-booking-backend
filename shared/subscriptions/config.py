import os


class SubscriptionConfig:
    """Subscription Configuration Constants"""

    # DynamoDB Table Name (from env or default)
    SUBSCRIPTIONS_TABLE = os.environ.get(
        "SUBSCRIPTIONS_TABLE", "ChatBooking-Subscriptions"
    )

    # Promotion Settings
    PROMO_PRICE = 1000
    PROMO_DURATION_MONTHS = 3

    # Plan Prices (CLP)
    PLAN_PRICES = {"lite": 15000, "pro": 29990, "business": 89990}
