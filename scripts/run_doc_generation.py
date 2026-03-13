#!/usr/bin/env python3
"""
run_doc_generation.py — CLI runner for the Doc Generation Agent.

Usage:
    python scripts/run_doc_generation.py --subject "full pipeline"
    python scripts/run_doc_generation.py --subject "ingestion agent" \
        --context-file docs/energy_options_agent_design_doc.md
    python scripts/run_doc_generation.py --subject "setup" --output-dir /tmp/docs --no-diagrams

Behaviour:
  1. Constructs a validated DocRequest from CLI arguments
  2. Calls run_doc_generation() → DocResult
  3. Writes each artifact to <output-dir>/<doc_type>_<slug>.md
  4. Prints written file path(s) and summary to stdout
  5. Exits 0 on success; exits 1 on any error

Arguments:
    --subject        Required. Short description of what to document.
    --context        Optional. Inline context text for the LLM to use.
    --context-file   Optional. Path to a file whose contents are used as context.
                     Mutually exclusive with --context.
    --output-dir     Directory to write generated .md files into.
                     Default: docs/generated/  (created if it does not exist)
    --no-diagrams    Omit Mermaid diagram blocks from output.

Environment variables:
    LLM_PROVIDER        defaults to "anthropic"
    ANTHROPIC_API_KEY   required for LLM-assisted generation
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path
import re
import sys

from src.agents.doc_generation.doc_generation_agent import run_doc_generation
from src.agents.doc_generation.models import DocRequest, DocResult

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)

_DEFAULT_OUTPUT_DIR = Path("docs/generated")


def _slugify(text: str) -> str:
    """
    Convert a subject string to a lowercase filesystem-safe slug.

    Replaces whitespace and non-alphanumeric characters with hyphens
    and collapses consecutive hyphens.

    Args:
        text: Arbitrary subject string.

    Returns:
        Lowercase slug suitable for use in a filename.
    """
    slug = text.lower()
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    slug = slug.strip("-")
    return slug


def write_artifacts(result: DocResult, output_dir: Path) -> list[Path]:
    """
    Write each DocArtifact in a DocResult to a .md file in output_dir.

    File name pattern: <doc_type>_<slug>.md
    Example: user_guide_full-pipeline.md

    Args:
        result: Completed DocResult from run_doc_generation().
        output_dir: Directory to write files into (created if absent).

    Returns:
        List of absolute paths to the written files.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []

    for artifact in result.artifacts:
        slug = _slugify(artifact.subject)
        filename = f"{artifact.doc_type}_{slug}.md"
        path = output_dir / filename
        path.write_text(artifact.content, encoding="utf-8")
        written.append(path.resolve())
        logger.info("Wrote %d bytes → %s", len(artifact.content), path)

    return written


def main() -> int:
    """
    Entry point for the doc generation runner.

    Returns:
        0 on success; 1 on any error.
    """
    parser = argparse.ArgumentParser(
        description="Run the Doc Generation Agent and write output to Markdown files."
    )
    parser.add_argument(
        "--subject",
        required=True,
        metavar="TEXT",
        help="Short description of what to document, e.g. 'full pipeline'",
    )

    context_group = parser.add_mutually_exclusive_group()
    context_group.add_argument(
        "--context",
        default="",
        metavar="TEXT",
        help="Inline context text for the LLM to use as source of truth",
    )
    context_group.add_argument(
        "--context-file",
        metavar="PATH",
        help="Path to a file whose contents are used as context",
    )

    parser.add_argument(
        "--output-dir",
        default=str(_DEFAULT_OUTPUT_DIR),
        metavar="DIR",
        help=f"Directory to write .md files into (default: {_DEFAULT_OUTPUT_DIR})",
    )
    parser.add_argument(
        "--no-diagrams",
        action="store_true",
        help="Omit Mermaid diagram blocks from the generated output",
    )
    args = parser.parse_args()

    # Resolve context
    context = args.context
    if args.context_file:
        context_path = Path(args.context_file)
        if not context_path.exists():
            logger.error("Context file not found: %s", args.context_file)
            return 1
        context = context_path.read_text(encoding="utf-8")
        logger.info("Loaded context from %s (%d chars)", args.context_file, len(context))

    # Build and validate the request
    try:
        request = DocRequest(
            subject=args.subject,
            context=context,
            include_diagrams=not args.no_diagrams,
        )
    except Exception as exc:
        logger.error("Invalid request: %s", exc)
        return 1

    # Run generation
    logger.info(
        "Generating %s for subject '%s' (diagrams=%s)...",
        request.doc_type,
        request.subject,
        request.include_diagrams,
    )
    try:
        result = run_doc_generation(request)
    except (NotImplementedError, OSError) as exc:
        logger.error("Doc generation failed: %s", exc)
        return 1

    # Write artifacts to disk
    output_dir = Path(args.output_dir)
    try:
        written_paths = write_artifacts(result, output_dir)
    except OSError as exc:
        logger.error("Failed to write output files: %s", exc)
        return 1

    # Print summary
    print("\n" + "=" * 70)  # noqa: T201
    print(f"Doc Generation — subject: '{request.subject}'")  # noqa: T201
    print("=" * 70)  # noqa: T201
    print(result.summary)  # noqa: T201
    print(f"\nArtifacts written ({len(written_paths)}):")  # noqa: T201
    for path in written_paths:
        print(f"  {path}")  # noqa: T201
    print("=" * 70 + "\n")  # noqa: T201

    return 0


if __name__ == "__main__":
    sys.exit(main())
