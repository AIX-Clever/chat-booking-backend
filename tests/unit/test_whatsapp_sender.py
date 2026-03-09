import json
import pytest
from unittest.mock import patch, MagicMock
from backend.whatsapp_sender.handler import lambda_handler

@pytest.fixture
def mock_env(monkeypatch):
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    monkeypatch.setenv("TWILIO_ACCOUNT_SID", "AC123")
    monkeypatch.setenv("TWILIO_AUTH_TOKEN", "auth123")
    monkeypatch.setenv("TWILIO_PHONE_NUMBER", "+1234567890")
    monkeypatch.setenv("WHATSAPP_MESSAGES_TABLE", "TestTable")

@pytest.fixture
def sqs_event():
    return {
        "Records": [
            {
                "messageId": "msg-1",
                "body": json.dumps({
                    "tenant_id": "tenant-1",
                    "to": "+56912345678",
                    "message": "Hola, confirmación de cita."
                })
            }
        ]
    }

@pytest.fixture
def sns_wrapped_event():
    return {
        "Records": [
            {
                "messageId": "msg-1",
                "body": json.dumps({
                    "Type": "Notification",
                    "MessageId": "sns-msg-1",
                    "TopicArn": "arn:aws:sns:us-east-1:000000000000:ChatBooking-WhatsappMessages",
                    "Message": json.dumps({
                        "tenant_id": "tenant-1",
                        "to": "+56912345678",
                        "message": "Hola, SNS check."
                    })
                })
            }
        ]
    }

@patch("backend.whatsapp_sender.handler.TWILIO_PHONE_NUMBER", "+1234567890")
@patch("backend.whatsapp_sender.handler.TWILIO_AUTH_TOKEN", "auth123")
@patch("backend.whatsapp_sender.handler.TWILIO_ACCOUNT_SID", "AC123")
@patch("backend.whatsapp_sender.handler.tenant_repo")
@patch("backend.whatsapp_sender.handler.limit_service")
@patch("backend.whatsapp_sender.handler.urllib.request.urlopen")
@patch("backend.whatsapp_sender.handler.whatsapp_table")
@patch("backend.whatsapp_sender.handler.metrics_service")
def test_whatsapp_sender_success(mock_metrics, mock_table, mock_urlopen, mock_limit_service, mock_tenant_repo, sqs_event, mock_env):
    # Mock limits
    mock_limit_service.check_can_send_message.return_value = True
    
    # Mock tenant
    mock_tenant = MagicMock()
    mock_tenant.settings = {} # Use default env vars
    mock_tenant_repo.get_by_id.return_value = mock_tenant
    
    # Mock Twilio via urllib success
    mock_response = MagicMock()
    mock_response.read.return_value = json.dumps({"sid": "SM12345", "status": "queued"}).encode("utf-8")
    mock_urlopen.return_value.__enter__.return_value = mock_response
    
    # Invoke
    lambda_handler(sqs_event, None)
    
    # Verify limit checked
    mock_limit_service.check_can_send_message.assert_called_once()
    
    # Verify message sent via urllib
    mock_urlopen.assert_called_once()
    req = mock_urlopen.call_args[0][0]
    assert "Accounts/AC123/Messages.json" in req.full_url
    
    # Verify DynamoDB save
    mock_table.put_item.assert_called_once()
    saved_item = mock_table.put_item.call_args[1]["Item"]
    assert saved_item["messageId"] == "SM12345"
    assert saved_item["status"] == "queued"

@patch("backend.whatsapp_sender.handler.tenant_repo")
@patch("backend.whatsapp_sender.handler.limit_service")
@patch("backend.whatsapp_sender.handler.urllib.request.urlopen")
@patch("backend.whatsapp_sender.handler.whatsapp_table")
@patch("backend.whatsapp_sender.handler.metrics_service")
def test_whatsapp_sender_quota_exceeded(mock_metrics, mock_table, mock_urlopen, mock_limit_service, mock_tenant_repo, sqs_event, mock_env):
    # Mock limits
    mock_limit_service.check_can_send_message.return_value = False
    
    # Mock tenant
    mock_tenant = MagicMock()
    mock_tenant_repo.get_by_id.return_value = mock_tenant

    # Invoke
    lambda_handler(sqs_event, None)
    
    # Verify no Twilio call
    mock_urlopen.assert_not_called()
    mock_table.put_item.assert_not_called()

