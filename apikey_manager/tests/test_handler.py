import pytest
import os
from unittest.mock import patch
from datetime import datetime, timezone

os.environ["AWS_DEFAULT_REGION"] = "us-east-2"

from shared.domain.entities import ApiKey, TenantId


def make_key(name: str, status: str = "ACTIVE") -> ApiKey:
    return ApiKey(
        api_key_id=f"key_{name.lower().replace(' ', '_')}",
        tenant_id=TenantId("tenant-abc"),
        api_key_hash="hash",
        status=status,
        name=name,
        key_preview="sk_live_abc...xyz",
        allowed_origins=["*"],
        rate_limit=1000,
        created_at=datetime.now(timezone.utc),
    )


BASE_EVENT = {
    "info": {"fieldName": "createApiKey"},
    "identity": {"resolverContext": {"tenantId": "tenant-abc"}},
    "arguments": {"name": "Mi Key"},
}


@pytest.fixture
def mock_repo():
    with patch("apikey_manager.handler.DynamoDBApiKeyRepository") as MockRepo:
        instance = MockRepo.return_value
        yield instance


def call_create(mock_repo, name: str = "Mi Key"):
    from apikey_manager.handler import handle_create_api_key
    return handle_create_api_key(mock_repo, TenantId("tenant-abc"), {"name": name})


class TestCreateApiKey:
    def test_crea_key_cuando_hay_capacidad(self, mock_repo):
        mock_repo.list_by_tenant.return_value = [make_key("Sitio Web")]
        result = call_create(mock_repo, "Widget Embed")
        assert result["name"] == "Widget Embed"
        mock_repo.save.assert_called_once()

    def test_rechaza_nombre_reservado_sitio_web(self, mock_repo):
        mock_repo.list_by_tenant.return_value = [make_key("Widget Embed")]
        with pytest.raises(ValueError, match="reservado"):
            call_create(mock_repo, "Sitio Web")
        mock_repo.save.assert_not_called()

    def test_rechaza_cuando_ya_hay_dos_keys_activas(self, mock_repo):
        mock_repo.list_by_tenant.return_value = [
            make_key("Sitio Web"),
            make_key("Widget Embed"),
        ]
        with pytest.raises(ValueError, match="Límite"):
            call_create(mock_repo, "Otra Key")
        mock_repo.save.assert_not_called()

    def test_rechaza_nombre_duplicado_en_keys_activas(self, mock_repo):
        mock_repo.list_by_tenant.return_value = [make_key("Widget Embed")]
        with pytest.raises(ValueError, match="Ya tienes una key activa"):
            call_create(mock_repo, "Widget Embed")
        mock_repo.save.assert_not_called()

    def test_permite_crear_nombre_que_existia_revocado(self, mock_repo):
        mock_repo.list_by_tenant.return_value = [
            make_key("Widget Embed", status="REVOKED"),
        ]
        result = call_create(mock_repo, "Widget Embed")
        assert result["name"] == "Widget Embed"
        mock_repo.save.assert_called_once()

    def test_permite_crear_si_una_key_esta_revocada(self, mock_repo):
        mock_repo.list_by_tenant.return_value = [
            make_key("Sitio Web"),
            make_key("Widget Embed", status="REVOKED"),
        ]
        result = call_create(mock_repo, "Nueva Key")
        assert result["status"] == "ACTIVE"
        mock_repo.save.assert_called_once()
