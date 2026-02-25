"""Tests for LLM provider abstraction."""

from unittest.mock import MagicMock, Mock, patch

from src.schemas import EmailClassification


class TestGetLitellmParams:
    def test_returns_config_values(self):
        from src.llm import _get_litellm_params

        params = _get_litellm_params()
        assert "model" in params
        assert "api_base" in params
        assert "api_key" in params
        assert "timeout" in params

    def test_model_from_config(self):
        from src.llm import _get_litellm_params

        params = _get_litellm_params()
        # Should match the test env LITELLM_MODEL
        assert isinstance(params["model"], str)
        assert len(params["model"]) > 0


class TestGetModelName:
    def test_returns_model_string(self):
        from src.llm import get_model_name

        name = get_model_name()
        assert isinstance(name, str)
        assert len(name) > 0


class TestIsLlmAvailable:
    @patch("src.llm.litellm.completion")
    def test_available_when_response_has_choices(self, mock_completion):
        mock_completion.return_value = Mock(choices=[Mock()])
        from src.llm import is_llm_available

        assert is_llm_available() is True

    @patch("src.llm.litellm.completion")
    def test_unavailable_on_exception(self, mock_completion):
        mock_completion.side_effect = Exception("Connection refused")
        from src.llm import is_llm_available

        assert is_llm_available() is False

    @patch("src.llm.litellm.completion")
    def test_unavailable_on_empty_choices(self, mock_completion):
        mock_completion.return_value = Mock(choices=[])
        from src.llm import is_llm_available

        assert is_llm_available() is False


class TestLlmComplete:
    @patch("src.llm.litellm.completion")
    def test_returns_text_on_success(self, mock_completion):
        mock_completion.return_value = Mock(choices=[Mock(message=Mock(content="Hello world"))])
        from src.llm import llm_complete

        result = llm_complete(messages=[{"role": "user", "content": "test"}])
        assert result == "Hello world"

    @patch("src.llm.litellm.completion")
    def test_returns_none_on_exception(self, mock_completion):
        mock_completion.side_effect = Exception("API error")
        from src.llm import llm_complete

        result = llm_complete(messages=[{"role": "user", "content": "test"}])
        assert result is None

    @patch("src.llm.litellm.completion")
    def test_returns_none_on_empty_response(self, mock_completion):
        mock_completion.return_value = Mock(choices=[])
        from src.llm import llm_complete

        result = llm_complete(messages=[{"role": "user", "content": "test"}])
        assert result is None

    @patch("src.llm.litellm.completion")
    def test_prepends_system_prompt(self, mock_completion):
        mock_completion.return_value = Mock(choices=[Mock(message=Mock(content="OK"))])
        from src.llm import llm_complete

        llm_complete(
            messages=[{"role": "user", "content": "test"}],
            system_prompt="Be helpful",
        )
        call_args = mock_completion.call_args
        messages = call_args.kwargs.get("messages") or call_args[1].get("messages")
        assert messages[0]["role"] == "system"
        assert messages[0]["content"] == "Be helpful"


class TestLlmCompleteStructured:
    @patch("src.llm.instructor.from_litellm")
    def test_returns_pydantic_model(self, mock_instructor):
        expected = EmailClassification(category="spam", confidence=0.9, reason="test")
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = expected
        mock_instructor.return_value = mock_client

        from src.llm import llm_complete_structured

        result = llm_complete_structured(
            EmailClassification,
            messages=[{"role": "user", "content": "classify"}],
        )
        assert result is not None
        assert result.category == "spam"
        assert result.confidence == 0.9

    @patch("src.llm.instructor.from_litellm")
    def test_returns_none_on_exception(self, mock_instructor):
        mock_instructor.side_effect = Exception("Instructor error")

        from src.llm import llm_complete_structured

        result = llm_complete_structured(
            EmailClassification,
            messages=[{"role": "user", "content": "classify"}],
        )
        assert result is None


class TestVerifyLlmStructuredOutput:
    @patch("src.llm.llm_complete_structured")
    def test_verify_success(self, mock_structured):
        from src.llm import _ProbeResponse, verify_llm_structured_output

        mock_structured.return_value = _ProbeResponse(value="ok")
        # Should not raise
        verify_llm_structured_output()

    @patch("src.llm.llm_complete_structured")
    def test_verify_failure_none(self, mock_structured):
        from src.llm import verify_llm_structured_output

        mock_structured.return_value = None
        import pytest

        with pytest.raises(RuntimeError, match="failed structured output probe"):
            verify_llm_structured_output()

    @patch("src.llm.llm_complete_structured")
    def test_verify_failure_exception(self, mock_structured):
        from src.llm import verify_llm_structured_output

        mock_structured.side_effect = Exception("Connection refused")
        import pytest

        with pytest.raises(RuntimeError, match="does not support TOOLS mode"):
            verify_llm_structured_output()
