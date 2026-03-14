"""
Doc Generation Agent

Responsibilities:
  - Accept a DocRequest describing what to document and what context to use
  - Delegate content generation to LLMWrapper (via src.core.llm_wrapper)
  - Produce a structured DocResult containing one DocArtifact per doc_type
  - Embed Mermaid diagram blocks (flowcharts, sequence diagrams) when requested

Supported doc types (DocType enum):
  - USER_GUIDE: end-user narrative covering setup, running the pipeline,
    interpreting output, and configuring environment variables.
    Includes a Mermaid pipeline flowchart when include_diagrams=True.

The agent never writes files to disk — callers receive content as strings
and decide where (and whether) to persist the output.

ESOD constraints: Python 3.11+, type hints on all public functions,
no langchain.*/langgraph.* imports, LLM calls via LLMWrapper only.
"""

from __future__ import annotations

from datetime import datetime, timezone
import logging

from src.agents.doc_generation.models import DocArtifact, DocRequest, DocResult, DocType
from src.core.llm_wrapper import LLMWrapper

logger = logging.getLogger(__name__)

# Model used for doc generation (LLMWrapper.complete — ESOD Section 5.3)
_DOC_MODEL_ID = "claude-sonnet-4-6"

_USER_GUIDE_PROMPT_TEMPLATE = """\
You are a technical writer producing documentation for the Energy Options Opportunity Agent,
a Python pipeline that identifies options trading opportunities driven by oil market instability.

Your task is to write a complete USER GUIDE in GitHub-flavoured Markdown for the following subject:

  Subject: {subject}

---
CONTEXT (use this as the authoritative source of truth; do not contradict it):
{context}
---

INSTRUCTIONS:
1. Structure the guide with clear ## headings. Suggested sections:
   - Overview
   - Prerequisites
   - Setup & Configuration (include a table of all environment variables)
   - Running the Pipeline
   - Interpreting the Output
   - Troubleshooting
2. Write for a developer audience who is new to this project but comfortable with
   Python and CLI tools.
3. Be concrete and actionable. Use code blocks for all commands and code examples.
4. {diagram_instruction}
5. Keep explanations concise. Prefer tables over prose lists where appropriate.
6. Do not invent configuration values or behaviour that contradicts the provided context.

Write the complete user guide now. Output only the Markdown document — no preamble.
"""

_DIAGRAM_ON = (
    "Include at least one Mermaid diagram block where it adds clarity "
    "(e.g. a flowchart of the 4-agent pipeline, a sequence diagram for setup). "
    "Use ```mermaid fenced code blocks."
)
_DIAGRAM_OFF = "Do not include any Mermaid or other diagram blocks."


def _build_user_guide_prompt(request: DocRequest) -> str:
    """
    Build the LLM prompt for a user guide generation request.

    Args:
        request: Validated DocRequest with subject, context, and diagram preference.

    Returns:
        Formatted prompt string ready to pass to LLMWrapper.complete().
    """
    context_block = request.context.strip() if request.context.strip() else "(none provided)"
    diagram_instruction = _DIAGRAM_ON if request.include_diagrams else _DIAGRAM_OFF
    return _USER_GUIDE_PROMPT_TEMPLATE.format(
        subject=request.subject,
        context=context_block,
        diagram_instruction=diagram_instruction,
    )


def generate_user_guide(
    request: DocRequest,
    model_id: str = _DOC_MODEL_ID,
) -> DocArtifact:
    """
    Generate a user guide DocArtifact via LLMWrapper.

    The LLM is instructed to produce a complete Markdown user guide for the
    subject described in the request, optionally including Mermaid diagrams.

    Args:
        request: Validated DocRequest (doc_type must be USER_GUIDE).
        model_id: LLM model identifier. Defaults to _DOC_MODEL_ID.

    Returns:
        DocArtifact with the generated Markdown content and a UTC timestamp.

    Raises:
        NotImplementedError: If LLMWrapper.complete() is not yet implemented.
        EnvironmentError: If required LLM environment variables are not set.
    """
    logger.info("Generating user guide for subject: '%s'", request.subject)

    prompt = _build_user_guide_prompt(request)
    wrapper = LLMWrapper(model_id=model_id)
    response = wrapper.complete(prompt=prompt)

    artifact = DocArtifact(
        doc_type=DocType.USER_GUIDE,
        subject=request.subject,
        content=response.content,
        generated_at=datetime.now(tz=timezone.utc),
    )

    logger.info(
        "User guide generated for '%s' — %d characters.",
        request.subject,
        len(artifact.content),
    )
    return artifact


def run_doc_generation(
    request: DocRequest,
    model_id: str = _DOC_MODEL_ID,
) -> DocResult:
    """
    Execute one doc generation cycle and return a structured result.

    Dispatches to the appropriate generator function based on request.doc_type.
    Currently supports DocType.USER_GUIDE only.

    Steps:
      1. Validate the request (Pydantic boundary — already done by caller).
      2. Dispatch to the doc-type-specific generator.
      3. Collect the DocArtifact and assemble a DocResult.

    Args:
        request: Validated DocRequest describing the documentation to produce.
        model_id: LLM model identifier passed through to the generator.
                  Defaults to the module-level _DOC_MODEL_ID constant.

    Returns:
        DocResult with one DocArtifact and a summary string.

    Raises:
        NotImplementedError: If LLMWrapper.complete() is not yet implemented,
            or if an unsupported doc_type is requested.
        EnvironmentError: If required LLM environment variables (LLM_PROVIDER,
            ANTHROPIC_API_KEY) are not set.
    """
    logger.info(
        "Starting doc generation: type=%s subject='%s'",
        request.doc_type,
        request.subject,
    )

    if request.doc_type == DocType.USER_GUIDE:
        artifact = generate_user_guide(request, model_id=model_id)
    else:
        raise NotImplementedError(
            f"DocType '{request.doc_type}' is not yet implemented. " "Supported types: USER_GUIDE"
        )

    result = DocResult(
        request=request,
        artifacts=[artifact],
        summary=(
            f"Generated {request.doc_type} for '{request.subject}'. "
            f"Output: {len(artifact.content)} characters of Markdown"
            + (" with Mermaid diagrams." if request.include_diagrams else ".")
        ),
        generated_at=datetime.now(tz=timezone.utc),
    )

    logger.info(
        "Doc generation complete: type=%s subject='%s' artifacts=%d",
        request.doc_type,
        request.subject,
        len(result.artifacts),
    )
    return result
