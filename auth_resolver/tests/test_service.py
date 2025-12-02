"""
Unit tests for auth_resolver service
"""

import pytest
from datetime import datetime
from unittest.mock import Mock, MagicMock
from shared.domain.entities import TenantId, Tenant, TenantStatus, TenantPlan, ApiKey
from shared.domain.exceptions import (
    InvalidApiKeyError,
    OriginNotAllowedError,
    TenantNotActiveError
)
from auth_resolver.service import AuthenticationService


class TestAuthenticationService:
    """Test AuthenticationService"""
    
    @pytest.fixture
    def mock_tenant_repo(self):
        return Mock()
    
    @pytest.fixture
    def mock_api_key_repo(self):
        return Mock()
    
    @pytest.fixture
    def auth_service(self, mock_tenant_repo, mock_api_key_repo):
        return AuthenticationService(mock_tenant_repo, mock_api_key_repo)
    
    def test_authenticate_valid_api_key(self, auth_service, mock_api_key_repo, mock_tenant_repo):
        """Test successful authentication"""
        # Setup
        tenant_id = TenantId("test123")
        api_key = ApiKey(
            api_key_id="key_123",
            tenant_id=tenant_id,
            key_hash="hashed_key",
            description="Test key",
            allowed_origins=["https://example.com"],
            is_active=True,
            created_at=datetime.utcnow()
        )
        
        tenant = Tenant(
            tenant_id=tenant_id,
            name="Test Tenant",
            slug="test-tenant",
            status=TenantStatus.ACTIVE,
            plan=TenantPlan.PRO,
            owner_user_id="user_123",
            billing_email="billing@test.com"
        )
        
        mock_api_key_repo.get_by_key_hash.return_value = api_key
        mock_tenant_repo.get_by_id.return_value = tenant
        
        # Execute
        result = auth_service.authenticate_api_key(
            "test_api_key",
            "https://example.com"
        )
        
        # Assert
        assert result == tenant_id
        mock_api_key_repo.save.assert_called_once()  # lastUsedAt updated
    
    def test_authenticate_invalid_api_key(self, auth_service, mock_api_key_repo):
        """Test authentication with invalid API key"""
        mock_api_key_repo.get_by_key_hash.return_value = None
        
        with pytest.raises(InvalidApiKeyError):
            auth_service.authenticate_api_key("invalid_key", "https://example.com")
    
    def test_authenticate_inactive_api_key(self, auth_service, mock_api_key_repo):
        """Test authentication with inactive API key"""
        api_key = ApiKey(
            api_key_id="key_123",
            tenant_id=TenantId("test123"),
            key_hash="hashed_key",
            description="Test key",
            allowed_origins=["https://example.com"],
            is_active=False,
            created_at=datetime.utcnow()
        )
        
        mock_api_key_repo.get_by_key_hash.return_value = api_key
        
        with pytest.raises(InvalidApiKeyError):
            auth_service.authenticate_api_key("test_key", "https://example.com")
    
    def test_authenticate_disallowed_origin(self, auth_service, mock_api_key_repo):
        """Test authentication from disallowed origin"""
        api_key = ApiKey(
            api_key_id="key_123",
            tenant_id=TenantId("test123"),
            key_hash="hashed_key",
            description="Test key",
            allowed_origins=["https://allowed.com"],
            is_active=True,
            created_at=datetime.utcnow()
        )
        
        mock_api_key_repo.get_by_key_hash.return_value = api_key
        
        with pytest.raises(OriginNotAllowedError):
            auth_service.authenticate_api_key("test_key", "https://malicious.com")
    
    def test_authenticate_suspended_tenant(self, auth_service, mock_api_key_repo, mock_tenant_repo):
        """Test authentication with suspended tenant"""
        tenant_id = TenantId("test123")
        api_key = ApiKey(
            api_key_id="key_123",
            tenant_id=tenant_id,
            key_hash="hashed_key",
            description="Test key",
            allowed_origins=["https://example.com"],
            is_active=True,
            created_at=datetime.utcnow()
        )
        
        tenant = Tenant(
            tenant_id=tenant_id,
            name="Test Tenant",
            slug="test-tenant",
            status=TenantStatus.SUSPENDED,
            plan=TenantPlan.PRO,
            owner_user_id="user_123",
            billing_email="billing@test.com"
        )
        
        mock_api_key_repo.get_by_key_hash.return_value = api_key
        mock_tenant_repo.get_by_id.return_value = tenant
        
        with pytest.raises(TenantNotActiveError):
            auth_service.authenticate_api_key("test_key", "https://example.com")
    
    def test_authenticate_wildcard_origin(self, auth_service, mock_api_key_repo, mock_tenant_repo):
        """Test authentication with wildcard origin"""
        tenant_id = TenantId("test123")
        api_key = ApiKey(
            api_key_id="key_123",
            tenant_id=tenant_id,
            key_hash="hashed_key",
            description="Test key",
            allowed_origins=["*"],
            is_active=True,
            created_at=datetime.utcnow()
        )
        
        tenant = Tenant(
            tenant_id=tenant_id,
            name="Test Tenant",
            slug="test-tenant",
            status=TenantStatus.ACTIVE,
            plan=TenantPlan.PRO,
            owner_user_id="user_123",
            billing_email="billing@test.com"
        )
        
        mock_api_key_repo.get_by_key_hash.return_value = api_key
        mock_tenant_repo.get_by_id.return_value = tenant
        
        # Should accept any origin
        result = auth_service.authenticate_api_key("test_key", "https://any-domain.com")
        assert result == tenant_id
