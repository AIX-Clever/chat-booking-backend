
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
