
import boto3
import os
from typing import List, Optional
from datetime import datetime
from botocore.exceptions import ClientError
from boto3.dynamodb.conditions import Key

from ..domain.entities import UserRoleEntity, UserRole, UserStatus, TenantId

class DynamoDBUserRoleRepository:
    """DynamoDB implementation of UserRole repository"""

    def __init__(self, table_name: Optional[str] = None):
        self.dynamodb = boto3.resource('dynamodb')
        self.table = self.dynamodb.Table(
            table_name or os.environ.get('USER_ROLES_TABLE', 'ChatBooking-UserRoles')
        )

    def get(self, user_id: str) -> Optional[UserRoleEntity]:
        try:
            response = self.table.get_item(Key={'userId': user_id})
            item = response.get('Item')
            if not item:
                return None
            return self._item_to_entity(item)
        except ClientError as e:
            print(f"Error getting user role: {e}")
            return None

    def create(self, user_role: UserRoleEntity) -> None:
        self.save(user_role)

    def update(self, user_role: UserRoleEntity) -> UserRoleEntity:
        self.save(user_role)
        return user_role

    def save(self, user_role: UserRoleEntity) -> None:
        item = {
            'userId': user_role.user_id,
            'tenantId': str(user_role.tenant_id),
            'email': user_role.email,
            'role': user_role.role.value,
            'status': user_role.status.value,
            'createdAt': user_role.created_at.isoformat(),
            'updatedAt': user_role.updated_at.isoformat()
        }
        if user_role.name:
            item['name'] = user_role.name

        self.table.put_item(Item=item)

    def list_by_tenant(self, tenant_id: TenantId) -> List[UserRoleEntity]:
        try:
            # Assuming GSI on tenantId
            response = self.table.query(
                IndexName='tenantId-index',
                KeyConditionExpression=Key('tenantId').eq(str(tenant_id))
            )
            return [self._item_to_entity(item) for item in response.get('Items', [])]
        except ClientError as e:
            print(f"Error listing user roles: {e}")
            return []

    def count_active_users(self, tenant_id: TenantId) -> int:
        users = self.list_by_tenant(tenant_id)
        return len([u for u in users if u.status == UserStatus.ACTIVE])

    def _item_to_entity(self, item: dict) -> UserRoleEntity:
        return UserRoleEntity(
            user_id=item['userId'],
            tenant_id=TenantId(item['tenantId']),
            email=item['email'],
            role=UserRole(item['role']),
            status=UserStatus(item['status']),
            name=item.get('name'),
            created_at=datetime.fromisoformat(item['createdAt']),
            updated_at=datetime.fromisoformat(item['updatedAt'])
        )
