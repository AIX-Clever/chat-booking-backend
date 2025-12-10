# Auth Resolver Lambda

Lambda para resolver `tenantId` desde una API Key en los headers de AppSync.

## Flujo

1. Recibir `x-api-key` desde AppSync
2. Calcular hash SHA256
3. Buscar en `TenantApiKeys` (GSI por hash)
4. Validar estado, orígenes permitidos, rate limit
5. Retornar `tenantId` en el contexto

## Estructura

```
auth_resolver/
├── handler.py          # Entry point Lambda
├── api_keys.py         # Resolver API Key → tenantId
└── requirements.txt
```

## Input

```json
{
  "authorizationToken": "api_key_here",
  "requestContext": {
    "sourceIp": "1.2.3.4",
    "requestId": "req_123"
  }
}
```

## Output

```json
{
  "isAuthorized": true,
  "resolverContext": {
    "tenantId": "andina"
  }
}
```

## Variables de entorno

- `DYNAMODB_TENANT_API_KEYS_TABLE`
