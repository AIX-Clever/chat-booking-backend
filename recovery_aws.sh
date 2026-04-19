#!/bin/bash
echo "exports.handler = async (event) => { return 'OK'; };" > index.js
zip -q dummy.zip index.js

# Crear el rol de recuperación
aws iam create-role --role-name DummyCFNRecoveryRole \
  --assume-role-policy-document '{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Principal":{"Service":"lambda.amazonaws.com"},"Action":"sts:AssumeRole"}]}' 2>/dev/null || true

export ROLE_ARN="arn:aws:iam::834088498821:role/DummyCFNRecoveryRole"
echo "Esperando a que AWS propague el rol..."
sleep 10

aws lambda create-function --function-name ChatBooking-dev-Subscript-DowngradeFunctionD67E4A0-IVFZm3gfKUA4 --runtime nodejs20.x --role $ROLE_ARN --handler index.handler --zip-file fileb://dummy.zip
aws lambda create-function --function-name ChatBooking-dev-Subscript-FintocWebhookFunction0F9-OnCsRrYV8XRB --runtime nodejs20.x --role $ROLE_ARN --handler index.handler --zip-file fileb://dummy.zip
aws lambda create-function --function-name ChatBooking-dev-Subscript-ListInvoicesFunctionE2A8-eu1vUEVvfWe8 --runtime nodejs20.x --role $ROLE_ARN --handler index.handler --zip-file fileb://dummy.zip
aws lambda create-function --function-name ChatBooking-dev-Subscript-SiiStatusSyncFunction637-svoKzlslbreD --runtime nodejs20.x --role $ROLE_ARN --handler index.handler --zip-file fileb://dummy.zip
aws lambda create-function --function-name ChatBooking-dev-Subscript-SubscriptionWorkerFuncti-Her7d6FnuZBt --runtime nodejs20.x --role $ROLE_ARN --handler index.handler --zip-file fileb://dummy.zip
aws lambda create-function --function-name ChatBooking-dev-Subscript-WebhookIngestorFunctionE-CLc6x3hPVF1u --runtime nodejs20.x --role $ROLE_ARN --handler index.handler --zip-file fileb://dummy.zip
aws lambda create-function --function-name ChatBooking-dev-Subscript-WebhookProcessorFunction-XPkccT6TZeDo --runtime nodejs20.x --role $ROLE_ARN --handler index.handler --zip-file fileb://dummy.zip

aws cloudformation continue-update-rollback --stack-name ChatBooking-dev-Subscriptions --region us-east-2
echo "Comando Rollback enviado. CloudFormation debería volver a UPDATE_ROLLBACK_COMPLETE."
