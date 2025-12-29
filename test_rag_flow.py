import requests
import json
import os
import sys

# Configuration - FILL THESE OR SET ENV VARS
GRAPHQL_URL = os.environ.get('APPSYNC_GRAPHQL_URL')
ID_TOKEN = os.environ.get('COGNITO_ID_TOKEN')

def get_upload_url(file_name, content_type):
    """
    Call mutation getUploadUrl to get a presigned S3 URL
    """
    query = """
    mutation GetUploadUrl($fileName: String!, $contentType: String!) {
        getUploadUrl(fileName: $fileName, contentType: $contentType)
    }
    """
    
    variables = {
        "fileName": file_name,
        "contentType": content_type
    }
    
    headers = {
        "Authorization": ID_TOKEN,
        "Content-Type": "application/json"
    }
    
    print(f"🔄 Requesting Presigned URL for {file_name}...")
    
    response = requests.post(
        GRAPHQL_URL,
        json={'query': query, 'variables': variables},
        headers=headers
    )
    
    if response.status_code != 200:
        print(f"❌ Error calling AppSync: {response.text}")
        sys.exit(1)
        
    data = response.json()
    if 'errors' in data:
        print(f"❌ GraphQL Error: {data['errors']}")
        sys.exit(1)
        
    return json.loads(data['data']['getUploadUrl'])

def upload_file_to_s3(presigned_url, file_path, content_type):
    """
    Upload file using the presigned URL via PUT
    """
    print(f"🔄 Uploading {file_path} to S3...")
    
    with open(file_path, 'rb') as f:
        response = requests.put(
            presigned_url,
            data=f,
            headers={'Content-Type': content_type}
        )
        
    if response.status_code == 200:
        print("✅ Upload Successful!")
    else:
        print(f"❌ Upload Failed: {response.status_code} - {response.text}")
        sys.exit(1)

def main():
    if not GRAPHQL_URL or not ID_TOKEN:
        print("\n⚠️  MISSING CONFIGURATION ⚠️")
        print("Please set the following environment variables:")
        print("  export APPSYNC_GRAPHQL_URL='https://...appsync-api...amazonaws.com/graphql'")
        print("  export COGNITO_ID_TOKEN='eyJra...' (JWT ID Token from Admin Panel)")
        return

    # Create a dummy test file
    test_file = "test_document.txt"
    with open(test_file, "w") as f:
        f.write("This is a test document for RAG ingestion verification.")

    try:
        # 1. Get URL
        response_data = get_upload_url(test_file, "text/plain")
        presigned_url = response_data['uploadUrl']
        print(f"📝 Got Presigned URL: {presigned_url[:50]}...")
        
        # 2. Upload
        upload_file_to_s3(presigned_url, test_file, "text/plain")
        
        print("\n🚀 Verification Workflow Complete!")
        print("Next steps: Check CloudWatch logs for 'IngestionFunction' to confirm processing.")
        
    finally:
        if os.path.exists(test_file):
            os.remove(test_file)

if __name__ == "__main__":
    main()
