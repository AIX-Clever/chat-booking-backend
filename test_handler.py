import sys
import os
import json
sys.path.append(os.getcwd())

os.environ["SERVICES_TABLE"] = "ChatBooking-Services"
os.environ["PROVIDERS_TABLE"] = "ChatBooking-Providers"
os.environ["BOOKINGS_TABLE"] = "ChatBooking-Bookings"
os.environ["AVAILABILITY_TABLE"] = "ChatBooking-ProviderAvailability"
os.environ["AWS_DEFAULT_REGION"] = "us-east-1"

from availability.handler import lambda_handler

event = {
    "info": {
        "fieldName": "getAvailableSlots"
    },
    "arguments": {
        "input": {
            "serviceId": "svc_808e04c7",
            "providerId": "pro_2df69ab1",
            "from": "2026-03-01T00:00:00.000Z",
            "to": "2026-03-31T23:59:59.999Z"
        }
    },
    "request": {
        "headers": {
            "x-tenant-id": "583155ee"
        }
    },
    "identity": None
}

class Context:
    pass

if __name__ == "__main__":
    result = lambda_handler(event, Context())
    print(json.dumps(result, indent=2))
