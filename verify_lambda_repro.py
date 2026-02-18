import os
import boto3
import json
from decimal import Decimal

# Mock environment variables
os.environ['CLIENTS_TABLE'] = 'ChatBooking-Clients'
os.environ['CLIENT_AUDIT_LOGS_TABLE'] = 'ChatBooking-ClientAuditLogs'

import sys
import os
sys.path.append(os.getcwd())
sys.path.append(os.path.join(os.getcwd(), 'shared'))
sys.path.append(os.path.join(os.getcwd(), 'clients'))

# Import handler
from clients.handler import list_clients

# Custom JSON encoder for Decimal
class DecimalEncoder(json.JSONEncoder):
    def default(self, o):
        if isinstance(o, Decimal):
            return float(o)
        return super(DecimalEncoder, self).default(o)

def test_list_clients():
    print("Testing list_clients...")
    try:
        result = list_clients('1109a560')
        print(json.dumps(result, cls=DecimalEncoder, indent=2))
        
        # Check specifically for identifiers
        for client in result:
            if 'identifiers' not in client:
                print(f"ERROR: Client {client.get('id')} missing identifiers!")
            elif client['identifiers'] is None:
                print(f"ERROR: Client {client.get('id')} identifiers is None!")
            else:
                print(f"SUCCESS: Client {client.get('id')} has identifiers: {client['identifiers']}")
                
    except Exception as e:
        print(f"FAILED: {str(e)}")

if __name__ == "__main__":
    test_list_clients()
