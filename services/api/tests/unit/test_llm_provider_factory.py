import os
import unittest
from unittest.mock import patch

from app.config import (
    LLMConfigurationError,
    LLMProvider,
    LLMSettings,
)
from app.explanations import (
    FakeLLMClient,
    GeminiLLMClient,
    OpenAILLMClient,
    create_llm_client,
)
from app.explanations.factory import GEMINI_OPENAI_BASE_URL


class LLMSettingsTests(unittest.TestCase):
    def test_fake_is_the_credential_free_default(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            settings = LLMSettings.from_environment()

        self.assertEqual(settings.provider, LLMProvider.FAKE)
        self.assertIsNone(settings.api_key)
        self.assertIsNone(settings.model)
        self.assertIsInstance(create_llm_client(settings), FakeLLMClient)

    def test_openai_requires_api_key_and_model(self) -> None:
        incomplete_environments = (
            {"PROMPTQL_LLM_PROVIDER": "openai"},
            {
                "PROMPTQL_LLM_PROVIDER": "openai",
                "OPENAI_API_KEY": "secret-key",
            },
            {
                "PROMPTQL_LLM_PROVIDER": "openai",
                "OPENAI_MODEL": "configured-model",
            },
        )

        for environment in incomplete_environments:
            with self.subTest(environment=tuple(environment)):
                with patch.dict(os.environ, environment, clear=True):
                    with self.assertRaises(LLMConfigurationError) as raised:
                        LLMSettings.from_environment()
                self.assertNotIn("secret-key", str(raised.exception))

    def test_gemini_requires_its_own_api_key_and_model(self) -> None:
        incomplete_environments = (
            {"PROMPTQL_LLM_PROVIDER": "gemini"},
            {
                "PROMPTQL_LLM_PROVIDER": "gemini",
                "GEMINI_API_KEY": "secret-key",
            },
            {
                "PROMPTQL_LLM_PROVIDER": "gemini",
                "GEMINI_MODEL": "gemini-2.5-flash",
            },
        )

        for environment in incomplete_environments:
            with self.subTest(environment=tuple(environment)):
                with patch.dict(os.environ, environment, clear=True):
                    with self.assertRaises(LLMConfigurationError) as raised:
                        LLMSettings.from_environment()
                self.assertNotIn("secret-key", str(raised.exception))

    def test_unsupported_provider_fails_clearly(self) -> None:
        with patch.dict(
            os.environ,
            {"PROMPTQL_LLM_PROVIDER": "unsupported"},
            clear=True,
        ):
            with self.assertRaisesRegex(
                LLMConfigurationError,
                "PROMPTQL_LLM_PROVIDER must be fake, gemini, or openai",
            ):
                LLMSettings.from_environment()

    def test_openai_settings_validate_numeric_bounds_and_hide_key(self) -> None:
        environment = {
            "PROMPTQL_LLM_PROVIDER": "openai",
            "OPENAI_API_KEY": "private-api-key",
            "OPENAI_MODEL": "configured-model",
            "OPENAI_REQUEST_TIMEOUT_SECONDS": "12.5",
            "OPENAI_MAX_OUTPUT_TOKENS": "300",
        }
        with patch.dict(os.environ, environment, clear=True):
            settings = LLMSettings.from_environment()

        self.assertEqual(settings.provider, LLMProvider.OPENAI)
        self.assertEqual(settings.request_timeout_seconds, 12.5)
        self.assertEqual(settings.max_output_tokens, 300)
        self.assertNotIn("private-api-key", repr(settings))

    def test_invalid_timeout_and_token_limit_fail_without_values(self) -> None:
        base_environment = {
            "PROMPTQL_LLM_PROVIDER": "openai",
            "OPENAI_API_KEY": "private-api-key",
            "OPENAI_MODEL": "configured-model",
        }
        invalid_values = (
            ("OPENAI_REQUEST_TIMEOUT_SECONDS", "not-a-number"),
            ("OPENAI_REQUEST_TIMEOUT_SECONDS", "121"),
            ("OPENAI_MAX_OUTPUT_TOKENS", "0"),
            ("OPENAI_MAX_OUTPUT_TOKENS", "not-an-integer"),
        )

        for variable_name, value in invalid_values:
            with self.subTest(variable=variable_name, value=value):
                environment = {**base_environment, variable_name: value}
                with patch.dict(os.environ, environment, clear=True):
                    with self.assertRaises(LLMConfigurationError) as raised:
                        LLMSettings.from_environment()
                self.assertNotIn("private-api-key", str(raised.exception))

    def test_gemini_uses_gemini_names_and_validates_numeric_settings(self) -> None:
        environment = {
            "PROMPTQL_LLM_PROVIDER": "gemini",
            "GEMINI_API_KEY": "private-gemini-key",
            "GEMINI_MODEL": "gemini-2.5-flash",
            "GEMINI_REQUEST_TIMEOUT_SECONDS": "18.5",
            "GEMINI_MAX_OUTPUT_TOKENS": "400",
            "OPENAI_API_KEY": "must-not-be-selected",
            "OPENAI_MODEL": "must-not-be-selected",
        }
        with patch.dict(os.environ, environment, clear=True):
            settings = LLMSettings.from_environment()

        self.assertEqual(settings.provider, LLMProvider.GEMINI)
        self.assertEqual(settings.api_key, "private-gemini-key")
        self.assertEqual(settings.model, "gemini-2.5-flash")
        self.assertEqual(settings.request_timeout_seconds, 18.5)
        self.assertEqual(settings.max_output_tokens, 400)
        self.assertNotIn("private-gemini-key", repr(settings))


class LLMProviderFactoryTests(unittest.TestCase):
    @patch("app.explanations.factory.AsyncOpenAI")
    def test_openai_factory_disables_retries_and_uses_configured_timeout(
        self,
        async_openai,
    ) -> None:
        sdk_client = async_openai.return_value
        settings = LLMSettings(
            provider=LLMProvider.OPENAI,
            api_key="private-api-key",
            model="configured-model",
            request_timeout_seconds=17,
            max_output_tokens=321,
        )

        client = create_llm_client(settings)

        self.assertIsInstance(client, OpenAILLMClient)
        async_openai.assert_called_once_with(
            api_key="private-api-key",
            timeout=17,
            max_retries=0,
        )

    @patch("app.explanations.factory.AsyncOpenAI")
    def test_gemini_factory_uses_fixed_google_compatibility_url(
        self,
        async_openai,
    ) -> None:
        settings = LLMSettings(
            provider=LLMProvider.GEMINI,
            api_key="private-gemini-key",
            model="gemini-2.5-flash",
            request_timeout_seconds=21,
            max_output_tokens=456,
        )

        client = create_llm_client(settings)

        self.assertIsInstance(client, GeminiLLMClient)
        async_openai.assert_called_once_with(
            api_key="private-gemini-key",
            timeout=21,
            max_retries=0,
            base_url=GEMINI_OPENAI_BASE_URL,
        )


if __name__ == "__main__":
    unittest.main()
