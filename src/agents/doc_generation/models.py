"""
Pydantic models for the Doc Generation Agent data boundary (ESOD Section 6).

All doc generation requests and results are validated through these models
before any LLM processing or content assembly.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from src.core.compat import StrEnum


class DocType(StrEnum):
    """Supported documentation output types."""

    USER_GUIDE = "user_guide"


class DocRequest(BaseModel):
    """
    Validated input for a documentation generation request.

    The caller provides a subject (what to document), prose or structured
    context (source code snippets, module descriptions, env var tables, etc.),
    and whether Mermaid diagrams should be included in the output.
    """

    doc_type: DocType = Field(
        default=DocType.USER_GUIDE,
        description="The type of document to generate",
    )
    subject: str = Field(
        ...,
        min_length=1,
        description=(
            "Short description of what is being documented, "
            "e.g. 'full pipeline', 'ingestion agent', 'development workflow'"
        ),
    )
    context: str = Field(
        default="",
        description=(
            "Source text, code snippets, or structured descriptions that the "
            "LLM should use as the authoritative source of truth for the document. "
            "May be empty; the agent will rely on its system knowledge of the project."
        ),
    )
    include_diagrams: bool = Field(
        default=True,
        description=(
            "When True, the agent instructs the LLM to include Mermaid diagram "
            "blocks (flowcharts, sequence diagrams) where they aid understanding."
        ),
    )


class DocArtifact(BaseModel):
    """
    A single generated documentation artifact.

    Contains the complete markdown content for one document, including any
    embedded Mermaid diagram blocks.
    """

    doc_type: DocType = Field(..., description="Type of document this artifact represents")
    subject: str = Field(..., description="Subject that was documented")
    content: str = Field(
        ...,
        min_length=1,
        description="Complete markdown content, including any Mermaid diagram blocks",
    )
    generated_at: datetime = Field(..., description="UTC timestamp when this artifact was produced")


class DocResult(BaseModel):
    """
    Structured output of one doc generation cycle.

    Contains one or more DocArtifact objects and a brief summary
    of what was generated and any caveats.
    """

    request: DocRequest = Field(..., description="The original request that produced this result")
    artifacts: list[DocArtifact] = Field(
        default_factory=list,
        description="Generated documentation artifacts, one per doc_type requested",
    )
    summary: str = Field(
        ...,
        description="One-sentence summary of what was generated and any caveats",
    )
    generated_at: datetime = Field(
        ..., description="UTC timestamp when the generation cycle completed"
    )
