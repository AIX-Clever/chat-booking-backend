---
trigger: always_on
---

# Reglas de Oro (Golden Rules)

Estas reglas deben ser seguidas estrictamente por todos los agentes y desarrolladores que trabajen en este proyecto.

1. **Documentation First**: Siempre revisar la documentación (`REPOSITORIES.md` y `chat-booking-docs`) antes de tomar decisiones de arquitectura.
2. **Despliegue Exclusivo por GitHub Actions / CI-CD**: Todo despliegue a producción (o cualquier entorno) se realiza **únicamente** a través de pipelines de GitHub Actions. Nunca realizar despliegues manuales locales (ej. `cdk deploy`).
3. **Tests & Coverage**: Al modificar código y validar que es funcional en localhost, actualizar los tests correspondientes y verificar que la cobertura se mantenga sobre el 80%.
4. **Documentation Updates**: Tras cualquier modificación de código relevante, actualizar siempre la documentación.
5. **Linting Check**: Antes de ejecutar un `git push`, correr y aprobar el linter (`npm run lint` o equivalente) para prevenir fallos en el build.
6. **Versionado Visible en Frontend (Debug)**: Cuando se debugeen problemas de caché o despliegues en frontend, agregar o actualizar un indicador de versión visual (ej. `v0.1 - timestamp`) en la UI para confirmar qué versión está viendo el usuario.
7. **Estrategia de Ambientes**: En la cuenta AWS actual (desarrollo), todos los workflows deben desplegar únicamente al ambiente DEV. No crear múltiples stacks temporales.
8. **Commits Ordenados y Atómicos**: Los commits deben estar ordenados, ser atómicos (una sola responsabilidad por commit) y estar bien descritos. Utilizar GitHub CLI (`gh`) si aplica.
9. **Uso de GitHub CLI**: Utilizar el CLI `gh` para revisar temas relacionados con repositorios y flujos de trabajo en GitHub de ser necesario.
10. **Arquitectura de Microservicios**: El proyecto utiliza arquitectura hexagonal separada por layers y lambdas. Asegurar que todo código cumpla con esta estructura.
11. **Sincronización de Shared Folder**: Cualquier cambio en la carpeta `shared/` del backend debe ser sincronizado 1:1 con el repositorio `chat-booking-layers` antes de intentar desplegar el backend. Consultar la [Guía de Sincronización](guides/shared-folder-synchronization.md).
12. **Región AWS**: Todos los recursos del proyecto (Lambda, AppSync, DynamoDB, CloudFormation stacks) están desplegados en `us-east-2` (Ohio). Siempre usar esta región al interactuar con AWS CLI, SDKs o consola. La única excepción es CloudFront, que opera globalmente desde `us-east-1`.
13. **Orden de Despliegue Obligatorio**: Siempre deployar en este orden: `chat-booking-layers` → `chat-booking-backend` → `chat-booking-admin`. Nunca saltarse el layer si hubo cambios en `shared/`. El backend valida el hash del layer antes de desplegarse — si el layer no está actualizado primero, el deploy del backend fallará.
14. **Orden de Ramas Obligatorio: `dev` → `qa` → `prod`**: Todo commit y push va primero a `dev`. Luego merge a `qa`, luego a `prod`. Nunca commitear directamente a `qa`, `stg` o `prod`, ni sugerir merge a `prod` sin pasar por `qa`. Si accidentalmente se commitea a otra rama, hacer cherry-pick a `dev` de inmediato. **Sin excepciones para emergencias de CI**: incluso si el deploy de `prod` está bloqueado por un bug del pipeline, el fix debe ir `dev → qa → prod`. La única excepción válida es si el propio pipeline de `qa` está roto y no puede recibir el commit.
15. **No Renombrar Atributos que sean Sort Key de un GSI en DynamoDB**: En DynamoDB no se puede renombrar la sort key de un GSI existente sin recrearlo. Si se necesita renombrar, mantener el atributo original (con el nombre del GSI) Y agregar el nuevo atributo con el nombre deseado. Ante cualquier cambio de nombre de atributo en DynamoDB, verificar primero si ese atributo es PK, SK o sort key de algún GSI.