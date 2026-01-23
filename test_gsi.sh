#!/bin/bash
# Quick test to verify slug-index GSI exists in DynamoDB
# Run with: bash test_gsi.sh

echo "🔍 Checking if slug-index GSI exists in ChatBooking-Tenants table..."

aws dynamodb describe-table \
  --table-name ChatBooking-Tenants \
  --region us-east-1 \
  --query 'Table.GlobalSecondaryIndexes[?IndexName==`slug-index`]' \
  --output json 2>&1

if [ $? -eq 0 ]; then
  echo "✅ GSI query executed successfully"
else
  echo "❌ Failed to query DynamoDB (check AWS credentials)"
fi
