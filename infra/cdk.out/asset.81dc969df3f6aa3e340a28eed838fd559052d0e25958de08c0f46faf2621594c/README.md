# Chat Agent Lambda — FSM Conversacional

Lambda principal que maneja el flujo conversacional del chat agéntico.

## 📋 Responsabilidades

- Mantener estado de conversaciones (FSM)
- Detectar intenciones del usuario
- Orquestar llamadas a otras Lambdas
- Generar respuestas contextuales

## 🔧 Variables de entorno

```
TENANTS_TABLE=Tenants
CONVERSATION_STATE_TABLE=ConversationState
BEDROCK_MODEL_ID=anthropic.claude-3-sonnet-20240229-v1:0
```

## 📦 Dependencias

Ver `requirements.txt`
