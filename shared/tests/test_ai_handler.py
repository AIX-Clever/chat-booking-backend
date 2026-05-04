import json
import pytest
from unittest.mock import MagicMock, patch


class TestAIHandlerTenantContext:
    def setup_method(self):
        self.mock_vector_repo = MagicMock()
        self.mock_vector_repo.search.return_value = [{"content": "Contexto de prueba"}]

    def _make_handler(self):
        with patch("boto3.client"):
            from shared.ai_handler import AIHandler
            handler = AIHandler(self.mock_vector_repo)
            return handler

    def _capture_system_prompt(self, handler, tenant_context=None):
        captured = {}

        def fake_invoke(**kwargs):
            body = json.loads(kwargs["body"])
            captured["system"] = body["system"]
            return {
                "body": MagicMock(read=lambda: json.dumps({
                    "content": [{"text": "respuesta"}]
                }).encode())
            }

        handler.bedrock_runtime.invoke_model = fake_invoke

        with patch.object(handler, "get_embedding", return_value=[0.1] * 1024):
            handler.generate_response("tenant-1", [], "hola", tenant_context=tenant_context)

        return captured.get("system", "")

    def test_system_prompt_without_tenant_context(self):
        handler = self._make_handler()
        prompt = self._capture_system_prompt(handler, tenant_context=None)

        assert "Eres un asistente de IA" in prompt
        assert "Contexto del negocio" not in prompt

    def test_system_prompt_with_profession(self):
        handler = self._make_handler()
        prompt = self._capture_system_prompt(handler, tenant_context={"profession": "Salud Mental"})

        assert "Rubro: Salud Mental" in prompt
        assert "Contexto del negocio" in prompt

    def test_system_prompt_with_specializations(self):
        handler = self._make_handler()
        context = {"profession": "Salud", "specializations": ["Psicología", "Nutrición"]}
        prompt = self._capture_system_prompt(handler, tenant_context=context)

        assert "Especialidades: Psicología, Nutrición" in prompt

    def test_system_prompt_with_empty_context(self):
        handler = self._make_handler()
        prompt = self._capture_system_prompt(handler, tenant_context={})

        assert "Contexto del negocio" not in prompt

    def test_system_prompt_with_empty_profession_and_specializations(self):
        handler = self._make_handler()
        prompt = self._capture_system_prompt(
            handler, tenant_context={"profession": "", "specializations": []}
        )

        assert "Contexto del negocio" not in prompt

    def test_rag_context_included_in_prompt(self):
        handler = self._make_handler()
        prompt = self._capture_system_prompt(handler)

        assert "Contexto de prueba" in prompt
