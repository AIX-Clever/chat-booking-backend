"""
Tests for Public Link Status Handler

Tests for getPublicLinkStatus and setPublicLinkStatus operations.
"""
import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime, timezone

from shared.domain.entities import Tenant, TenantId, TenantStatus, TenantPlan


class TestPublicLinkStatusHandler:
    """Test cases for public link status operations."""

    @pytest.fixture
    def mock_tenant(self):
        """Create a mock tenant for testing."""
        return Tenant(
            tenant_id=TenantId("tenant_test_123"),
            name="Test Business",
            slug="test-business",
            status=TenantStatus.ACTIVE,
            plan=TenantPlan.PRO,
            owner_user_id="user_123",
            billing_email="test@example.com",
            settings={"photoUrl": "https://example.com/logo.png", "bio": "Test bio"},
            is_published=False,
            published_at=None,
            created_at=datetime.now(timezone.utc),
        )

    @pytest.fixture
    def mock_tenant_suspended(self, mock_tenant):
        """Create a suspended tenant."""
        mock_tenant.status = TenantStatus.SUSPENDED
        return mock_tenant

    def test_handle_get_status_success(self, mock_tenant):
        """Test successful get status returns correct structure."""
        from public_link_status.handler import handle_get_status
        
        with patch('public_link_status.handler.DynamoDBTenantRepository') as mock_repo, \
             patch('public_link_status.handler.DynamoDBServiceRepository') as mock_svc_repo, \
             patch('public_link_status.handler.DynamoDBProviderRepository') as mock_prov_repo, \
             patch('public_link_status.handler.DynamoDBAvailabilityRepository') as mock_avail_repo:
            
            mock_repo.return_value.get_by_id.return_value = mock_tenant
            mock_svc_repo.return_value.list_by_tenant.return_value = []
            mock_prov_repo.return_value.list_by_tenant.return_value = []
            
            logger = MagicMock()
            # provider_id is None
            result = handle_get_status(TenantId("tenant_test_123"), None, logger)
            
            assert "isPublished" in result
            assert "completenessChecklist" in result
            assert "completenessPercentage" in result
            assert "publicUrl" in result
            assert result["isPublished"] == False
            assert result["slug"] == "test-business"

    def test_handle_get_status_tenant_not_found(self):
        """Test get status with non-existent tenant."""
        from public_link_status.handler import handle_get_status
        
        with patch('public_link_status.handler.DynamoDBTenantRepository') as mock_repo:
            mock_repo.return_value.get_by_id.return_value = None
            
            logger = MagicMock()
            with pytest.raises(Exception) as exc_info:
                handle_get_status(TenantId("non_existent"), None, logger)
            
            assert "Tenant not found" in str(exc_info.value)

    def test_handle_set_status_success(self, mock_tenant):
        """Test successful publication toggle."""
        from public_link_status.handler import handle_set_status
        
        with patch('public_link_status.handler.DynamoDBTenantRepository') as mock_repo, \
             patch('public_link_status.handler.check_rate_limit', return_value=True):
            
            mock_repo.return_value.get_by_id.return_value = mock_tenant
            mock_repo.return_value.save = MagicMock()
            
            logger = MagicMock()
            result = handle_set_status(TenantId("tenant_test_123"), True, logger)
            
            assert result["success"] == True
            assert result["isPublished"] == True
            assert "publishedAt" in result

    def test_handle_set_status_suspended_tenant_fails(self, mock_tenant_suspended):
        """Test that suspended tenants cannot publish."""
        from public_link_status.handler import handle_set_status
        
        with patch('public_link_status.handler.DynamoDBTenantRepository') as mock_repo:
            mock_repo.return_value.get_by_id.return_value = mock_tenant_suspended
            
            logger = MagicMock()
            with pytest.raises(Exception) as exc_info:
                handle_set_status(TenantId("tenant_test_123"), True, logger)
            
            assert "Cannot publish" in str(exc_info.value)

    def test_handle_set_status_rate_limit_exceeded(self, mock_tenant):
        """Test rate limiting prevents excessive toggles."""
        from public_link_status.handler import handle_set_status
        
        with patch('public_link_status.handler.DynamoDBTenantRepository') as mock_repo, \
             patch('public_link_status.handler.check_rate_limit', return_value=False):
            
            mock_repo.return_value.get_by_id.return_value = mock_tenant
            
            logger = MagicMock()
            with pytest.raises(Exception) as exc_info:
                handle_set_status(TenantId("tenant_test_123"), True, logger)
            
            assert "Rate limit exceeded" in str(exc_info.value)


    def test_handle_get_status_lite_provider_slug(self):
        """Test LITE plan uses provider slug if available."""
        from public_link_status.handler import handle_get_status
        from shared.domain.entities import Tenant, TenantId, TenantStatus, TenantPlan, Provider
        
        # Create LITE tenant
        lite_tenant = Tenant(
            tenant_id=TenantId("tenant_lite"),
            name="Lite Business",
            slug="lite-business-slug", # Should be ignored in favor of provider slug
            status=TenantStatus.ACTIVE,
            plan=TenantPlan.LITE,
            owner_user_id="user_lite",
            billing_email="lite@example.com",
            settings={},
            is_published=True,
            published_at=datetime.now(timezone.utc),
            created_at=datetime.now(timezone.utc),
        )
        
        # Create Provider with slug
        provider_with_slug = MagicMock(spec=Provider)
        provider_with_slug.provider_id = "prov_1"
        provider_with_slug.active = True
        provider_with_slug.slug = "expert-mario"
        provider_with_slug.bio = "Expert bio"
        provider_with_slug.photo_url = "http://photo"
        provider_with_slug.service_ids = ["srv_1"]
        
        with patch('public_link_status.handler.DynamoDBTenantRepository') as mock_repo, \
             patch('public_link_status.handler.DynamoDBServiceRepository') as mock_svc_repo, \
             patch('public_link_status.handler.DynamoDBProviderRepository') as mock_prov_repo, \
             patch('public_link_status.handler.DynamoDBAvailabilityRepository') as mock_avail_repo:
            
            mock_repo.return_value.get_by_id.return_value = lite_tenant
            mock_svc_repo.return_value.list_by_tenant.return_value = []
            
            # Return list of providers
            mock_prov_repo.return_value.list_by_tenant.return_value = [provider_with_slug]
            
            logger = MagicMock()
            result = handle_get_status(TenantId("tenant_lite"), None, logger)
            
            # Logic should pick "expert-mario" instead of "lite-business-slug"
            assert result["slug"] == "expert-mario"
            assert "expert-mario" in result["publicUrl"]


