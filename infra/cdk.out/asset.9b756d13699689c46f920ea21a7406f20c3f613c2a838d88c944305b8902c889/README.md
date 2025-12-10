# Availability Lambda

Lambda para calcular slots disponibles para un servicio, profesional y rango de fechas.

## Operaciones

- `getAvailableSlots(tenantId, serviceId, providerId, fromDate, toDate)` → Lista de slots disponibles

## Lógica

1. Leer disponibilidad base del profesional (`ProviderAvailability`)
2. Leer duración del servicio
3. Generar slots candidatos cada 15 minutos
4. Filtrar slots ya ocupados (`Bookings`)
5. Retornar slots disponibles

## Estructura

```
availability/
├── handler.py          # Entry point Lambda
├── slots.py            # Generación de slots
├── calendar.py         # Lógica de calendarios
└── requirements.txt
```

## Variables de entorno

- `DYNAMODB_PROVIDER_AVAILABILITY_TABLE`
- `DYNAMODB_BOOKINGS_TABLE`
- `DYNAMODB_SERVICES_TABLE`
- `SLOT_INTERVAL_MINUTES` (default: 15)
