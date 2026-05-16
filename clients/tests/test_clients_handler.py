import pytest
import sys
import os
import boto3
from moto import mock_aws

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

CLIENTS_TABLE = "clients-test"
AUDIT_TABLE = "client-audit-test"

os.environ["CLIENTS_TABLE"] = CLIENTS_TABLE
os.environ["CLIENT_AUDIT_LOGS_TABLE"] = AUDIT_TABLE
os.environ["AWS_DEFAULT_REGION"] = "us-east-2"
os.environ["AWS_ACCESS_KEY_ID"] = "test"
os.environ["AWS_SECRET_ACCESS_KEY"] = "test"


def create_tables(dynamodb):
    dynamodb.create_table(
        TableName=CLIENTS_TABLE,
        KeySchema=[
            {"AttributeName": "tenantId", "KeyType": "HASH"},
            {"AttributeName": "id", "KeyType": "RANGE"},
        ],
        AttributeDefinitions=[
            {"AttributeName": "tenantId", "AttributeType": "S"},
            {"AttributeName": "id", "AttributeType": "S"},
            {"AttributeName": "identifierValue", "AttributeType": "S"},
        ],
        GlobalSecondaryIndexes=[
            {
                "IndexName": "tax-id-index",
                "KeySchema": [
                    {"AttributeName": "tenantId", "KeyType": "HASH"},
                    {"AttributeName": "identifierValue", "KeyType": "RANGE"},
                ],
                "Projection": {"ProjectionType": "ALL"},
            }
        ],
        BillingMode="PAY_PER_REQUEST",
    )
    dynamodb.create_table(
        TableName=AUDIT_TABLE,
        KeySchema=[
            {"AttributeName": "tenantId", "KeyType": "HASH"},
            {"AttributeName": "clientIdAndTimestamp", "KeyType": "RANGE"},
        ],
        AttributeDefinitions=[
            {"AttributeName": "tenantId", "AttributeType": "S"},
            {"AttributeName": "clientIdAndTimestamp", "AttributeType": "S"},
        ],
        BillingMode="PAY_PER_REQUEST",
    )


@mock_aws
def test_create_client_exitoso():
    dynamodb = boto3.resource("dynamodb", region_name="us-east-2")
    create_tables(dynamodb)

    import importlib
    import handler
    importlib.reload(handler)

    result = handler.create_client(
        "tenant-1",
        {
            "names": {"given": "Juan", "family": "Pérez"},
            "identifiers": [{"type": "RUT", "value": "12345678-5"}],
            "contactInfo": [{"system": "email", "value": "juan@test.com"}],
        },
        user_id="user-abc",
    )
    assert result["names"]["given"] == "Juan"
    assert result["id"] is not None


@mock_aws
def test_create_client_rut_invalido():
    dynamodb = boto3.resource("dynamodb", region_name="us-east-2")
    create_tables(dynamodb)

    import importlib
    import handler
    importlib.reload(handler)

    with pytest.raises(ValueError, match="Identificador inválido"):
        handler.create_client(
            "tenant-1",
            {
                "names": {"given": "Ana", "family": "López"},
                "identifiers": [{"type": "RUT", "value": "12345678-0"}],
            },
        )


@mock_aws
def test_create_client_duplicado():
    dynamodb = boto3.resource("dynamodb", region_name="us-east-2")
    create_tables(dynamodb)

    import importlib
    import handler
    importlib.reload(handler)

    payload = {
        "names": {"given": "Luis", "family": "García"},
        "identifiers": [{"type": "RUT", "value": "12345678-5"}],
    }
    handler.create_client("tenant-1", payload)

    with pytest.raises(ValueError, match="Ya existe un cliente"):
        handler.create_client("tenant-1", payload)


@mock_aws
def test_list_clients_paginacion():
    dynamodb = boto3.resource("dynamodb", region_name="us-east-2")
    create_tables(dynamodb)

    import importlib
    import handler
    importlib.reload(handler)

    for i in range(5):
        handler.create_client(
            "tenant-pag",
            {
                "names": {"given": f"Cliente{i}", "family": "Test"},
                "identifiers": [{"type": "DNI", "value": f"DNI-{i:04d}"}],
            },
        )

    page1 = handler.list_clients("tenant-pag", limit=3)
    assert len(page1["items"]) == 3
    assert page1["nextToken"] is not None

    page2 = handler.list_clients("tenant-pag", limit=3, next_token=page1["nextToken"])
    assert len(page2["items"]) == 2
    assert page2["nextToken"] is None

    # listClients y listClientsPaginated usan el mismo handler
    all_clients = handler.list_clients("tenant-pag", limit=10)
    assert len(all_clients["items"]) == 5


@mock_aws
def test_update_client_registra_changed_by():
    dynamodb = boto3.resource("dynamodb", region_name="us-east-2")
    create_tables(dynamodb)

    import importlib
    import handler
    importlib.reload(handler)

    cliente = handler.create_client(
        "tenant-1",
        {
            "names": {"given": "María", "family": "Torres"},
            "identifiers": [{"type": "DNI", "value": "DNI-0001"}],
        },
        user_id="admin-1",
    )

    handler.update_client(
        "tenant-1",
        {"id": cliente["id"], "names": {"given": "María", "family": "Torres Updated"}},
        user_id="editor-99",
    )

    audit = handler.list_client_audit_logs("tenant-1", cliente["id"])
    update_logs = [log for log in audit if log.get("field") == "names"]
    assert any(log["changedBy"] == "editor-99" for log in update_logs)


@mock_aws
def test_update_client_preserva_communication_language():
    dynamodb = boto3.resource("dynamodb", region_name="us-east-2")
    create_tables(dynamodb)

    import importlib
    import handler
    importlib.reload(handler)

    cliente = handler.create_client(
        "tenant-1",
        {
            "names": {"given": "Pedro", "family": "Soto"},
            "identifiers": [{"type": "DNI", "value": "DNI-0002"}],
            "communicationLanguage": "pt",
        },
    )

    handler.update_client(
        "tenant-1",
        {"id": cliente["id"], "occupation": "Médico"},
    )

    updated = handler.get_client("tenant-1", cliente["id"])
    assert updated["communicationLanguage"] == "pt"
