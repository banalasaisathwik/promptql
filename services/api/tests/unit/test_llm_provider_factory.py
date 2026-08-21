import os
import unittest
from unittest.mock import patch

from app.config import (
    LLMConfigurationError,
    LLMProvider,
    LLMSettings,
    LLMTask,
)
from app.explanations import (
    FakeLLMClient,
    GeminiLLMClient,
    GroqLLMClient,
    OpenAILLMClient,
    OpenRouterLLMClient,
    create_llm_client,
)
from app.explanations.factory import (
    GEMINI_OPENAI_BASE_URL,
    GROQ_OPENAI_BASE_URL,
    OPENROUTER_OPENAI_BASE_URL,
)


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

    def test_groq_requires_its_own_api_key_and_model(self) -> None:
        incomplete_environments = (
            {"PROMPTQL_LLM_PROVIDER": "groq"},
            {
                "PROMPTQL_LLM_PROVIDER": "groq",
                "GROQ_API_KEY": "secret-key",
            },
            {
                "PROMPTQL_LLM_PROVIDER": "groq",
                "GROQ_MODEL": "openai/gpt-oss-20b",
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
                "PROMPTQL_LLM_PROVIDER must be fake, gemini, groq, openai, or openrouter",
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

    def test_groq_uses_groq_names_and_validates_numeric_settings(self) -> None:
        environment = {
            "PROMPTQL_LLM_PROVIDER": "groq",
            "GROQ_API_KEY": "private-groq-key",
            "GROQ_MODEL": "openai/gpt-oss-20b",
            "GROQ_REQUEST_TIMEOUT_SECONDS": "16.5",
            "GROQ_MAX_OUTPUT_TOKENS": "350",
            "OPENAI_API_KEY": "must-not-be-selected",
            "OPENAI_MODEL": "must-not-be-selected",
        }
        with patch.dict(os.environ, environment, clear=True):
            settings = LLMSettings.from_environment()

        self.assertEqual(settings.provider, LLMProvider.GROQ)
        self.assertEqual(settings.api_key, "private-groq-key")
        self.assertEqual(settings.model, "openai/gpt-oss-20b")
        self.assertEqual(settings.request_timeout_seconds, 16.5)
        self.assertEqual(settings.max_output_tokens, 350)
        self.assertNotIn("private-groq-key", repr(settings))

    def test_openrouter_requires_its_own_key_and_task_models_fall_back_to_default(self) -> None:
        environment = {
            "PROMPTQL_LLM_PROVIDER": "openrouter",
            "OPENROUTER_API_KEY": "private-openrouter-key",
            "PROMPTQL_DEFAULT_MODEL": "default-model",
            "PROMPTQL_PLANNER_MODEL": "planner-model",
        }
        with patch.dict(os.environ, environment, clear=True):
            settings = LLMSettings.from_environment()

        self.assertEqual(settings.provider, LLMProvider.OPENROUTER)
        self.assertEqual(settings.model_for(LLMTask.PLANNING), "planner-model")
        self.assertEqual(settings.model_for(LLMTask.HYPOTHESIS_GENERATION), "default-model")
        self.assertEqual(settings.model_for(LLMTask.CODE_DIAGNOSIS), "default-model")
        self.assertNotIn("private-openrouter-key", repr(settings))

    def test_openrouter_requires_key_and_at_least_one_active_model(self) -> None:
        for environment in (
            {"PROMPTQL_LLM_PROVIDER": "openrouter", "PROMPTQL_DEFAULT_MODEL": "model"},
            {"PROMPTQL_LLM_PROVIDER": "openrouter", "OPENROUTER_API_KEY": "secret"},
        ):
            with self.subTest(environment=environment):
                with patch.dict(os.environ, environment, clear=True):
                    with self.assertRaises(LLMConfigurationError):
                        LLMSettings.from_environment()

    def test_openrouter_allows_explicit_planner_and_hypothesis_models_without_default(self) -> None:
        with patch.dict(os.environ, {
            "PROMPTQL_LLM_PROVIDER": "openrouter",
            "OPENROUTER_API_KEY": "secret",
            "PROMPTQL_PLANNER_MODEL": "planner-model",
            "PROMPTQL_HYPOTHESIS_MODEL": "hypothesis-model",
        }, clear=True):
            settings = LLMSettings.from_environment()

        self.assertEqual(settings.model_for(LLMTask.PLANNING), "planner-model")
        self.assertEqual(
            settings.model_for(LLMTask.HYPOTHESIS_GENERATION),
            "hypothesis-model",
        )


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

    @patch("app.explanations.factory.AsyncOpenAI")
    def test_gemini_factory_uses_selected_task_model(self, async_openai) -> None:
        settings = LLMSettings(
            provider=LLMProvider.GEMINI,
            api_key="private-gemini-key",
            model=None,
            request_timeout_seconds=21,
            max_output_tokens=456,
        )

        client = create_llm_client(settings, model="planner-model")

        self.assertIsInstance(client, GeminiLLMClient)
        self.assertEqual(client.model, "planner-model")

    @patch("app.explanations.factory.AsyncOpenAI")
    def test_groq_factory_uses_fixed_url_and_disables_retries(
        self,
        async_openai,
    ) -> None:
        settings = LLMSettings(
            provider=LLMProvider.GROQ,
            api_key="private-groq-key",
            model="openai/gpt-oss-20b",
            request_timeout_seconds=15,
            max_output_tokens=256,
        )

        client = create_llm_client(settings)

        self.assertIsInstance(client, GroqLLMClient)
        async_openai.assert_called_once_with(
            api_key="private-groq-key",
            timeout=15,
            max_retries=0,
            base_url=GROQ_OPENAI_BASE_URL,
        )

    @patch("app.explanations.factory.AsyncOpenAI")
    def test_openrouter_factory_uses_compatibility_url_and_selected_task_model(
        self, async_openai
    ) -> None:
        settings = LLMSettings(
            provider=LLMProvider.OPENROUTER,
            api_key="private-openrouter-key",
            model="default-model",
            request_timeout_seconds=15,
            max_output_tokens=256,
        )

        client = create_llm_client(settings, model="planner-model")

        self.assertIsInstance(client, OpenRouterLLMClient)
        self.assertEqual(client.model, "planner-model")
        async_openai.assert_called_once_with(
            api_key="private-openrouter-key",
            timeout=15,
            max_retries=0,
            base_url=OPENROUTER_OPENAI_BASE_URL,
        )


if __name__ == "__main__":
    unittest.main()
