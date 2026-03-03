import unittest
from datetime import datetime, timezone
from shared.domain.entities import Booking, TenantId, CustomerInfo, BookingStatus, PaymentStatus
from shared.infrastructure.dynamodb_repositories import DynamoDBBookingRepository
from booking.handler import booking_to_dict

class TestDteSchemaMapping(unittest.TestCase):
    def setUp(self):
        self.tenant_id = TenantId("tenant-123")
        self.customer_info = CustomerInfo(
            customer_id="cust-123",
            given_name="Test", family_name="Client",
            email="test@example.com",
            phone="+56912345678"
        )
        self.booking = Booking(
            booking_id="bk-123",
            tenant_id=self.tenant_id,
            service_id="svc-1",
            provider_id="prov-1",
            customer_info=self.customer_info,
            start_time=datetime(2026, 2, 24, 10, 0, tzinfo=timezone.utc),
            end_time=datetime(2026, 2, 24, 11, 0, tzinfo=timezone.utc),
            status=BookingStatus.CONFIRMED,
            payment_status=PaymentStatus.PAID,
            total_amount=15000.0,
            dte_folio="12345",
            dte_pdf_url="https://s3.amazonaws.com/bucket/dte-12345.pdf"
        )

    def test_booking_entity_dte_fields(self):
        """Verify that Booking entity correctly holds DTE fields"""
        self.assertEqual(self.booking.dte_folio, "12345")
        self.assertEqual(self.booking.dte_pdf_url, "https://s3.amazonaws.com/bucket/dte-12345.pdf")

    def test_booking_to_dict_mapping(self):
        """Verify that booking_to_dict (API handler mapping) includes DTE fields for GraphQL"""
        result = booking_to_dict(self.booking)
        
        # Verify DTE fields match the GraphQL schema names
        self.assertEqual(result["dteFolio"], "12345")
        self.assertEqual(result["dtePdfUrl"], "https://s3.amazonaws.com/bucket/dte-12345.pdf")
        
        # Verify other critical fields
        self.assertEqual(result["bookingId"], "bk-123")
        self.assertEqual(result["status"], "CONFIRMED")

    def test_repository_item_mapping(self):
        """Verify that DynamoDBBookingRepository correctly maps DTE fields to/from internal items"""
        # We mock the repository to use its internal mapping methods
        repo = DynamoDBBookingRepository(table_name="TestTable")
        
        # 1. Test Entity to Item (simulated via part of save method logic)
        # In repositories.py, the item is constructed manually in save()
        item = {
            "bookingId": self.booking.booking_id,
            "tenantId": str(self.booking.tenant_id),
            "dteFolio": self.booking.dte_folio,
            "dtePdfUrl": self.booking.dte_pdf_url,
            "status": self.booking.status.value,
            "paymentStatus": self.booking.payment_status.value,
            "start": self.booking.start_time.isoformat(),
            "endTime": self.booking.end_time.isoformat(),
            "createdAt": self.booking.created_at.isoformat(),
            "serviceId": self.booking.service_id,
            "providerId": self.booking.provider_id,
        }
        
        # 2. Test Item to Entity
        entity = repo._item_to_entity(item)
        
        self.assertEqual(entity.dte_folio, "12345")
        self.assertEqual(entity.dte_pdf_url, "https://s3.amazonaws.com/bucket/dte-12345.pdf")

if __name__ == "__main__":
    unittest.main()
