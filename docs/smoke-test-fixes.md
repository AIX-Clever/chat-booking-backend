# Fixes pendientes — Smoke Test Dev (2026-05-12)

Problemas detectados durante el smoke test del pipeline de notificaciones en dev.
Ordenados por prioridad: 🔴 bloqueante → 🟡 IAM → 🟢 ruido.

---

## 🔴 Bloqueantes para envío real

### 1. SES Configuration Set no existe en dev
- **Error**: `Configuration set <ChatBooking-dev> does not exist`
- **Dónde falla**: BookingFunction (email on_booking) y NotificationSchedulerFunction (email hours_before)
- **Causa**: CDK setea `SES_CONFIGURATION_SET: ChatBooking-${envName}` en commonProps pero nunca crea el recurso SES ni verifica identidades
- **Estado actual**: 0 configuration sets, 0 identidades verificadas en cuenta dev
- **Fix**:
  1. Crear `CfnConfigurationSet` en CDK para dev/qa/prod
  2. Verificar dominio `mail.holalucia.cl` en SES (o al menos el email `no-reply@mail.holalucia.cl`)
- **Archivos**: `infra/lib/` (nuevo stack o recurso SES)

### 2. `SES_SENDER_EMAIL` no llega al NotificationScheduler
- **Error**: email no se envía, `sender = ""` en `_send_email()`
- **Causa**: `SES_SENDER_EMAIL` solo está en el env del BookingFunction (línea 277 lambda-stack.ts), no en commonProps
- **Fix**: Agregar `SES_SENDER_EMAIL: 'no-reply@mail.holalucia.cl'` al env del `NotificationSchedulerFunction` en CDK
- **Archivo**: `infra/lib/lambda-stack.ts` ~línea 1184

### 3. Cuota WhatsApp = 0 en tenant de dev
- **Error**: `"WhatsApp pre-paid quota exhausted", "quota": 0`
- **Causa**: El tenant de prueba no tiene créditos cargados
- **Fix**: Recargar créditos desde el panel de administración (no es bug de código)
- **Nota**: Sin créditos el WhatsappSender descarta el mensaje silenciosamente

---

## 🟡 IAM faltantes

### 4. `WhatsappSenderFunction` → `dynamodb:UpdateItem` en `ChatBooking-TenantUsage`
- **Error**: `AccessDeniedException: UpdateItem on ChatBooking-TenantUsage`
- **Causa**: La función intenta registrar métrica de cuota agotada pero no tiene permiso de escritura
- **Fix CDK**: `props.tenantUsageTable.grantWriteData(this.whatsappSenderFunction)`
- **Archivo**: `infra/lib/lambda-stack.ts`

### 5. `BookingFunction` → `dynamodb:GetItem` en `ChatBooking-UserRoles`
- **Error**: `AccessDeniedException: GetItem on ChatBooking-UserRoles`
- **Causa**: `enforce_not_readonly()` hace GetItem pero la función no tiene el permiso IAM
- **Impacto**: No bloqueante (error swallowed), pero ruido en cada reserva
- **Fix CDK**: `props.userRolesTable.grantReadData(this.bookingFunction)`
- **Archivo**: `infra/lib/lambda-stack.ts`

---

## 🟢 Ruido (no bloqueante)

### 6. `WhatsappSenderQueue` recibe eventos `BOOKING_CONFIRMED`
- **Síntoma**: WhatsappSender recibe 2 records por invocación — uno `BOOKING_CONFIRMED` (descartado como "invalid payload") y uno `WHATSAPP_SEND` (procesado)
- **Causa**: La suscripción SNS de `ChatBooking-WhatsappSenderQueue` no tiene `filterPolicy` configurado, por lo que recibe todos los eventos del topic
- **Fix CDK**: Agregar filtro `event_type: ['WHATSAPP_SEND']` en la suscripción SQS del topic
- **Archivo**: `infra/lib/lambda-stack.ts` (suscripción de WhatsappSenderQueue al whatsappNotificationTopic)

---

## Estado del pipeline (post smoke test)

| Etapa | Estado | Detalle |
|-------|--------|---------|
| BookingFunction → SNS publish | ✅ | BOOKING_CONFIRMED publicado correctamente |
| WhatsappScheduler → parseo SNS | ✅ | Fix `_parse_record` para formato SNS directo |
| WhatsappScheduler → on_booking publish | ✅ | WHATSAPP_SEND publicado a SNS |
| WhatsappScheduler → remind_24h skip | ✅ | Correctamente skipeado (reserva < 24h) |
| NotificationScheduler → procesado | ✅ | processed: 1, errors: 0 |
| WhatsappSenderFunction → recibe mensaje | ✅ | Llega vía SQS con payload correcto |
| WhatsappSenderFunction → envío real | ❌ | Bloqueado por cuota = 0 (#3) |
| Email on_booking | ❌ | Bloqueado por SES config set (#1) |
| Email hours_before | ❌ | Bloqueado por SES config set (#1) + sender email (#2) |
