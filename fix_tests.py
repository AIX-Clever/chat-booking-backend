import re
import os

with open("tests/unit/test_booking_service_new.py", "r") as f:
    text = f.read()
text = text.replace('client_name="Test",', 'client_first_name="Test",\n            client_last_name="Client",')
text = text.replace('client_name="Test Client",', 'client_first_name="Test",\n            client_last_name="Client",')
text = text.replace('name="Test",', 'given_name="Test",\n            family_name="Client",')
text = text.replace('name="Test Client"', 'given_name="Test", family_name="Client"')

with open("tests/unit/test_booking_service_new.py", "w") as f:
    f.write(text)

with open("tests/unit/test_metrics_integration.py", "r") as f:
    text = f.read()
text = text.replace('client_name="Test User",', 'client_first_name="Test",\n            client_last_name="User",')
with open("tests/unit/test_metrics_integration.py", "w") as f:
    f.write(text)

with open("tests/unit/test_past_booking.py", "r") as f:
    text = f.read()
text = text.replace('client_name="Test User",', 'client_first_name="Test",\n            client_last_name="User",')
with open("tests/unit/test_past_booking.py", "w") as f:
    f.write(text)

with open("tests/integration/test_service_limits.py", "r") as f:
    text = f.read()
text = text.replace('client_name=f"Client {i}",', 'client_first_name=f"Client",\n                client_last_name=f"{i}",')
with open("tests/integration/test_service_limits.py", "w") as f:
    f.write(text)
