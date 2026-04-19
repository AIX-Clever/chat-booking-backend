import unittest
from unittest.mock import Mock, patch
from user_management.service import UserManagementService
from shared.domain.entities import TenantId, UserRoleEntity, UserRole, UserStatus
from datetime import datetime, timezone


class TestUserManagementService(unittest.TestCase):
    def setUp(self):
        self.mock_tenant_repo = Mock()
        self.mock_user_role_repo = Mock()
        self.mock_email_service = Mock()
        self.mock_cognito = Mock()
        self.user_pool_id = "test-pool-id"

        with patch(
            "user_management.service.UserManagementService._get_user_pool_id",
            return_value=self.user_pool_id,
        ):
            self.service = UserManagementService(
                tenant_repo=self.mock_tenant_repo,
                user_role_repo=self.mock_user_role_repo,
                email_service=self.mock_email_service,
                cognito_client=self.mock_cognito,
                user_pool_id=self.user_pool_id,
            )

        self.tenant_id = TenantId("tenant-123")
        self.user_id = "user-456"

    def test_reset_user_password_success(self):
        # Act
        result = self.service.reset_user_password(self.user_id)

        # Assert
        self.assertTrue(result)
        self.mock_cognito.admin_reset_user_password.assert_called_with(
            UserPoolId=self.user_pool_id, Username=self.user_id
        )

    def test_resend_invitation_pending_user(self):
        # Arrange
        user_role = UserRoleEntity(
            user_id=self.user_id,
            tenant_id=self.tenant_id,
            email="test@example.com",
            role=UserRole.USER,
            status=UserStatus.PENDING_INVITATION,
            name="Test User",
            created_at=datetime.now(timezone.utc),
        )
        self.mock_user_role_repo.get.return_value = user_role

        # Act
        result = self.service.resend_invitation(self.user_id)

        # Assert
        self.assertTrue(result)
        self.mock_cognito.admin_set_user_password.assert_called_once()
        self.mock_email_service.send_email.assert_called_once()

    def test_resend_invitation_active_user_falls_back_to_reset(self):
        # Arrange
        user_role = UserRoleEntity(
            user_id=self.user_id,
            tenant_id=self.tenant_id,
            email="test@example.com",
            role=UserRole.USER,
            status=UserStatus.ACTIVE,
            name="Active User",
            created_at=datetime.now(timezone.utc),
        )
        self.mock_user_role_repo.get.return_value = user_role

        # Act
        result = self.service.resend_invitation(self.user_id)

        # Assert
        self.assertTrue(result)
        # Should call admin_reset_user_password instead of setting a temp password
        self.mock_cognito.admin_reset_user_password.assert_called_once()
        self.mock_cognito.admin_set_user_password.assert_not_called()


if __name__ == "__main__":
    unittest.main()
