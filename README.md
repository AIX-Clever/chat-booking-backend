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

## 📦 Build y Deploy

Ver `/plan/deployment/README.md` para instrucciones completas.

## 📚 Documentación

- [Arquitectura de Lambdas](../plan/architecture/lambdas.md)
- [Schema DynamoDB](../plan/architecture/dynamodb-schema.md)
- [Deployment](../plan/deployment/README.md)

<!-- Trigger Deploy: Sync with Layers -->
