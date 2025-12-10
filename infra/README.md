# CDK Stacks

Aquí se definen los stacks de AWS CDK para desplegar toda la infraestructura.

## Estructura

```
cdk/
├── bin/
│   └── app.ts              # Entry point
├── lib/
│   ├── database-stack.ts   # DynamoDB tables
│   ├── api-stack.ts        # AppSync GraphQL API
│   ├── auth-stack.ts       # Cognito User Pools
│   ├── lambda-stack.ts     # Lambda functions
│   └── cdn-stack.ts        # CloudFront + S3
├── package.json
├── tsconfig.json
└── cdk.json
```

## Stacks disponibles

### 1. DatabaseStack
Crea las 7 tablas DynamoDB:
- Tenants
- TenantApiKeys
- Services
- Providers
- ProviderAvailability
- Bookings
- ConversationState

### 2. ApiStack
- GraphQL API (AppSync)
- Data sources (DynamoDB)
- Resolvers (Lambda)
- API Keys

### 3. AuthStack
- Cognito User Pool
- User Pool Client
- Identity Pool
- IAM Roles

### 4. LambdaStack
- chat_agent (Python 3.9)
- catalog (Python 3.9)
- availability (Python 3.9)
- booking (Python 3.9)
- auth_resolver (Python 3.9)

### 5. CdnStack
- S3 Buckets
- CloudFront Distributions
- SSL Certificates

## Uso

```bash
npm install
cdk bootstrap
cdk deploy --all
```
