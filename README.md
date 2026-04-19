# Backend Lambdas — SaaS Agentic Booking Chat

Este repositorio contiene todas las funciones Lambda (Python) que implementan la lógica de negocio del sistema.

## 📁 Estructura del proyecto

```
backend-lambdas/
├── chat_agent/              # Lambda del agente conversacional
│   ├── handler.py
│   ├── fsm.py
│   ├── states.py
│   ├── nlp.py
│   ├── responses.py
│   └── requirements.txt
│
├── catalog/                 # Lambda de catálogo
│   ├── handler.py
│   ├── services.py
│   ├── providers.py
│   └── requirements.txt
│
├── availability/            # Lambda de disponibilidad
│   ├── handler.py
│   ├── slots.py
│   ├── calendar.py
│   └── requirements.txt
│
├── booking/                 # Lambda de reservas
│   ├── handler.py
│   ├── create.py
│   ├── cancel.py
│   ├── validate.py
│   └── requirements.txt
│
├── auth_resolver/           # Lambda de autenticación
│   ├── handler.py
│   ├── api_keys.py
│   └── requirements.txt
│
├── profile_baker/           # Lambda de SEO (pre-render static HTML)
│   ├── handler.py
│   └── requirements.txt
│
├── shared/                  # Código compartido
│   ├── dynamodb.py
│   ├── utils.py
│   ├── models.py
│   └── constants.py
│
├── tests/
│   ├── unit/
│   ├── integration/
│   └── fixtures/
│
├── requirements-dev.txt     # Dependencias de desarrollo
├── pytest.ini
└── .env.example
```

## 🚀 Desarrollo local

```bash
# Instalar dependencias
pip install -r requirements-dev.txt

# Ejecutar tests
pytest tests/unit

# Ejecutar tests con coverage
pytest --cov=. --cov-report=html
```

## 📦 Configuración e Infraestructura (CDK)

El proyecto utiliza **AWS CDK (TypeScript)** almacenado en la carpeta `infra/`.

### ⚡ Prevención de CFN Export Locks mediante SSM

Para evitar los bloqueos (deadlocks) de `UPDATE_ROLLBACK_FAILED` en CloudFormation, los stacks evitan usar `Fn::ImportValue` para dependencias cruzadas.

En lugar de exportar propiedades directamente entre `SubscriptionStack` y `LambdaStack`:
1. `SubscriptionStack` publica sus recursos críticas (ej. nombre de tabla `subscriptions-table-name`) en **AWS Systems Manager Parameter Store (SSM)**.
2. `LambdaStack` utiliza un resolve at deploy-time para importar este string (o bien, `fromStringParameterName`).
3. El archivo `app.ts` declara dependencias topológicas (`lambdaStack.addDependency(subscriptionStack)`) asegurando un correcto orden de construcción de los parámetros SSM.

Ver la documentación extendida en `chat-booking-docs` -> `TROUBLESHOOTING.md`.

## 📦 Build y Deploy

Ver `/plan/deployment/README.md` para instrucciones completas.

## 📚 Documentación

- [Arquitectura de Lambdas](../plan/architecture/lambdas.md)
- [Schema DynamoDB](../plan/architecture/dynamodb-schema.md)
- [Deployment](../plan/deployment/README.md)

<!-- Trigger Deploy: Sync with Layers -->
