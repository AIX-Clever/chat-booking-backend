import json
import pytest
from unittest.mock import patch, MagicMock
from backend.whatsapp_webhook.handler import lambda_handler
import urllib.parse

@pytest.fixture
def mock_env(monkeypatch):
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    monkeypatch.setenv("WHATSAPP_MESSAGES_TABLE", "TestTable")
    monkeypatch.setenv("WHATSAPP_STATIC_RESPONSE", "Test static response")

@pytest.fixture
def webhook_status_event():
    # Twilio status callback is application/x-www-form-urlencoded
    body = {
        "MessageSid": "SM123456789",
        "MessageStatus": "delivered",
    }
    encoded_body = urllib.parse.urlencode(body)
    return {
        "requestContext": {
            "http": {
                "method": "POST"
            }
        },
        "headers": {
            "content-type": "application/x-www-form-urlencoded"
        },
        "body": encoded_body,
        "isBase64Encoded": False
    }

@pytest.fixture
def webhook_incoming_event():
    # Twilio incoming message
    body = {
        "MessageSid": "SM000000000",
        "Body": "Hola quiero agendar",
        "From": "whatsapp:+56912345678"
    }
    encoded_body = urllib.parse.urlencode(body)
    return {
        "requestContext": {
            "http": {
                "method": "POST"
            }
        },
        "headers": {
            "content-type": "application/x-www-form-urlencoded"
        },
        "body": encoded_body,
        "isBase64Encoded": False
    }

@patch("backend.whatsapp_webhook.handler.whatsapp_table")
def test_whatsapp_webhook_status_callback(mock_table, webhook_status_event, mock_env):
    # Mock the GSI query to return a tenantId
    mock_table.query.return_value = {
        "Items": [{"tenantId": "tenant-123", "messageId": "SM123456789"}]
    }

    response = lambda_handler(webhook_status_event, None)
    
    assert response["statusCode"] == 200
    
    # Verify GSI queried
    mock_table.query.assert_called_once()
    
    # Verify update item called
    mock_table.update_item.assert_called_once()
    update_kwargs = mock_table.update_item.call_args[1]
    assert update_kwargs["Key"]["tenantId"] == "tenant-123"
    assert update_kwargs["Key"]["messageId"] == "SM123456789"
    assert update_kwargs["ExpressionAttributeValues"][":s"] == "delivered"

@patch("backend.whatsapp_webhook.handler.whatsapp_table")
def test_whatsapp_webhook_incoming_message(mock_table, webhook_incoming_event, mock_env):
    response = lambda_handler(webhook_incoming_event, None)
    
    assert response["statusCode"] == 200
    assert response["headers"]["Content-Type"] == "text/xml"
    
    # Should return TwiML with the static response
    body = response["body"]
    assert "<Response>" in body
    assert "<Message>Este es un canal exclusivo para el envío de recordatorios médicos. Por el momento, no procesamos respuestas o mensajes por este medio.</Message>" in body
    
    # No DB update on incoming (unless we track them eventually, but right now we just reply)
    mock_table.update_item.assert_not_called()

@patch("backend.whatsapp_webhook.handler.whatsapp_table")
def test_whatsapp_webhook_base64_payload(mock_table, mock_env):
    import base64
    raw_body = "MessageSid=SM999&Body=Encoded+Message&From=whatsapp%3A%2B12345678"
    b64_body = base64.b64encode(raw_body.encode("utf-8")).decode("utf-8")
    
    event = {
        "isBase64Encoded": True,
        "body": b64_body
    }
    
    response = lambda_handler(event, None)
    
    assert response["statusCode"] == 200
    assert "<Message>Este es un canal exclusivo para el envío de recordatorios médicos. Por el momento, no procesamos respuestas o mensajes por este medio.</Message>" in response["body"]

@patch("backend.whatsapp_webhook.handler.whatsapp_table")
def test_whatsapp_webhook_status_callback_with_error(mock_table, mock_env):
    mock_table.query.return_value = {
        "Items": [{"tenantId": "tenant-1", "messageId": "SM-ERR"}]
    }
    
    event = {
        "body": "MessageSid=SM-ERR&MessageStatus=failed&ErrorCode=30005&ErrorMessage=Unknown+destination+handset"
    }
    
    response = lambda_handler(event, None)
    assert response["statusCode"] == 200
    
    mock_table.update_item.assert_called_once()
    kwargs = mock_table.update_item.call_args[1]
    assert kwargs["Key"] == {"tenantId": "tenant-1", "messageId": "SM-ERR"}
    assert ":ec" in kwargs["ExpressionAttributeValues"]
    assert kwargs["ExpressionAttributeValues"][":ec"] == "30005"
    assert kwargs["ExpressionAttributeValues"][":s"] == "failed"

