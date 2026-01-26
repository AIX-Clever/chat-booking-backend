import json
import os
import sys
import urllib.request
import urllib.error
import re

# Configuration
LANDING_PAGE_PATH = "../chat-booking-landing/index.html"

def get_config_from_html():
    """
    Extracts configuration dynamically from the landing page HTML.
    This ensures we test with the EXACT same credentials as the frontend.
    """
    try:
        with open(LANDING_PAGE_PATH, "r") as f:
            content = f.read()
            
        api_url_match = re.search(r'data-api-url="([^"]+)"', content)
        api_key_match = re.search(r'data-public-key="([^"]+)"', content)
        tenant_id_match = re.search(r'data-tenant-id="([^"]+)"', content)
        
        if not api_url_match or not api_key_match or not tenant_id_match:
            print("❌ Could not find widget configuration in index.html")
            sys.exit(1)
            
        print(f"📄 Config loaded from {LANDING_PAGE_PATH}")
        return {
            "GRAPHQL_URL": api_url_match.group(1),
            "API_KEY": api_key_match.group(1),
            "TENANT_ID": tenant_id_match.group(1)
        }
    except FileNotFoundError:
        print(f"❌ Could not find {LANDING_PAGE_PATH}")
        sys.exit(1)

def make_request(config, query, variables):
    data = json.dumps({'query': query, 'variables': variables}).encode('utf-8')
    
    headers = {
        "x-api-key": config['API_KEY'],
        "x-tenant-id": config['TENANT_ID'],
        "Content-Type": "application/json",
        "User-Agent": "Python/3.11"
    }
    
    try:
        req = urllib.request.Request(config['GRAPHQL_URL'], data=data, headers=headers)
        with urllib.request.urlopen(req) as response:
            response_body = response.read().decode('utf-8')
            
            if response.status != 200:
                print(f"❌ Error calling AppSync: {response.status} - {response_body}")
                sys.exit(1)
            
            data = json.loads(response_body)
            if 'errors' in data:
                print(f"❌ GraphQL Error: {data['errors']}")
                sys.exit(1)
                
            return data['data']
            
    except urllib.error.HTTPError as e:
        print(f"❌ HTTP Error calling AppSync: {e.code} - {e.read().decode('utf-8')}")
        sys.exit(1)
    except urllib.error.URLError as e:
        print(f"❌ Connection Error: {e.reason}")
        sys.exit(1)

def start_conversation(config):
    print("💬 Starting new conversation...")
    query = """
    mutation StartConversation($input: StartConversationInput!) {
        startConversation(input: $input) {
            conversation {
                conversationId
            }
        }
    }
    """
    variables = {
        "input": {
            "channel": "WEB",
            "metadata": "{}"
        }
    }
    
    result = make_request(config, query, variables)
    conv_id = result['startConversation']['conversation']['conversationId']
    print(f"✅ Conversation Started: {conv_id}")
    return conv_id

def send_message(config, conversation_id, message_text):
    print(f"💬 Sending Message: '{message_text}'...")
    query = """
    mutation SendMessage($input: SendMessageInput!) {
        sendMessage(input: $input) {
            response
        }
    }
    """
    
    variables = {
        "input": {
            "conversationId": conversation_id,
            "message": message_text,
            "messageType": "TEXT",
            "userData": json.dumps({"force_rag": True})
        }
    }
    
    result = make_request(config, query, variables)
    raw_response = result['sendMessage']['response']
    print(f"DEBUG: RAW RESPONSE: {raw_response}")
    
    # response is AWSJSON (string), so parse it
    try:
        parsed_response = json.loads(raw_response)
        return parsed_response
    except json.JSONDecodeError:
        return {"text": raw_response} # Fallback if it's just string

def main():
    # 1. Get Config Dynamicallly
    config = get_config_from_html()

    print(f"🔐 API Key: {config['API_KEY'][:5]}...")
    print(f"🏢 Tenant ID: {config['TENANT_ID']}")
    print(f"🔗 URL: {config['GRAPHQL_URL'][:30]}...")

    # 2. Start Conversation
    conv_id = start_conversation(config)
    
    # 3. Send Query
    ai_response = send_message(config, conv_id, "What is the purpose of the test document?")
    
    print("\n🤖 AI Response:")
    print(json.dumps(ai_response, indent=2))
    
    # 4. Verify
    response_text = ai_response.get('text', str(ai_response))
    
    if "RAG ingestion verification" in response_text or "ingestion verification" in response_text or "test document" in response_text:
        print("\n✅ SUCCESS: RAG Retrieved correct context!")
    else:
        print("\n⚠️  WARNING: Response might not be from RAG context. Check logs.")

if __name__ == "__main__":
    main()