@patch("backend.whatsapp_sender.handler.tenant_repo")
@patch("backend.whatsapp_sender.handler.limit_service")
@patch("backend.whatsapp_sender.handler.urllib.request.urlopen")
@patch("backend.whatsapp_sender.handler.whatsapp_table")
@patch("backend.whatsapp_sender.handler.metrics_service")
def test_whatsapp_sender_custom_tenant_credentials(mock_metrics, mock_table, mock_urlopen, mock_limit_service, mock_tenant_repo, sqs_event, mock_env):
    # Mock limits
    mock_limit_service.check_can_send_message.return_value = True
    
    # Mock tenant with custom settings
    mock_tenant = MagicMock()
    mock_tenant.settings = {
        "twilio_account_sid": "CUSTOM_SID",
        "twilio_auth_token": "CUSTOM_TOKEN",
        "twilio_whatsapp_number": "+9876543210"
    }
    mock_tenant_repo.get_by_id.return_value = mock_tenant
    
    # Mock Twilio success
    mock_response = MagicMock()
    mock_response.read.return_value = json.dumps({"sid": "SM999", "status": "queued"}).encode("utf-8")
    mock_urlopen.return_value.__enter__.return_value = mock_response
    
    # Invoke
    lambda_handler(sqs_event, None)
    
    # Verify customized Client URL 
    mock_urlopen.assert_called_once()
    req = mock_urlopen.call_args[0][0]
    assert "Accounts/CUSTOM_SID/Messages.json" in req.full_url

@patch("backend.whatsapp_sender.handler.TWILIO_PHONE_NUMBER", "+1234567890")
@patch("backend.whatsapp_sender.handler.TWILIO_AUTH_TOKEN", "auth123")
@patch("backend.whatsapp_sender.handler.TWILIO_ACCOUNT_SID", "AC123")
@patch("backend.whatsapp_sender.handler.tenant_repo")
@patch("backend.whatsapp_sender.handler.limit_service")
@patch("backend.whatsapp_sender.handler.urllib.request.urlopen")
@patch("backend.whatsapp_sender.handler.whatsapp_table")
@patch("backend.whatsapp_sender.handler.metrics_service")
def test_whatsapp_sender_sns_wrapped(mock_metrics, mock_table, mock_urlopen, mock_limit_service, mock_tenant_repo, sns_wrapped_event, mock_env):
    # Mock limits
    mock_limit_service.check_can_send_message.return_value = True
    
    # Mock tenant
    mock_tenant = MagicMock()
    mock_tenant.settings = {}
    mock_tenant_repo.get_by_id.return_value = mock_tenant
    
    # Mock Twilio via urllib success
    mock_response = MagicMock()
    mock_response.read.return_value = json.dumps({"sid": "SM-SNS", "status": "queued"}).encode("utf-8")
    mock_urlopen.return_value.__enter__.return_value = mock_response
    
    lambda_handler(sns_wrapped_event, None)
    
    mock_limit_service.check_can_send_message.assert_called_once()
    mock_urlopen.assert_called_once()
    
    req = mock_urlopen.call_args[0][0]
    # Check that payload contains SNS body content "Hola, SNS check."
    assert b"Hola%2C+SNS+check" in req.data
    
    mock_table.put_item.assert_called_once()
    saved_item = mock_table.put_item.call_args[1]["Item"]
    assert saved_item["messageId"] == "SM-SNS"

@patch("backend.whatsapp_sender.handler.TWILIO_PHONE_NUMBER", "")
@patch("backend.whatsapp_sender.handler.TWILIO_AUTH_TOKEN", "")
@patch("backend.whatsapp_sender.handler.TWILIO_ACCOUNT_SID", "")
@patch("backend.whatsapp_sender.handler.tenant_repo")
@patch("backend.whatsapp_sender.handler.limit_service")
@patch("backend.whatsapp_sender.handler.urllib.request.urlopen")
@patch("backend.whatsapp_sender.handler.whatsapp_table")
@patch("backend.whatsapp_sender.handler.metrics_service")
def test_whatsapp_sender_missing_credentials(mock_metrics, mock_table, mock_urlopen, mock_limit_service, mock_tenant_repo, sqs_event, mock_env):
    mock_limit_service.check_can_send_message.return_value = True
    
    mock_tenant = MagicMock()
    mock_tenant.settings = {} # Force fallback to empty env vars
    mock_tenant.tenant_id.value = "tenant-1"
    mock_tenant_repo.get_by_id.return_value = mock_tenant
    
    with pytest.raises(ValueError, match="Missing Twilio credentials"):
        lambda_handler(sqs_event, None)
