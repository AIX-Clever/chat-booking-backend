import boto3
import json
import time
import sys

# Color codes
GREEN = '\033[92m'
RED = '\033[91m'
RESET = '\033[0m'

def test_fsm_flow():
    client = boto3.client('lambda', region_name='us-east-1')
    function_name = 'ChatBooking-Backend-Dev-ChatAgentFunction' # Approximate name, need to verify
    
    # 1. Start Conversation
    print(f"1. Starting Conversation...")
    payload = {
        "field": "startConversation",
        "arguments": {
            "tenantId": "tenant-default", # Verify this ID
            "channel": "test-script"
        }
    }
    
    response = invoke_lambda(client, function_name, payload)
    if 'error' in response:
        print(f"{RED}Failed to start: {response['error']}{RESET}")
        return

    conv_id = response['conversation']['conversationId']
    print(f"{GREEN}Conversation Started: {conv_id}{RESET}")
    print(f"Msg: {response['response']['text']}")

    # 2. Select Service (Search -> List -> Select)
    # We need to find the service ID first or simulate selection
    # Assuming standard flow: The bot asked for help. We say "Reservar"
    
    print(f"\n2. Sending 'Reservar'...")
    response = send_message(client, function_name, conv_id, "Reservar Servicio", "flow_booking")
    print(f"Msg: {response['response'].get('text')}")
    
    # 3. Simulate Service Selection
    # Need a valid service ID from the response or hardcoded known one
    services = response['response'].get('options', [])
    if not services:
        print(f"{RED}No services found!{RESET}")
        return

    service_id = services[0]['value']
    print(f"\n3. Selecting Service: {services[0]['label']} ({service_id})")
    response = send_message(client, function_name, conv_id, "Quiero este", service_id)
    
    # 4. Select Provider
    providers = response['response'].get('options', [])
    if not providers:
        print(f"{RED}No providers found!{RESET}")
        # Note: If auto-selected (only 1 provider), we might be at slot selection already
        if response['response']['type'] == 'calendar':
            print(f"{GREEN}Auto-selected provider!{RESET}")
        else:
            return

    if response['response']['type'] != 'calendar':
        provider_id = providers[0]['value']
        print(f"\n4. Selecting Provider: {providers[0]['label']} ({provider_id})")
        response = send_message(client, function_name, conv_id, "Este", provider_id)

    # 5. Select Slot
    slots = response['response'].get('slots', [])
    if not slots:
        print(f"{RED}No slots available!{RESET}")
        return
        
    slot_start = slots[0]['start']
    print(f"\n5. Selecting Slot: {slot_start}")
    response = send_message(client, function_name, conv_id, slot_start, slot_start) # Value is the iso string
    
    # 6. Contact Info
    print(f"\n6. Sending Contact Info...")
    contact_data = {
        "clientName": "Test User",
        "clientEmail": "test@example.com",
        "clientPhone": "1234567890"
    }
    # This might require 'messageType': 'form_response' or similar depending on implementation
    # But checking handle_send_message, it reads userData
    
    response = send_message(client, function_name, conv_id, "Mis datos", contact_data)
    
    # 7. Confirm
    if response['response']['type'] == 'confirmation':
        print(f"\n7. Confirming Booking...")
        response = send_message(client, function_name, conv_id, "Confirmar", "confirm")
    
    # 8. Success?
    if response['response']['type'] == 'success':
        print(f"\n{GREEN}VICTORY! Booking Confirmed: {response['response']['booking']['bookingId']}{RESET}")
    else:
        print(f"\n{RED}Failed to confirm. Ended at state: {response['response']['type']}{RESET}")


def invoke_lambda(client, func_name, payload):
    # Try finding exact name if partial
    if 'ChatBooking' not in func_name:
        # List functions logic here? For now assume exact or passed correctly
        pass

    try:
        res = client.invoke(
            FunctionName=func_name,
            InvocationType='RequestResponse',
            Payload=json.dumps(payload)
        )
        response_payload = json.loads(res['Payload'].read())
        return response_payload
    except Exception as e:
        print(f"{RED}Lambda Invoke Error: {e}{RESET}")
        return {'error': str(e)}

def send_message(client, func_name, conv_id, text, value_or_data):
    user_data = None
    if isinstance(value_or_data, dict):
        user_data = value_or_data
    elif value_or_data:
        user_data = {'value': value_or_data}
        
    payload = {
        "field": "sendMessage",
        "arguments": {
            "tenantId": "tenant-default",
            "conversationId": conv_id,
            "message": text,
            "messageType": "text",
            "userData": user_data
        }
    }
    return invoke_lambda(client, func_name, payload)

if __name__ == "__main__":
    # Get Function Name argument
    if len(sys.argv) > 1:
        FUNCTION_NAME = sys.argv[1]
        print(f"Targeting function: {FUNCTION_NAME}")
        test_fsm_flow()
    else:
        print("Please provide function name as argument")
