"""
Unit tests for the Doc Generation Agent.

All tests use synthetic DocRequest objects — no real LLM API calls.
LLMWrapper is patched to return a deterministic fake response so the
generation logic is exercised without requiring network access or API keys.

Coverage:
  - DocRequest: Pydantic validation (valid, missing subject, empty content)
  - DocArtifact: Pydantic validation (content must be non-empty)
  - _build_user_guide_prompt: prompt contains subject, context, and diagram instructions
  - generate_user_guide: returns DocArtifact; LLMWrapper called once with correct args
  - generate_user_guide: LLMWrapper NotImplementedError propagates to caller
  - run_doc_generation: USER_GUIDE dispatches to generate_user_guide
  - run_doc_generation: unsupported doc_type raises NotImplementedError
  - run_doc_generation: DocResult counts and summary are consistent
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from pydantic import ValidationError
import pytest

from src.agents.doc_generation.doc_generation_agent import (
    _build_user_guide_prompt,
    generate_user_guide,
    run_doc_generation,
)
from src.agents.doc_generation.models import DocArtifact, DocRequest, DocResult, DocType

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

_FAKE_CONTENT = (
    "# User Guide\n\nThis is a generated guide.\n\n" "```mermaid\nflowchart LR\n  A --> B\n```\n"
)
_TS = datetime.now(timezone.utc)


def _make_request(**overrides: object) -> DocRequest:
    """Return a valid DocRequest with sensible defaults, overridable per test."""
    defaults: dict[str, object] = {
        "doc_type": DocType.USER_GUIDE,
        "subject": "full pipeline",
        "context": (
            "4-agent pipeline: Ingestion → Event Detection "
            "→ Feature Generation → Strategy Evaluation"
        ),
        "include_diagrams": True,
    }
    defaults.update(overrides)
    return DocRequest(**defaults)  # type: ignore[arg-type]


def _make_llm_response(content: str = _FAKE_CONTENT) -> MagicMock:
    """Return a mock LLMResponse-like object."""
    response = MagicMock()
    response.content = content
    return response


# ---------------------------------------------------------------------------
# DocRequest — Pydantic validation
# ---------------------------------------------------------------------------


class TestDocRequestValidation:
    def test_valid_request_constructs(self) -> None:
        req = _make_request()
        assert req.subject == "full pipeline"
        assert req.doc_type == DocType.USER_GUIDE
        assert req.include_diagrams is True

    def test_subject_must_not_be_empty(self) -> None:
        with pytest.raises(ValidationError):
            _make_request(subject="")

    def test_empty_context_is_allowed(self) -> None:
        req = _make_request(context="")
        assert req.context == ""

    def test_include_diagrams_defaults_to_true(self) -> None:
        req = DocRequest(subject="ingestion agent")
        assert req.include_diagrams is True

    def test_doc_type_defaults_to_user_guide(self) -> None:
        req = DocRequest(subject="setup")
        assert req.doc_type == DocType.USER_GUIDE


# ---------------------------------------------------------------------------
# DocArtifact — Pydantic validation
# ---------------------------------------------------------------------------


class TestDocArtifactValidation:
    def test_valid_artifact_constructs(self) -> None:
        artifact = DocArtifact(
            doc_type=DocType.USER_GUIDE,
            subject="full pipeline",
            content="# Guide\n\nHello.",
            generated_at=_TS,
        )
        assert artifact.content == "# Guide\n\nHello."

    def test_content_must_not_be_empty(self) -> None:
        with pytest.raises(ValidationError):
            DocArtifact(
                doc_type=DocType.USER_GUIDE,
                subject="full pipeline",
                content="",
                generated_at=_TS,
            )


# ---------------------------------------------------------------------------
# _build_user_guide_prompt
# ---------------------------------------------------------------------------


class TestBuildUserGuidePrompt:
    def test_prompt_contains_subject(self) -> None:
        req = _make_request(subject="ingestion agent")
        prompt = _build_user_guide_prompt(req)
        assert "ingestion agent" in prompt

    def test_prompt_contains_context(self) -> None:
        req = _make_request(context="Fetches crude prices via Alpha Vantage.")
        prompt = _build_user_guide_prompt(req)
        assert "Alpha Vantage" in prompt

    def test_diagram_on_includes_mermaid_instruction(self) -> None:
        req = _make_request(include_diagrams=True)
        prompt = _build_user_guide_prompt(req)
        assert "Mermaid" in prompt
        assert "mermaid" in prompt.lower()

    def test_diagram_off_excludes_mermaid_instruction(self) -> None:
        req = _make_request(include_diagrams=False)
        prompt = _build_user_guide_prompt(req)
        assert "Do not include any Mermaid" in prompt

    def test_empty_context_uses_none_provided_placeholder(self) -> None:
        req = _make_request(context="")
        prompt = _build_user_guide_prompt(req)
        assert "(none provided)" in prompt

    def test_prompt_is_non_empty_string(self) -> None:
        req = _make_request()
        prompt = _build_user_guide_prompt(req)
        assert isinstance(prompt, str)
        assert len(prompt) > 100


# ---------------------------------------------------------------------------
# generate_user_guide
# ---------------------------------------------------------------------------


class TestGenerateUserGuide:
    def _patched_generate(self, request: DocRequest, content: str = _FAKE_CONTENT) -> DocArtifact:
        """Run generate_user_guide with LLMWrapper patched to return fake content."""
        with patch("src.agents.doc_generation.doc_generation_agent.LLMWrapper") as mock_wrapper_cls:
            mock_instance = MagicMock()
            mock_instance.complete.return_value = _make_llm_response(content)
            mock_wrapper_cls.return_value = mock_instance
            return generate_user_guide(request)

    def test_returns_doc_artifact(self) -> None:
        req = _make_request()
        artifact = self._patched_generate(req)
        assert isinstance(artifact, DocArtifact)

    def test_artifact_doc_type_is_user_guide(self) -> None:
        req = _make_request()
        artifact = self._patched_generate(req)
        assert artifact.doc_type == DocType.USER_GUIDE

    def test_artifact_subject_matches_request(self) -> None:
        req = _make_request(subject="ingestion agent")
        artifact = self._patched_generate(req)
        assert artifact.subject == "ingestion agent"

    def test_artifact_content_matches_llm_response(self) -> None:
        req = _make_request()
        artifact = self._patched_generate(req, content=_FAKE_CONTENT)
        assert artifact.content == _FAKE_CONTENT

    def test_artifact_generated_at_is_utc_datetime(self) -> None:
        req = _make_request()
        artifact = self._patched_generate(req)
        assert artifact.generated_at.tzinfo is not None

    def test_llm_wrapper_called_once(self) -> None:
        req = _make_request()
        with patch("src.agents.doc_generation.doc_generation_agent.LLMWrapper") as mock_wrapper_cls:
            mock_instance = MagicMock()
            mock_instance.complete.return_value = _make_llm_response()
            mock_wrapper_cls.return_value = mock_instance
            generate_user_guide(req)
        mock_instance.complete.assert_called_once()

    def test_not_implemented_error_propagates(self) -> None:
        req = _make_request()
        with patch("src.agents.doc_generation.doc_generation_agent.LLMWrapper") as mock_wrapper_cls:
            mock_instance = MagicMock()
            mock_instance.complete.side_effect = NotImplementedError("not implemented")
            mock_wrapper_cls.return_value = mock_instance
            with pytest.raises(NotImplementedError):
                generate_user_guide(req)


# ---------------------------------------------------------------------------
# run_doc_generation
# ---------------------------------------------------------------------------


class TestRunDocGeneration:
    def _patched_run(self, request: DocRequest, content: str = _FAKE_CONTENT) -> DocResult:
        """Run run_doc_generation with LLMWrapper patched to return fake content."""
        with patch("src.agents.doc_generation.doc_generation_agent.LLMWrapper") as mock_wrapper_cls:
            mock_instance = MagicMock()
            mock_instance.complete.return_value = _make_llm_response(content)
            mock_wrapper_cls.return_value = mock_instance
            return run_doc_generation(request)

    def test_returns_doc_result(self) -> None:
        req = _make_request()
        result = self._patched_run(req)
        assert isinstance(result, DocResult)

    def test_result_has_one_artifact_for_user_guide(self) -> None:
        req = _make_request()
        result = self._patched_run(req)
        assert len(result.artifacts) == 1

    def test_result_artifact_matches_request_subject(self) -> None:
        req = _make_request(subject="strategy evaluation agent")
        result = self._patched_run(req)
        assert result.artifacts[0].subject == "strategy evaluation agent"

    def test_result_summary_is_non_empty_string(self) -> None:
        req = _make_request()
        result = self._patched_run(req)
        assert isinstance(result.summary, str)
        assert len(result.summary) > 0

    def test_result_summary_mentions_subject(self) -> None:
        req = _make_request(subject="full pipeline")
        result = self._patched_run(req)
        assert "full pipeline" in result.summary

    def test_result_generated_at_is_utc_datetime(self) -> None:
        req = _make_request()
        result = self._patched_run(req)
        assert result.generated_at.tzinfo is not None

    def test_result_request_round_trips(self) -> None:
        req = _make_request()
        result = self._patched_run(req)
        assert result.request.subject == req.subject
        assert result.request.doc_type == req.doc_type

    def test_unsupported_doc_type_raises_not_implemented(self) -> None:
        """
        Verify that an unrecognised doc_type raises NotImplementedError.

        We bypass the StrEnum by injecting the raw string after construction
        so the dispatch branch is exercised without adding new enum values.
        """
        req = _make_request()
        req_dict = req.model_dump()
        req_dict["doc_type"] = "unsupported_type"

        with patch("src.agents.doc_generation.doc_generation_agent.LLMWrapper"):
            # Manually bypass the enum to reach the else/raise branch
            with patch.object(req, "doc_type", "unsupported_type"):
                with pytest.raises(NotImplementedError, match="not yet implemented"):
                    run_doc_generation(req)

    def test_diagrams_on_reflected_in_summary(self) -> None:
        req = _make_request(include_diagrams=True)
        result = self._patched_run(req)
        assert "Mermaid" in result.summary

    def test_diagrams_off_reflected_in_summary(self) -> None:
        req = _make_request(include_diagrams=False)
        result = self._patched_run(req)
        assert "Mermaid" not in result.summary
