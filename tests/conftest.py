import boto3

# Pre-importing these ensures they are recognized as packages
# even if boto3.resource or boto3.client are patched later.
try:
    import boto3.dynamodb.transform
    import boto3.dynamodb.conditions
    import boto3.dynamodb.table
    import boto3.dynamodb.types
except ImportError:
    pass
