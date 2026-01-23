
import unittest
from unittest.mock import Mock, MagicMock
from shared.domain.entities import TenantId, Service, Provider, Category
from catalog.service import CatalogService, ServiceManagementService, ProviderManagementService

class TestCatalogService(unittest.TestCase):
    def setUp(self):
        self.mock_service_repo = Mock()
        self.mock_provider_repo = Mock()
        self.mock_category_repo = Mock()
        self.mock_room_repo = Mock()
        
        self.catalog_service = CatalogService(
            self.mock_service_repo,
            self.mock_provider_repo,
            self.mock_category_repo,
            self.mock_room_repo
        )
        
        self.tenant_id = TenantId("tenant-123")
        self.service_id = "svc-1"

    def test_search_services(self):
        # Arrange
        mock_svc = Service(
            service_id="s1", tenant_id=self.tenant_id, name="Test", description="desc",
            category="cat", duration_minutes=30, price=100
        )
        self.mock_service_repo.search.return_value = [mock_svc]

        # Act
        result = self.catalog_service.search_services(self.tenant_id, query="Test")

        # Assert
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].name, "Test")
        self.mock_service_repo.search.assert_called_with(self.tenant_id, "Test", False)

    def test_list_all_services(self):
        # Arrange
        mock_svc = Service(
            service_id="s1", tenant_id=self.tenant_id, name="Test", description="desc",
            category="cat", duration_minutes=30, price=100
        )
        self.mock_service_repo.list_by_tenant.return_value = [mock_svc]

        # Act
        result = self.catalog_service.list_all_services(self.tenant_id)

        # Assert
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].name, "Test")
        self.mock_service_repo.list_by_tenant.assert_called_with(self.tenant_id)

    def test_list_categories(self):
        # Arrange
        mock_cat = Category(category_id="c1", tenant_id=self.tenant_id, name="Cat1")
        self.mock_category_repo.list_by_tenant.return_value = [mock_cat]

        # Act
        result = self.catalog_service.list_categories(self.tenant_id)

        # Assert
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].name, "Cat1")
        self.mock_category_repo.list_by_tenant.assert_called_with(self.tenant_id, False)

    def test_get_service(self):
        # Arrange
        mock_svc = Service(
            service_id=self.service_id, tenant_id=self.tenant_id, name="Test", description="desc",
            category="cat", duration_minutes=30, price=100
        )
        self.mock_service_repo.get_by_id.return_value = mock_svc

        # Act
        result = self.catalog_service.get_service(self.tenant_id, self.service_id)

        # Assert
        self.assertEqual(result.service_id, self.service_id)

    def test_list_providers_by_service_filtering(self):
        """
        Test that list_providers_by_service correctly filters providers
        and likely (implied) logs the decision.
        """
        # Mock Service
        self.mock_service_repo.get_by_id.return_value = Service(
            service_id=self.service_id,
            tenant_id=self.tenant_id,
            name="Test Service",
            description="desc",
            category="cat",
            duration_minutes=30,
            price=10.0
        )

        # Mock Providers
        # Provider 1: Has service -> Should be included
        p1 = Provider(
            provider_id="p1",
            tenant_id=self.tenant_id,
            name="Provider One",
            bio="bio",
            service_ids=[self.service_id], # MATCH
            timezone="UTC",
            active=True
        )
        # Provider 2: No service -> Should be excluded
        p2 = Provider(
            provider_id="p2",
            tenant_id=self.tenant_id,
            name="Provider Two",
            bio="bio",
            service_ids=["other-svc"], # NO MATCH
            timezone="UTC",
            active=True
        )
        # Provider 3: Has service but inactive -> Should be excluded (based on can_provide_service logic)
        p3 = Provider(
            provider_id="p3",
            tenant_id=self.tenant_id,
            name="Provider Three",
            bio="bio",
            service_ids=[self.service_id],
            timezone="UTC",
            active=False # INACTIVE
        )

        self.mock_provider_repo.list_by_tenant.return_value = [p1, p2, p3]

        # ACT
        result = self.catalog_service.list_providers_by_service(self.tenant_id, self.service_id)

        # ASSERT
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].provider_id, "p1")
        
        # Verify repository call (it calls list_by_tenant now instead of list_by_service)
        self.mock_provider_repo.list_by_tenant.assert_called_with(self.tenant_id)


class TestServiceManagementService(unittest.TestCase):
    def setUp(self):
        self.mock_repo = Mock()
        self.service = ServiceManagementService(self.mock_repo)
        self.tenant_id = TenantId("tenant-1")

    def test_create_service(self):
        # Act
        svc = self.service.create_service(
            self.tenant_id, "s1", "New Service", "desc", "general", 60, 50.0
        )

        # Assert
        self.assertEqual(svc.name, "New Service")
        self.mock_repo.save.assert_called_once()


    def test_update_service(self):
        # Arrange
        self.mock_repo.get_by_id.return_value = Service(
            service_id="s1", tenant_id=self.tenant_id, name="Old Name", description="desc",
            category="cat", duration_minutes=30, price=100
        )
        
        # Act
        svc = self.service.update_service(
            self.tenant_id, "s1", name="Updated Name"
        )
        
        # Assert
        self.assertEqual(svc.name, "Updated Name")
        self.mock_repo.save.assert_called_once()


    def test_delete_service(self):
        # Arrange
        self.mock_repo.get_by_id.return_value = Service(
            service_id="s1", tenant_id=self.tenant_id, name="Svc", description="desc",
            category="cat", duration_minutes=30, price=100
        )
        
        # Act
        self.service.delete_service(self.tenant_id, "s1")
        
        # Assert
        self.mock_repo.delete.assert_called_with(self.tenant_id, "s1")


class TestProviderManagementService(unittest.TestCase):
    def setUp(self):
        self.mock_repo = Mock()
        self.service = ProviderManagementService(self.mock_repo)
        self.tenant_id = TenantId("tenant-1")

    def test_create_provider(self):
        # Act
        prov = self.service.create_provider(
            self.tenant_id, "p1", "Dr. Test", "Bio", ["s1"], "UTC"
        )

        # Assert
        self.assertEqual(prov.name, "Dr. Test")
        self.mock_repo.save.assert_called_once()

