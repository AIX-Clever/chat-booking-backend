import json
import pytest
from unittest.mock import patch, MagicMock
import urllib.parse
import backend.whatsapp_webhook.handler as wh_handler
from backend.whatsapp_webhook.handler import (
    lambda_handler,
    _is_affirmative,
    _is_negative,
)

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


# --- Helpers ---

@pytest.mark.parametrize("text", ["si", "sí", "Sí", "SI", "ok", "dale", "confirmo", "acepto"])
def test_is_affirmative(text):
    assert _is_affirmative(text) is True


@pytest.mark.parametrize("text", ["no", "No", "nop", "cancel", "cancelar"])
def test_is_negative(text):
    assert _is_negative(text) is True


def test_is_affirmative_false_for_unknown():
    assert _is_affirmative("quizas") is False


def test_is_negative_false_for_unknown():
    assert _is_negative("quizas") is False


# --- Waitlist reply flow via lambda_handler ---

def _make_incoming_event(from_number: str, body_text: str) -> dict:
    body = urllib.parse.urlencode({"From": from_number, "Body": body_text, "MessageSid": "SM-test"})
    return {"body": body, "isBase64Encoded": False}


PENDING_CONTEXT = {
    "clientPhone": "whatsapp:+56987654321",
    "tenantId": "tenant-abc",
    "waitingListId": "wl-001",
    "bookingId": "bkg-001",
    "serviceId": "svc-001",
}


@patch("backend.whatsapp_webhook.handler._create_booking_from_waitlist")
@patch("backend.whatsapp_webhook.handler.waitlist_service")
@patch("backend.whatsapp_webhook.handler.waitlist_pending_table")
@patch("backend.whatsapp_webhook.handler.whatsapp_table")
def test_waitlist_reply_affirmative(mock_wa_table, mock_pending_table, mock_wl_service, mock_create_booking, mock_env):
    mock_pending_table.get_item.return_value = {"Item": PENDING_CONTEXT}

    response = lambda_handler(_make_incoming_event("whatsapp:+56987654321", "sí"), None)

    assert response["statusCode"] == 200
    assert "confirmada" in response["body"].lower()
    mock_pending_table.delete_item.assert_called_once_with(Key={"clientPhone": "whatsapp:+56987654321"})
    mock_wl_service.mark_booked.assert_called_once()
    mock_create_booking.assert_called_once_with("whatsapp:+56987654321", "tenant-abc", "bkg-001")


@patch("backend.whatsapp_webhook.handler._advance_waitlist")
@patch("backend.whatsapp_webhook.handler.waitlist_service")
@patch("backend.whatsapp_webhook.handler.waitlist_pending_table")
@patch("backend.whatsapp_webhook.handler.whatsapp_table")
def test_waitlist_reply_negative(mock_wa_table, mock_pending_table, mock_wl_service, mock_advance, mock_env):
    mock_pending_table.get_item.return_value = {"Item": PENDING_CONTEXT}

    response = lambda_handler(_make_incoming_event("whatsapp:+56987654321", "no"), None)

    assert response["statusCode"] == 200
    assert "cancelado" in response["body"].lower()
    mock_pending_table.delete_item.assert_called_once_with(Key={"clientPhone": "whatsapp:+56987654321"})
    mock_wl_service.mark_declined.assert_called_once()
    mock_advance.assert_called_once_with("tenant-abc", "svc-001", "bkg-001")


@patch("backend.whatsapp_webhook.handler.waitlist_pending_table")
@patch("backend.whatsapp_webhook.handler.whatsapp_table")
def test_waitlist_reply_unrecognized(mock_wa_table, mock_pending_table, mock_env):
    mock_pending_table.get_item.return_value = {"Item": PENDING_CONTEXT}

    response = lambda_handler(_make_incoming_event("whatsapp:+56987654321", "tal vez"), None)

    assert response["statusCode"] == 200
    assert "Sí" in response["body"] or "No" in response["body"]
    mock_pending_table.delete_item.assert_not_called()


@patch("backend.whatsapp_webhook.handler.waitlist_pending_table")
@patch("backend.whatsapp_webhook.handler.whatsapp_table")
def test_incoming_message_no_pending_returns_static(mock_wa_table, mock_pending_table, mock_env):
    mock_pending_table.get_item.return_value = {}

    response = lambda_handler(_make_incoming_event("whatsapp:+56999999999", "hola"), None)

    assert response["statusCode"] == 200
    assert "text/xml" in response["headers"]["Content-Type"]


