# Booking Lambda

Lambda para crear y cancelar reservas de forma segura, evitando overbooking.

## Operaciones

- `createBooking(tenantId, serviceId, providerId, startTime, endTime, customerInfo)` → Booking
- `cancelBooking(tenantId, bookingId)` → Booking actualizado
- `confirmBooking(tenantId, bookingId)` → Booking confirmado

## Prevención de Overbooking

Usa `ConditionExpression` en DynamoDB:

```python
ConditionExpression='attribute_not_exists(PK) AND attribute_not_exists(SK)'
```

Esto garantiza que no se pueda crear una reserva si ya existe otra en el mismo horario para el mismo profesional.

## Estructura

```
booking/
├── handler.py          # Entry point Lambda
├── create.py           # Crear reserva
├── cancel.py           # Cancelar reserva
├── validate.py         # Validaciones
└── requirements.txt
```

## Variables de entorno

- `DYNAMODB_BOOKINGS_TABLE`
- `DYNAMODB_SERVICES_TABLE`
- `DYNAMODB_PROVIDERS_TABLE`
