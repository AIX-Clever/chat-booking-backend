"""
Metrics Module for Dashboard Analytics

Provides low-latency metrics using DynamoDB atomic counters.
Metrics are pre-aggregated by period (day/month) for instant retrieval.

Usage:
    from shared.metrics import MetricsService

    metrics = MetricsService()
    metrics.increment_booking(tenant_id, service_id, provider_id)
    metrics.increment_message(tenant_id)

    dashboard = metrics.get_dashboard_metrics(tenant_id)
"""

import os
import boto3
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, Optional, List
from decimal import Decimal
from boto3.dynamodb.conditions import Key


class MetricsService:
    """
    Service for tracking and retrieving tenant metrics.
    Uses DynamoDB atomic counters for low-latency pre-aggregation.
    """

    def __init__(self, table_name: Optional[str] = None):
        self.dynamodb = boto3.resource("dynamodb")
        self.table_name = table_name or os.environ.get(
            "TENANT_USAGE_TABLE", "ChatBooking-TenantUsage"
        )
        self.table = self.dynamodb.Table(self.table_name)

    def _get_periods(self) -> Dict[str, str]:
        """Get current time periods for aggregation"""
        now = datetime.now(timezone.utc)
        return {
            "month": now.strftime("%Y-%m"),
            "day": now.strftime("%Y-%m-%d"),
            "week": f"{now.year}-W{now.isocalendar()[1]:02d}",
        }

    def _calculate_ttl(self, months: int = 13) -> int:
        """Calculate TTL timestamp (default 13 months for yearly comparison)"""
        future = datetime.now(timezone.utc) + timedelta(days=months * 30)
        return int(future.timestamp())

    def _atomic_increment(
        self,
        tenant_id: str,
        sk: str,
        attribute: str,
        count: int = 1,
        extra_attrs: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Atomically increment a counter in DynamoDB"""
        update_expression = (
            "ADD #attr :inc SET #ttl = if_not_exists(#ttl, :ttl), #updatedAt = :now"
        )
        expression_names = {
            "#attr": attribute,
            "#ttl": "ttl",
            "#updatedAt": "updatedAt",
        }
        expression_values = {
            ":inc": Decimal(count),
            ":ttl": self._calculate_ttl(),
            ":now": datetime.now(timezone.utc).isoformat(),
        }

        # Add extra attributes if provided
        if extra_attrs:
            for key, value in extra_attrs.items():
                update_expression += f", #{key} = if_not_exists(#{key}, :{key})"
                expression_names[f"#{key}"] = key
                expression_values[f":{key}"] = value

        self.table.update_item(
            Key={"PK": f"TENANT#{tenant_id}", "SK": sk},
            UpdateExpression=update_expression,
            ExpressionAttributeNames=expression_names,
            ExpressionAttributeValues=expression_values,
        )

    # ==================== Increment Operations ====================

    def increment_booking(
        self,
        tenant_id: str,
        service_id: str,
        provider_id: str,
        service_name: Optional[str] = None,
        provider_name: Optional[str] = None,
        amount: float = 0,
    ) -> None:
        """
        Track a new booking.
        Increments: monthly total, daily total, service count, provider count.
        """
        periods = self._get_periods()

        # Monthly booking count
        self._atomic_increment(
            tenant_id,
            f"MONTH#{periods['month']}",
            "bookings",
            extra_attrs={"revenue": Decimal(str(amount))} if amount else None,
        )

        # Daily booking count
        self._atomic_increment(tenant_id, f"DAY#{periods['day']}", "bookings")

        # Service popularity (for top services chart)
        self._atomic_increment(
            tenant_id,
            f"SVC#{service_id}#{periods['month']}",
            "bookings",
            extra_attrs={"name": service_name} if service_name else None,
        )

        # Provider popularity (for top providers chart)
        self._atomic_increment(
            tenant_id,
            f"PROV#{provider_id}#{periods['month']}",
            "bookings",
            extra_attrs={"name": provider_name} if provider_name else None,
        )

        # Revenue tracking if amount provided
        if amount > 0:
            self._atomic_increment(
                tenant_id,
                f"MONTH#{periods['month']}",
                "revenue",
                count=0,  # Don't increment, we're using ADD for revenue
            )

    def increment_message(self, tenant_id: str, is_ai_response: bool = False) -> None:
        """Track a chat message"""
        periods = self._get_periods()

        self._atomic_increment(tenant_id, f"MONTH#{periods['month']}", "messages")
        self._atomic_increment(tenant_id, f"DAY#{periods['day']}", "messages")

        if is_ai_response:
            self._atomic_increment(
                tenant_id, f"MONTH#{periods['month']}", "aiResponses"
            )

    def increment_tokens(self, tenant_id: str, token_count: int) -> None:
        """Track AI token usage"""
        periods = self._get_periods()
        self._atomic_increment(
            tenant_id, f"MONTH#{periods['month']}", "tokensIA", count=token_count
        )

    def increment_error(self, tenant_id: str, error_type: str) -> None:
        """Track an error occurrence"""
        periods = self._get_periods()
        self._atomic_increment(
            tenant_id,
            f"ERR#{error_type}#{periods['month']}",
            "count",
            extra_attrs={"lastOccurred": datetime.now(timezone.utc).isoformat()},
        )

    def increment_conversation_completed(self, tenant_id: str) -> None:
        """Track a completed conversation (booking made through chat)"""
        periods = self._get_periods()
        self._atomic_increment(
            tenant_id, f"MONTH#{periods['month']}", "conversionsChat"
        )

    def update_booking_status(
        self, tenant_id: str, old_status: str, new_status: str
    ) -> None:
        """Track booking status changes for the pie chart"""
        periods = self._get_periods()

        # Decrement old status
        if old_status:
            self._atomic_increment(
                tenant_id, f"STATUS#{old_status}#{periods['month']}", "count", count=-1
            )

        # Increment new status
        self._atomic_increment(
            tenant_id, f"STATUS#{new_status}#{periods['month']}", "count"
        )

    # ==================== Query Operations ====================

    def get_dashboard_metrics(self, tenant_id: str) -> Dict[str, Any]:
        """
        Get all dashboard metrics for a tenant.
        Returns data formatted for the dashboard components.
        """
        periods = self._get_periods()
        current_month = periods["month"]

        # Query all metrics for current month
        response = self.table.query(
            KeyConditionExpression=Key("PK").eq(f"TENANT#{tenant_id}")
        )

        items = response.get("Items", [])

        # Process and structure the data
        result = {
            "period": current_month,
            "summary": {
                "revenue": 0,
                "bookings": 0,
                "messages": 0,
                "tokensIA": 0,
                "conversionsChat": 0,
                "aiResponses": 0,
            },
            "daily": [],
            "topServices": [],
            "topProviders": [],
            "bookingStatus": {
                "CONFIRMED": 0,
                "PENDING": 0,
                "CANCELLED": 0,
                "NO_SHOW": 0,
            },
            "errors": [],
        }

        # Sort items into categories
        for item in items:
            sk = item.get("SK", "")

            if sk.startswith(f"MONTH#{current_month}"):
                # Monthly summary
                result["summary"]["revenue"] = float(item.get("revenue", 0))
                result["summary"]["bookings"] = int(item.get("bookings", 0))
                result["summary"]["messages"] = int(item.get("messages", 0))
                result["summary"]["tokensIA"] = int(item.get("tokensIA", 0))
                result["summary"]["conversionsChat"] = int(
                    item.get("conversionsChat", 0)
                )
                result["summary"]["aiResponses"] = int(item.get("aiResponses", 0))

            elif sk.startswith("DAY#") and current_month in sk:
                # Daily data for charts
                day = sk.replace("DAY#", "")
                result["daily"].append(
                    {
                        "date": day,
                        "bookings": int(item.get("bookings", 0)),
                        "messages": int(item.get("messages", 0)),
                    }
                )

            elif sk.startswith("SVC#") and current_month in sk:
                # Top services
                parts = sk.split("#")
                if len(parts) >= 2:
                    result["topServices"].append(
                        {
                            "serviceId": parts[1],
                            "name": item.get("name", "Unknown"),
                            "bookings": int(item.get("bookings", 0)),
                        }
                    )

            elif sk.startswith("PROV#") and current_month in sk:
                # Top providers
                parts = sk.split("#")
                if len(parts) >= 2:
                    result["topProviders"].append(
                        {
                            "providerId": parts[1],
                            "name": item.get("name", "Unknown"),
                            "bookings": int(item.get("bookings", 0)),
                        }
                    )

            elif sk.startswith("STATUS#") and current_month in sk:
                # Booking status counts
                parts = sk.split("#")
                if len(parts) >= 2:
                    status = parts[1]
                    if status in result["bookingStatus"]:
                        result["bookingStatus"][status] = int(item.get("count", 0))

            elif sk.startswith("ERR#") and current_month in sk:
                # Error tracking
                parts = sk.split("#")
                if len(parts) >= 2:
                    result["errors"].append(
                        {
                            "type": parts[1],
                            "count": int(item.get("count", 0)),
                            "lastOccurred": item.get("lastOccurred"),
                        }
                    )

        # Sort top services and providers
        result["topServices"] = sorted(
            result["topServices"], key=lambda x: x["bookings"], reverse=True
        )[:10]

        result["topProviders"] = sorted(
            result["topProviders"], key=lambda x: x["bookings"], reverse=True
        )[:10]

        # Sort daily data
        result["daily"] = sorted(result["daily"], key=lambda x: x["date"])

        # Calculate derived metrics
        total_bookings = sum(result["bookingStatus"].values())
        if total_bookings > 0:
            result["summary"]["conversionRate"] = round(
                (
                    (
                        result["summary"]["conversionsChat"]
                        / result["summary"]["messages"]
                        * 100
                    )
                    if result["summary"]["messages"] > 0
                    else 0
                ),
                1,
            )
            result["summary"]["autoAttendanceRate"] = round(
                (
                    (
                        result["summary"]["aiResponses"]
                        / result["summary"]["messages"]
                        * 100
                    )
                    if result["summary"]["messages"] > 0
                    else 0
                ),
                1,
            )
        else:
            result["summary"]["conversionRate"] = 0
            result["summary"]["autoAttendanceRate"] = 0

        return result

    def get_usage_for_plan_limits(self, tenant_id: str) -> Dict[str, int]:
        """Get current usage for plan limit checking"""
        periods = self._get_periods()

        try:
            response = self.table.get_item(
                Key={"PK": f"TENANT#{tenant_id}", "SK": f"MONTH#{periods['month']}"}
            )

            item = response.get("Item", {})
            return {
                "messages": int(item.get("messages", 0)),
                "bookings": int(item.get("bookings", 0)),
                "tokensIA": int(item.get("tokensIA", 0)),
            }
        except Exception:
            return {"messages": 0, "bookings": 0, "tokensIA": 0}
