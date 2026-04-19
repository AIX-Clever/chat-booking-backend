import base64
import json
import boto3

def get_caf_manager_function_name(env_name="dev"):
    """Find the CAF Manager Lambda function name."""
    client = boto3.client('lambda', region_name='us-east-1')
    paginator = client.get_paginator('list_functions')
    for page in paginator.paginate():
        for fn in page['Functions']:
            if 'CafManagerFunction' in fn['FunctionName'] and env_name in fn['FunctionName']:
                return fn['FunctionName']
    return None

def test_upload_caf():
    print("MOCKING CAF XML...")
    dummy_xml = """<?xml version="1.0" encoding="ISO-8859-1"?>
<AUTORIZACION>
  <CAF version="1.0">
    <DA>
      <RE>76123456-7</RE>
      <RS>EMPRESA DE PRUEBA SPA</RS>
      <TD>39</TD>
      <RNG>
        <D>150</D>
        <H>200</H>
      </RNG>
      <FA>2026-01-01</FA>
    </DA>
    <FRMA algoritmo="SHA1withRSA">Fake Signature</FRMA>
  </CAF>
  <RSASK>Fake Key</RSASK>
  <RSAPUBK>Fake Pub Key</RSAPUBK>
</AUTORIZACION>"""

    b64_xml = base64.b64encode(dummy_xml.encode('iso-8859-1')).decode('utf-8')
    
    # Simulate the AppSync GraphQL Event payload
    event = {
        "arguments": {
            "base64Xml": b64_xml,
            "tipoDte": 39
        },
        "info": {
            "fieldName": "uploadCaf"
        },
        "identity": {
            "claims": {
                "custom:tenantId": "test-tenant-123"
            }
        }
    }
    
    print("FINDING LAMBDA FUNCTION...")
    function_name = get_caf_manager_function_name()
    if not function_name:
        print("FAILED: Could not find the CafManagerFunction. Make sure it's deployed.")
        return
        
    print(f"INVOKING {function_name}...")
    client = boto3.client('lambda', region_name='us-east-1')
    response = client.invoke(
        FunctionName=function_name,
        InvocationType='RequestResponse',
        Payload=json.dumps(event)
    )
    
    payload = json.loads(response['Payload'].read().decode('utf-8'))
    print("RESPONSE:", json.dumps(payload, indent=2))
    
    if payload.get("success") and payload.get("folioInicial") == 150 and payload.get("folioFinal") == 200:
        print("\n✅ Verification PASSED: XML was processed and saved to DynamoDB via Lambda!")
    else:
        print("\n❌ Verification FAILED: Did not get the expected folio numbers back.")

if __name__ == "__main__":
    try:
        test_upload_caf()
    except Exception as e:
        print(f"Error executing test: {e}")
        if "ExpiredToken" in str(e):
            print("\n🚨 Your AWS CLI Token is expired! Please run `aws sso login` or configure your credentials and try again.")