class TestRateLimiter:
    """Test cases for rate limiting functionality."""

    def test_check_rate_limit_allows_under_limit(self):
        """Test that requests under limit are allowed."""
        from public_link_status.handler import check_rate_limit, _rate_limit_cache
        
        # Clear cache
        _rate_limit_cache.clear()
        
        result = check_rate_limit("test_key", max_requests=5, window_seconds=60)
        assert result == True

    def test_check_rate_limit_blocks_over_limit(self):
        """Test that requests over limit are blocked."""
        from public_link_status.handler import check_rate_limit, _rate_limit_cache
        
        # Clear cache and fill it
        _rate_limit_cache.clear()
        
        # Make 5 requests (at limit)
        for _ in range(5):
            check_rate_limit("test_over_limit", max_requests=5, window_seconds=60)
        
        # 6th request should be blocked
        result = check_rate_limit("test_over_limit", max_requests=5, window_seconds=60)
        assert result == False


class TestCompletenessChecklist:
    """Test cases for completeness checklist generation."""

    @pytest.fixture
    def complete_tenant(self):
        """Tenant with all required fields."""
        return Tenant(
            tenant_id=TenantId("tenant_complete"),
            name="Complete Business",
            slug="complete-business",
            status=TenantStatus.ACTIVE,
            plan=TenantPlan.PRO,
            owner_user_id="user_123",
            billing_email="test@example.com",
            settings={"photoUrl": "logo.png", "bio": "Description"},
            is_published=False,
            published_at=None,
            created_at=datetime.now(timezone.utc),
        )

    def test_checklist_includes_all_required_items(self, complete_tenant):
        """Test that checklist includes all 7 expected items for PRO plan."""
        from public_link_status.handler import build_comprehensive_checklist
        
        with patch('public_link_status.handler.DynamoDBServiceRepository') as mock_svc_repo, \
             patch('public_link_status.handler.DynamoDBProviderRepository') as mock_prov_repo, \
             patch('shared.infrastructure.dynamodb_repositories.DynamoDBRoomRepository') as mock_room_repo:
            
            mock_svc_repo.return_value.list_by_tenant.return_value = []
            mock_prov_repo.return_value.list_by_tenant.return_value = []
            mock_room_repo.return_value.list_by_tenant.return_value = []
            
            logger = MagicMock()
            
            checklist = build_comprehensive_checklist(
                TenantId("tenant_complete"), 
                complete_tenant, 
                None,
                logger
            )
            
            # PRO Plan expects 7 items: 
            # business_name, slug, logo, categories, services, rooms, providers
            assert len(checklist) == 7
            
            item_names = [item["item"] for item in checklist]
            assert "business_name" in item_names
            assert "slug" in item_names
            assert "logo" in item_names
            assert "categories" in item_names
            assert "services" in item_names
            assert "rooms" in item_names
            assert "providers" in item_names

    def test_checklist_marks_missing_items(self):
        """Test that missing required items are marked as MISSING and LITE exclusions work."""
        from public_link_status.handler import build_comprehensive_checklist
        
        incomplete_tenant = Tenant(
            tenant_id=TenantId("tenant_incomplete"),
            name="",  # Missing name
            slug="",  # Missing slug
            status=TenantStatus.ACTIVE,
            plan=TenantPlan.LITE,
            owner_user_id="user_123",
            billing_email="test@example.com",
            settings={},
            is_published=False,
            published_at=None,
            created_at=datetime.now(timezone.utc),
        )
        
        with patch('public_link_status.handler.DynamoDBServiceRepository') as mock_svc_repo, \
             patch('public_link_status.handler.DynamoDBProviderRepository') as mock_prov_repo:
            
            mock_svc_repo.return_value.list_by_tenant.return_value = []
            mock_prov_repo.return_value.list_by_tenant.return_value = []
            
            logger = MagicMock()
            checklist = build_comprehensive_checklist(
                TenantId("tenant_incomplete"), 
                incomplete_tenant, 
                None,
                logger
            )
            
            item_names = [item["item"] for item in checklist]
            
            # LITE Plan should EXCLUDE business_name, logo, rooms
            assert "business_name" not in item_names
            assert "logo" not in item_names
            assert "rooms" not in item_names
            
            # Should INCLUDE slug, categories, services, providers
            assert "slug" in item_names
            assert "categories" in item_names
            assert "services" in item_names
            assert "providers" in item_names
            
            # Verify status for missing items
            slug_item = next(i for i in checklist if i["item"] == "slug")
            assert slug_item["status"] == "MISSING"

    def test_checklist_detects_logo_in_profile(self):
        """Test that logo is detected when present in settings.profile.logoUrl."""
        from public_link_status.handler import build_comprehensive_checklist
        
        tenant = Tenant(
            tenant_id=TenantId("tenant_profile_logo"),
            name="Business",
            slug="slug",
            status=TenantStatus.ACTIVE,
            plan=TenantPlan.PRO,
            owner_user_id="user_123",
            billing_email="test@example.com",
            settings={"profile": {"logoUrl": "https://example.com/logo.png"}},
            is_published=False,
            published_at=None,
            created_at=datetime.now(timezone.utc),
        )
        
        with patch('public_link_status.handler.DynamoDBServiceRepository') as mock_svc_repo, \
             patch('public_link_status.handler.DynamoDBProviderRepository') as mock_prov_repo, \
             patch('shared.infrastructure.dynamodb_repositories.DynamoDBRoomRepository') as mock_room_repo:
            
            mock_svc_repo.return_value.list_by_tenant.return_value = []
            mock_prov_repo.return_value.list_by_tenant.return_value = []
            mock_room_repo.return_value.list_by_tenant.return_value = []
            
            logger = MagicMock()
            checklist = build_comprehensive_checklist(
                TenantId("tenant_profile_logo"), 
                tenant, 
                None,
                logger
            )
            
            logo_item = next(i for i in checklist if i["item"] == "logo")
            assert logo_item["status"] == "COMPLETE"