# --- _advance_waitlist ---

@patch("backend.whatsapp_webhook.handler.sqs_client")
@patch("backend.whatsapp_webhook.handler.booking_repo")
@patch("backend.whatsapp_webhook.handler.waitlist_service")
def test_advance_waitlist_notifies_next_candidate(mock_wl_service, mock_booking_repo, mock_sqs, mock_env, monkeypatch):
    monkeypatch.setattr(wh_handler, "WHATSAPP_SENDER_QUEUE_URL", "https://sqs.example.com/queue")
    candidate = MagicMock()
    candidate.waiting_list_id = "wl-002"
    candidate.client_id = "+56911111111"
    mock_wl_service.process_cancellation.return_value = candidate

    wh_handler._advance_waitlist("tenant-abc", "svc-001", "bkg-001")

    mock_wl_service.mark_contacted.assert_called_once()
    mock_booking_repo.soft_lock.assert_called_once()
    mock_sqs.send_message.assert_called_once()
    sent_body = json.loads(mock_sqs.send_message.call_args.kwargs["MessageBody"])
    assert sent_body["type"] == "waitlist_notification"
    assert sent_body["to"] == "+56911111111"


@patch("backend.whatsapp_webhook.handler.waitlist_service")
def test_advance_waitlist_no_candidates(mock_wl_service, mock_env, monkeypatch):
    monkeypatch.setattr(wh_handler, "WHATSAPP_SENDER_QUEUE_URL", "https://sqs.example.com/queue")
    mock_wl_service.process_cancellation.return_value = None

    wh_handler._advance_waitlist("tenant-abc", "svc-001", "bkg-001")

    mock_wl_service.mark_contacted.assert_not_called()


def test_advance_waitlist_no_queue_url(mock_env, monkeypatch):
    monkeypatch.setattr(wh_handler, "WHATSAPP_SENDER_QUEUE_URL", "")

    wh_handler._advance_waitlist("tenant-abc", "svc-001", "bkg-001")


# --- _create_booking_from_waitlist ---

@patch("backend.whatsapp_webhook.handler.booking_service")
@patch("backend.whatsapp_webhook.handler.client_repo")
@patch("backend.whatsapp_webhook.handler.booking_repo")
def test_create_booking_from_waitlist_success(mock_booking_repo, mock_client_repo, mock_booking_svc, mock_env):
    original = MagicMock()
    original.service_id = "svc-001"
    original.provider_id = "pro-001"
    original.start_time = "2026-06-01T14:00:00"
    original.end_time = "2026-06-01T15:00:00"
    mock_booking_repo.get_by_id.return_value = original

    client_info = MagicMock()
    client_info.first_name = "Ana"
    client_info.last_name = "Torres"
    client_info.email = "ana@example.com"
    client_info.phone = "+56911111111"
    mock_client_repo.find_by_phone.return_value = client_info

    wh_handler._create_booking_from_waitlist("whatsapp:+56911111111", "tenant-abc", "bkg-001")

    mock_booking_svc.create_booking.assert_called_once()
    call_kwargs = mock_booking_svc.create_booking.call_args.kwargs
    assert call_kwargs["ignore_availability"] is True
    assert call_kwargs["client_first_name"] == "Ana"


@patch("backend.whatsapp_webhook.handler.booking_repo")
def test_create_booking_from_waitlist_no_booking_id(mock_booking_repo, mock_env):
    wh_handler._create_booking_from_waitlist("whatsapp:+56911111111", "tenant-abc", "")
    mock_booking_repo.get_by_id.assert_not_called()


@patch("backend.whatsapp_webhook.handler.client_repo")
@patch("backend.whatsapp_webhook.handler.booking_repo")
def test_create_booking_from_waitlist_client_not_found(mock_booking_repo, mock_client_repo, mock_env):
    mock_booking_repo.get_by_id.return_value = MagicMock()
    mock_client_repo.find_by_phone.return_value = None

    wh_handler._create_booking_from_waitlist("whatsapp:+56911111111", "tenant-abc", "bkg-001")

    assert mock_client_repo.find_by_phone.call_count == 2


@patch("backend.whatsapp_webhook.handler.booking_repo")
def test_create_booking_from_waitlist_booking_not_found(mock_booking_repo, mock_env):
    mock_booking_repo.get_by_id.return_value = None

    wh_handler._create_booking_from_waitlist("whatsapp:+56911111111", "tenant-abc", "bkg-001")

