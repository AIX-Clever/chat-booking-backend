"""
Unit tests for shared utilities
"""

import pytest
from datetime import datetime
from shared.utils import (
    generate_id,
    hash_api_key,
    generate_api_key,
    lambda_response,
    success_response,
    error_response,
    parse_iso_datetime,
    to_iso_string,
    add_minutes,
    Logger
)


class TestIdGeneration:
    """Test ID generation utilities"""
    
    def test_generate_id_with_prefix(self):
        id1 = generate_id("svc")
        id2 = generate_id("svc")
        
        assert id1.startswith("svc_")
        assert id2.startswith("svc_")
        assert id1 != id2  # Should be unique
        assert len(id1) > 4
    
    def test_generate_id_uniqueness(self):
        ids = [generate_id("test") for _ in range(100)]
        assert len(set(ids)) == 100  # All unique


class TestApiKeyUtilities:
    """Test API key utilities"""
    
    def test_hash_api_key_consistency(self):
        key = "test_api_key_123"
        hash1 = hash_api_key(key)
        hash2 = hash_api_key(key)
        
        assert hash1 == hash2
        assert len(hash1) == 64  # SHA256 produces 64 hex chars
    
    def test_different_keys_produce_different_hashes(self):
        hash1 = hash_api_key("key1")
        hash2 = hash_api_key("key2")
        
        assert hash1 != hash2
    
    def test_generate_api_key(self):
        key1 = generate_api_key()
        key2 = generate_api_key()
        
        assert len(key1) >= 32
        assert len(key2) >= 32
        assert key1 != key2


class TestLambdaResponses:
    """Test Lambda response builders"""
    
    def test_lambda_response_structure(self):
        response = lambda_response({"test": "data"}, 200)
        
        assert response["statusCode"] == 200
        assert "body" in response
        assert "headers" in response
        assert response["headers"]["Content-Type"] == "application/json"
    
    def test_success_response(self):
        response = success_response({"result": "ok"})
        
        assert response["statusCode"] == 200
        body = eval(response["body"])  # Parse JSON string
        assert body["result"] == "ok"
    
    def test_error_response(self):
        response = error_response("Something went wrong", 500)
        
        assert response["statusCode"] == 500
        body = eval(response["body"])
        assert "error" in body
        assert body["error"] == "Something went wrong"


class TestDateTimeUtilities:
    """Test datetime utilities"""
    
    def test_parse_iso_datetime(self):
        iso_string = "2025-12-15T10:30:00Z"
        dt = parse_iso_datetime(iso_string)
        
        assert isinstance(dt, datetime)
        assert dt.year == 2025
        assert dt.month == 12
        assert dt.day == 15
        assert dt.hour == 10
        assert dt.minute == 30
    
    def test_parse_iso_datetime_with_milliseconds(self):
        iso_string = "2025-12-15T10:30:00.123Z"
        dt = parse_iso_datetime(iso_string)
        
        assert isinstance(dt, datetime)
    
    def test_to_iso_string(self):
        dt = datetime(2025, 12, 15, 10, 30, 0)
        iso_string = to_iso_string(dt)
        
        assert iso_string == "2025-12-15T10:30:00Z"
    
    def test_add_minutes(self):
        dt = datetime(2025, 12, 15, 10, 0, 0)
        new_dt = add_minutes(dt, 30)
        
        assert new_dt.hour == 10
        assert new_dt.minute == 30
    
    def test_add_minutes_crosses_hour(self):
        dt = datetime(2025, 12, 15, 10, 45, 0)
        new_dt = add_minutes(dt, 30)
        
        assert new_dt.hour == 11
        assert new_dt.minute == 15


class TestLogger:
    """Test Logger utility"""
    
    def test_logger_initialization(self):
        logger = Logger(service_name="test_service")
        assert logger.service_name == "test_service"
    
    def test_logger_info(self, capsys):
        logger = Logger()
        logger.info("Test message", user_id="123", action="test")
        
        captured = capsys.readouterr()
        assert "Test message" in captured.out
        assert "INFO" in captured.out
    
    def test_logger_error(self, capsys):
        logger = Logger()
        logger.error("Error occurred", error_code="ERR_001")
        
        captured = capsys.readouterr()
        assert "Error occurred" in captured.out
        assert "ERROR" in captured.out
