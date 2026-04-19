import boto3
import os
from typing import List, Optional
from datetime import datetime
from boto3.dynamodb.conditions import Key
from botocore.exceptions import ClientError
from decimal import Decimal

from ..domain.entities import Category, TenantId
from ..domain.repositories import ICategoryRepository


class DynamoDBCategoryRepository(ICategoryRepository):
    """DynamoDB implementation of Category repository"""

    def __init__(self, table_name: Optional[str] = None):
        self.dynamodb = boto3.resource("dynamodb")
        self.table = self.dynamodb.Table(
            table_name or os.environ.get("CATEGORIES_TABLE", "ChatBooking-Categories")
        )

    def get_by_id(self, tenant_id: TenantId, category_id: str) -> Optional[Category]:
        try:
            response = self.table.get_item(
                Key={"tenantId": str(tenant_id), "categoryId": category_id}
            )
            item = response.get("Item")

            if not item:
                return None

            return self._item_to_entity(item)
        except ClientError as e:
            print(f"Error getting category: {e}")
            return None

    def list_by_tenant(
        self, tenant_id: TenantId, active_only: bool = False
    ) -> List[Category]:
        try:
            response = self.table.query(
                KeyConditionExpression=Key("tenantId").eq(str(tenant_id))
            )

            categories = [
                self._item_to_entity(item) for item in response.get("Items", [])
            ]

            if active_only:
                return [c for c in categories if c.is_active]

            return sorted(categories, key=lambda c: c.display_order)
        except ClientError as e:
            print(f"Error listing categories: {e}")
            return []

    def save(self, category: Category) -> None:
        item = {
            "tenantId": str(category.tenant_id),
            "categoryId": category.category_id,
            "name": category.name,
            "isActive": category.is_active,
            "displayOrder": category.display_order,
            "createdAt": category.created_at.isoformat(),
            "updatedAt": category.updated_at.isoformat(),
            "metadata": category.metadata,
        }

        if category.description:
            item["description"] = category.description

        # DynamoDB doesn't like float/decimals sometimes if strictly typed but boto3 handles primitives well.
        # displayOrder is int.

        self.table.put_item(Item=item)

    def delete(self, tenant_id: TenantId, category_id: str) -> None:
        self.table.delete_item(
            Key={"tenantId": str(tenant_id), "categoryId": category_id}
        )

    def _item_to_entity(self, item: dict) -> Category:
        return Category(
            category_id=item["categoryId"],
            tenant_id=TenantId(item["tenantId"]),
            name=item["name"],
            description=item.get("description"),
            is_active=item.get("isActive", True),
            display_order=int(item.get("displayOrder", 0)),
            metadata=item.get("metadata", {}),
            created_at=datetime.fromisoformat(item["createdAt"]),
            updated_at=datetime.fromisoformat(item["updatedAt"]),
        )
