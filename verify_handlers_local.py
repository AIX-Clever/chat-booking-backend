import sys
import os
import json
from unittest.mock import MagicMock
from datetime import datetime, UTC

# Mock AWS environment
os.environ['DOCUMENTS_BUCKET'] = 'mock-bucket'
os.environ['DOCUMENTS_TABLE'] = 'mock-table'
os.environ['DB_ENDPOINT'] = 'mock-endpoint'
os.environ['DB_SECRET_ARN'] = 'mock-secret'
os.environ['AWS_DEFAULT_REGION'] = 'us-east-1'

# Mock boto3 before importing handlers
import boto3
boto3.client = MagicMock()
boto3.resource = MagicMock()

# Mock repositories to avoid real DB calls
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'chat_agent'))

try:
    print("1. Importing Chat Handler...")
    from chat_agent import handler
    from shared.domain.entities import TenantId, Conversation, ConversationState, Workflow, WorkflowStep, Service, Provider
    
    # Setup Mocks
    mock_service_repo = MagicMock()
    mock_provider_repo = MagicMock()
    mock_workflow_repo = MagicMock()
    mock_conversation_repo = MagicMock()
    
    # Inject mocks into handler dependencies (singleton hack)
    handler.service_repo = mock_service_repo
    handler.provider_repo = mock_provider_repo
    handler.workflow_repo = mock_workflow_repo
    handler.conversation_repo = mock_conversation_repo
    
    # Also update the service instance inside handler
    handler.chat_agent_service.service_repo = mock_service_repo
    handler.chat_agent_service.provider_repo = mock_provider_repo
    handler.chat_agent_service.workflow_repo = mock_workflow_repo
    handler.chat_agent_service.conversation_repo = mock_conversation_repo
    handler.chat_agent_service.workflow_engine.service_repo = mock_service_repo
    handler.chat_agent_service.workflow_engine.provider_repo = mock_provider_repo

    print("2. Setting up Mock Data...")
    tenant_id = TenantId("test-tenant")
    
    # Mock Service
    mock_service = Service(
        service_id="svc-1", tenant_id=tenant_id, name="Test Service", 
        description="Desc", category="Test", duration_minutes=30, price=100.0
    )
    mock_service_repo.list_by_tenant.return_value = [mock_service]
    
    # Mock Provider
    mock_provider = Provider(
        provider_id="prov-1", tenant_id=tenant_id, name="Dr. Test", 
        bio="Bio", service_ids=["svc-1"], timezone="UTC"
    )
    mock_provider_repo.list_by_tenant.return_value = [mock_provider]

    # Mock Workflow (Default Flow structure)
    steps = {
        "start": WorkflowStep("start", "MESSAGE", {"text": "Hello"}, "menu"),
        "menu": WorkflowStep("menu", "QUESTION", {"text": "Menu", "options": [{"label": "Book", "value": "book", "next": "flow_services"}]}),
        "flow_services": WorkflowStep("flow_services", "TOOL", {"tool": "start_booking_flow"}, "flow_providers"),
        "flow_providers": WorkflowStep("flow_providers", "TOOL", {"tool": "list_providers"}, "end"),
        "end": WorkflowStep("end", "MESSAGE", {"text": "Flow Ended"}, None)
    }
    mock_workflow = Workflow("wf-1", tenant_id, "Default", steps)
    mock_workflow_repo.get_by_id.return_value = mock_workflow
    mock_workflow_repo.list_by_tenant.return_value = [mock_workflow]

    # Mock Conversation
    conv_id = "conv-123"
    mock_conv = Conversation(conv_id, tenant_id, ConversationState.INIT)
    mock_conversation_repo.get_by_id.return_value = mock_conv
    mock_conversation_repo.save = MagicMock()

    print("\n3. Testing 'start_booking_flow' execution...")
    
    # Simulate processing step with 'start_booking_flow' tool
    # We call the engine directly or via service to be faster
    engine = handler.chat_agent_service.workflow_engine
    
    # Test 1: Execute Tool start_booking_flow
    step_services = steps["flow_services"]
    response = engine._execute_tool(mock_conv, step_services, mock_workflow)
    
    print(f"   Response Type: {response.get('type')}")
    if response.get('type') == 'service_selection' or response.get('type') == 'options':
        print("   ✅ start_booking_flow handled successfully (returned options/services)")
    else:
        print(f"   ❌ FAILED: Unexpected response: {response}")

    print("\n4. Testing 'list_providers' execution...")
    
    # Execute Tool list_providers
    step_providers = steps["flow_providers"]
    response_prov = engine._execute_tool(mock_conv, step_providers, mock_workflow)
    
    print(f"   Response Type: {response_prov.get('type')}")
    if response_prov.get('type') == 'provider_selection':
         print("   ✅ list_providers handled successfully")
    elif 'Auto-assigned' in str(response_prov) or response_prov.get('options'): # If optimization checked
         print("   ✅ list_providers handled (provider list returned)")
    else:
         print(f"   ❌ FAILED: Unexpected response: {response_prov}")

except ImportError as e:
    print(f"FAILED: Import Error - {e}")
except Exception as e:
    print(f"FAILED: Runtime Error - {e}")
    import traceback
    traceback.print_exc()
