# Catalog Lambda

Lambda para consultar servicios y profesionales del catálogo del tenant.

## Operaciones

- `searchServices(tenantId, query)` → Lista de servicios
- `listProvidersByService(tenantId, serviceId)` → Lista de profesionales
- `getService(tenantId, serviceId)` → Servicio específico
- `getProvider(tenantId, providerId)` → Profesional específico

## Estructura

```
catalog/
├── handler.py          # Entry point Lambda
├── services.py         # Lógica de servicios
├── providers.py        # Lógica de profesionales
└── requirements.txt
```

## Variables de entorno

- `DYNAMODB_SERVICES_TABLE`
- `DYNAMODB_PROVIDERS_TABLE`
