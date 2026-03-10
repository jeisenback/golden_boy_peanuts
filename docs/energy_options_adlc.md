**Application Development Life Cycle**

Agent-Assisted Task Workflow

Version 1.0 • March 2026 • Companion to SDLC Workflow v1.0

+-----------------------------------------------------------------------+
| **Document Relationship**                                             |
|                                                                       |
| This ADLC document sits inside the SDLC Workflow (v1.0). Where the    |
| SDLC defines the overall process --- branching, CI, sprints, and      |
| toolchain --- the ADLC defines what happens within each individual    |
| task: the repeating loop from issue to merged code.                   |
|                                                                       |
| SDLC = the development system. ADLC = the task execution engine that  |
| runs inside it.                                                       |
+-----------------------------------------------------------------------+

**1. Purpose**

This document defines the Application Development Life Cycle (ADLC): the
repeating task-level workflow used to take a GitHub Issue from open to
merged. It specifies how Claude Code, Copilot, Cursor, and human
judgment interact at each step, where handoffs happen, and what done
looks like for each task type.

Claude Code leads the bulk of implementation. The human\'s role is to
plan precisely, steer during the session, review rigorously, and own
every line that merges to the codebase. Agents accelerate; humans are
accountable.

**2. The Universal Development Loop**

Every task --- regardless of type --- follows this 10-step loop.
Per-type variations are defined in Section 4. The loop does not skip
steps; it adapts them.

  -----------------------------------------------------------------------------
  **\#**   **Step**      **Owner**       **Tool**           **Action**
  -------- ------------- --------------- ------------------ -------------------
  **1**    **Plan**      **Human**       GitHub Issues +    Define the issue.
                                         Claude.ai          Write acceptance
                                                            criteria. Decide if
                                                            agent-led or
                                                            human-led. Draft
                                                            Claude Code prompt
                                                            if agent-led.

  **2**    **Branch**    **Human**       Git CLI            Create agent/\*
                                                            branch from
                                                            develop. Never work
                                                            directly on develop
                                                            or main.

  **3**    **Build**     **Claude Code** Claude Code CLI    Claude Code
                                                            implements the
                                                            feature using the
                                                            prepared prompt.
                                                            Human monitors,
                                                            steers, and
                                                            intervenes as
                                                            needed.

  **4**    **Inline**    **Human +       Copilot / Cursor   Human reviews agent
                         Agent**                            output. Uses
                                                            Copilot/Cursor
                                                            inline for targeted
                                                            edits, completions,
                                                            and cleanup.

  **5**    **Test**      **Human**       pytest (local)     Run full test suite
                                                            locally. Write
                                                            missing tests.
                                                            Confirm coverage.
                                                            Fix any failures
                                                            before pushing.

  **6**    **Check**     **Human**       ruff, mypy, import Run lint, type
                                         scanner            check, and runtime
                                                            import scan
                                                            locally. Resolve
                                                            all issues. Do not
                                                            push a failing
                                                            branch.

  **7**    **PR**        **Human**       GitHub PR          Open PR from
                                                            agent/\* to
                                                            develop. Apply
                                                            needs-review label.
                                                            Write PR summary:
                                                            what changed, what
                                                            agent did, what was
                                                            manually edited.

  **8**    **Review**    **Human**       GitHub PR diff     Pause. Review every
                                                            changed line as a
                                                            second developer
                                                            would. Check logic,
                                                            edge cases, and
                                                            naming. Request
                                                            changes from
                                                            yourself if needed.

  **9**    **CI**        **Automated**   GitHub Actions     All CI stages run
                                                            automatically. Do
                                                            not merge until all
                                                            checks pass.
                                                            Investigate and fix
                                                            any CI failure.

  **10**   **Merge**     **Human**       GitHub             Squash and merge to
                                                            develop. Delete the
                                                            branch. Close the
                                                            issue. Add a
                                                            comment noting the
                                                            agent tool used.
  -----------------------------------------------------------------------------

+-----------------------------------------------------------------------+
| **Loop Principle**                                                    |
|                                                                       |
| Steps 1--2 (Plan and Branch) are always human-owned. Steps 3--4       |
| (Build and Inline) are agent-led with human oversight. Steps 5--10    |
| (Test through Merge) are always human-owned. The agent never merges,  |
| never closes issues, and never decides when something is done.        |
+-----------------------------------------------------------------------+

**3. Human vs. Agent Decision Checkpoints**

At key moments in the loop, the developer must make a deliberate choice
about who does the next unit of work. The following checkpoints define
those moments and the rules that govern them.

  -------------------------------------------------------------------------
  **Decision Point**     **If Yes**       **If No**        **Rule**
  ---------------------- ---------------- ---------------- ----------------
  **Is the task larger   Use Claude Code  Use              Claude Code for
  than \~2 hours of      as lead          Copilot/Cursor   modules; Copilot
  human coding?**                         inline           for edits

  **Does the task create Detailed Claude  Standard feature New modules
  a new module or        Code prompt      prompt (Section  always get
  agent?**               (Section 5.1)    5.2)             detailed prompts

  **Is the output        Runtime import   Scan still       Never skip scan
  touching src/ runtime  scan required    recommended      on src/ changes
  code?**                before PR                         

  **Did the agent        Line-by-line     Diff review      Volume triggers
  generate more than 100 review mandatory sufficient       deeper review
  lines of new code?**                                     

  **Are there failing    Human fixes      Proceed to       Human owns test
  tests after the agent  before PR --- do lint/type check  correctness
  session?**             not ask agent to                  
                         fix tests                         
                         blindly                           

  **Is this a bug fix?** Write a          N/A              Fix without a
                         regression test                   test is not done
                         first, then fix                   

  **Is the PR touching   Verify           Standard review  Schema changes
  database schema?**     TimescaleDB                       need
                         compatibility                     migration-path
                         before merge                      check
  -------------------------------------------------------------------------

**4. Tool Handoff Criteria**

Handoffs between tools are explicit moments where context must be
transferred and verified. A failed handoff --- where the receiving tool
lacks context or the output is not verified --- is a common source of
compounding errors in agent-assisted development.

  ----------------------------------------------------------------------------
  **Handoff**        **Trigger**        **How**            **Verify**
  ------------------ ------------------ ------------------ -------------------
  **Claude.ai →      Design or prompt   Copy the agreed    Claude Code has
  Claude Code**      is finalized in    prompt +           read the issue, PRD
                     chat               constraints into   section, and ESOD
                                        the Claude Code    constraints before
                                        session. Reference generating code.
                                        the GitHub Issue   
                                        number.            

  **Claude Code →    Agent session ends Commit all agent   Human reviews diff,
  Human**            or stalls          output to agent/\* removes noise, runs
                                        branch with        tests locally
                                        message: \'agent:  before any further
                                        \[summary of what  tooling.
                                        was built\]\'.     

  **Human →          Agent output needs Human identifies   Each Copilot/Cursor
  Copilot/Cursor**   targeted edits     specific lines or  suggestion reviewed
                                        functions needing  before accepting.
                                        improvement. Uses  No bulk
                                        Copilot/Cursor for auto-accept.
                                        inline completion  
                                        only.              

  **Copilot/Cursor → Inline editing     Human runs full    All tests pass. No
  Human**            complete           test suite and     lint errors. Ready
                                        lint check         to push.
                                        locally.           

  **Human → GitHub   PR opened to       Push branch and    All CI stages green
  Actions**          develop            open PR. CI        before merge. Human
                                        triggers           investigates any
                                        automatically.     failure --- do not
                                                           retry blindly.
  ----------------------------------------------------------------------------

**5. Claude Code Prompt Templates**

These templates are designed to be copied, filled in, and pasted
directly into a Claude Code session. They are intentionally detailed:
Claude Code performs best when it has full context, explicit
constraints, and a clear expected output before it begins.

+-----------------------------------------------------------------------+
| **Prompt Usage Rule**                                                 |
|                                                                       |
| Always include: (1) the GitHub Issue number, (2) the relevant PRD     |
| section, (3) the ESOD constraints that apply, and (4) the expected    |
| output structure.                                                     |
|                                                                       |
| Never ask Claude Code to \'figure out the architecture\' ---          |
| architecture decisions are made by the human before the session       |
| starts.                                                               |
+-----------------------------------------------------------------------+

**5.1 New Agent Module**

**When to use:**

Use this template when creating a new top-level agent module (e.g.
ingestion agent, event detection agent, feature generation agent).

**Prompt Template:**

> You are implementing a new agent module for the Energy Options
> Opportunity Agent system.
>
> GITHUB ISSUE: #\[issue number\] --- \[issue title\]
>
> PRD REFERENCE: Section \[X\] --- \[section name\]
>
> MODULE: \[module name, e.g. ingestion_agent\]
>
> LOCATION: src/agents/\[module_name\]/
>
> RESPONSIBILITIES:
>
> \[List exactly what this module must do, one item per line\]
>
> INPUTS:
>
> \[Describe what data/config this module receives\]
>
> OUTPUTS:
>
> \[Describe the exact output: data structure, format, schema\]
>
> CONSTRAINTS (from ESOD --- non-negotiable):
>
> \- Python 3.11+. Type hints on all public functions.
>
> \- No langchain.\* or langgraph.\* imports anywhere in src/.
>
> \- All external API calls must use tenacity for retry with exponential
> backoff.
>
> \- All inbound data validated with Pydantic models at the module
> boundary.
>
> \- Structured JSON logging using the Python logging module.
>
> \- Module must operate correctly if called without any LangChain
> dependency installed.
>
> DATABASE:
>
> \- PostgreSQL via psycopg2 or SQLAlchemy. Schema must be
> TimescaleDB-compatible.
>
> \- Connection string read from environment variable: DATABASE_URL
>
> EXPECTED FILE STRUCTURE:
>
> src/agents/\[module_name\]/
>
> \_\_init\_\_.py
>
> \[module_name\].py \# main agent logic
>
> models.py \# Pydantic input/output models
>
> db.py \# database read/write functions
>
> tests/agents/\[module_name\]/
>
> test\_\[module_name\].py \# unit tests
>
> test\_\[module_name\]\_integration.py \# integration tests (uses
> testcontainers)
>
> DO NOT:
>
> \- Make architecture decisions not specified here. Ask if unclear.
>
> \- Import from langchain, langgraph, or any agent framework.
>
> \- Use SQLite for any database operations.
>
> \- Leave unimplemented stubs without a TODO comment and a failing
> test.
>
> Start by reading the existing codebase structure, then implement.

**5.2 Feature Within an Existing Module**

**When to use:**

Use this template when adding a new capability, signal, or behavior to a
module that already exists.

**Prompt Template:**

> You are adding a feature to an existing module in the Energy Options
> Opportunity Agent.
>
> GITHUB ISSUE: #\[issue number\] --- \[issue title\]
>
> TARGET MODULE: src/agents/\[module_name\]/\[file_name\].py
>
> FEATURE: \[One sentence describing what is being added\]
>
> ACCEPTANCE CRITERIA (from GitHub Issue):
>
> \[Paste acceptance criteria directly from the issue\]
>
> CONTEXT:
>
> \- Read the existing module before making any changes.
>
> \- The existing test suite must continue to pass after your changes.
>
> \- Add new tests in
> tests/agents/\[module_name\]/test\_\[module_name\].py
>
> CONSTRAINTS:
>
> \- Do not refactor existing code unless it directly blocks the
> feature.
>
> \- Do not add new dependencies without flagging them for human
> approval first.
>
> \- No langchain.\* or langgraph.\* imports.
>
> \- Type hints required on any new functions.
>
> EXPECTED OUTPUT:
>
> \[Describe the new function signature, return type, or behavior\]
>
> Read the module first. Then implement the feature. Then write the
> tests.

**5.3 Bug Fix**

**When to use:**

Use this template when fixing a confirmed defect. Always write the
regression test before asking Claude Code to fix the bug.

**Prompt Template:**

> You are fixing a confirmed bug in the Energy Options Opportunity
> Agent.
>
> GITHUB ISSUE: #\[issue number\] --- \[issue title\]
>
> AFFECTED FILE: src/\[path/to/file.py\]
>
> BUG DESCRIPTION:
>
> \[Describe exactly what is wrong: inputs, expected behavior, actual
> behavior\]
>
> REPRODUCTION:
>
> \[Paste the failing test or the exact steps to reproduce\]
>
> REGRESSION TEST:
>
> \[The test that currently FAILS and must PASS after the fix is already
> written at:
>
> tests/\[path\]/test\_\[name\].py :: test\_\[function_name\]\]
>
> CONSTRAINTS:
>
> \- Fix only the confirmed bug. Do not refactor surrounding code.
>
> \- Do not modify the regression test --- the code must change, not the
> test.
>
> \- All existing tests must continue to pass.
>
> \- Document the root cause in a comment near the fix.
>
> Read the file, understand the root cause, then implement the minimal
> fix.

**5.4 Test Coverage**

**When to use:**

Use this template when adding tests to a module that lacks coverage, or
when building out a golden dataset validation scenario.

**Prompt Template:**

> You are writing tests for an existing module in the Energy Options
> Opportunity Agent.
>
> GITHUB ISSUE: #\[issue number\] --- \[issue title\]
>
> TARGET MODULE: src/agents/\[module_name\]/\[file_name\].py
>
> TEST FILE: tests/agents/\[module_name\]/test\_\[file_name\].py
>
> COVERAGE GOAL:
>
> \[List the specific functions or behaviors that need test coverage\]
>
> TEST TYPES REQUIRED:
>
> \- Unit tests: test each function in isolation with mocked
> dependencies
>
> \- Integration tests: test the full module path using a real Postgres
> instance
>
> (use testcontainers: from testcontainers.postgres import
> PostgresContainer)
>
> \[Add: golden dataset test if output-facing\]
>
> GOLDEN DATASET (if applicable):
>
> \[Describe the known-good input scenario and the expected edge_score /
> output\]
>
> CONSTRAINTS:
>
> \- Do not mock the database in integration tests. Use testcontainers.
>
> \- Do not modify source code to make tests pass --- tests must reflect
> real behavior.
>
> \- Use pytest fixtures for shared setup.
>
> \- Each test must have a clear docstring explaining what it validates.
>
> Read the module first. Then write tests that would catch real
> failures.

**5.5 Refactor / Cleanup**

**When to use:**

Use this template when improving code structure, readability, or
reducing duplication without changing behavior.

**Prompt Template:**

> You are refactoring existing code in the Energy Options Opportunity
> Agent.
>
> GITHUB ISSUE: #\[issue number\] --- \[issue title\]
>
> TARGET FILE(S): src/\[path/to/file.py\]
>
> REFACTOR GOAL:
>
> \[Describe specifically what is being improved: e.g. extract
> duplicated retry logic
>
> into a shared utility, simplify a function with too many
> responsibilities, etc.\]
>
> CONSTRAINTS (strict):
>
> \- Zero behavioral changes. The existing test suite must pass without
> modification.
>
> \- Do not add new features or fix bugs as part of this refactor.
>
> \- Do not change public function signatures unless explicitly stated.
>
> \- No new external dependencies.
>
> \- No langchain.\* or langgraph.\* imports.
>
> DONE WHEN:
>
> \- All existing tests pass without changes.
>
> \- The refactored code is measurably simpler (fewer lines, clearer
> naming,
>
> or reduced duplication) than the original.
>
> \- A brief comment explains what was simplified and why.
>
> Read the file. Propose the refactor approach before implementing. Wait
> for approval.

**6. Definition of Done by Task Type**

A task is not done when the code works --- it is done when all of the
following criteria are met. These criteria are the merge gate for every
PR.

  -----------------------------------------------------------------------
  **Task Type**   **Definition of Done**
  --------------- -------------------------------------------------------
  **New Agent     Module is independently importable and testable. Unit
  Module**        tests cover all public functions. Integration test
                  covers full pipeline path through the module. No
                  langchain.\* runtime imports. Module documented with a
                  docstring and README entry.

  **Feature       Acceptance criteria in the GitHub Issue are all
  (existing       checked. Existing tests still pass. New tests cover the
  module)**       added behavior. Lint and type check pass. PR
                  description explains what changed and why.

  **Bug Fix**     A regression test exists that fails before the fix and
                  passes after. Root cause documented in the PR or issue
                  comment. No unrelated changes included. All existing
                  tests pass.

  **Test          All targeted functions/modules have pytest coverage.
  Coverage**      Tests use real Postgres via testcontainers (not mocked
                  DB). Golden dataset scenario validated if
                  output-facing. Coverage report shows improvement.

  **Refactor /    No behavioral changes (all existing tests still pass
  Cleanup**       with no modifications). Code is simpler or more
                  readable by measurable criteria (fewer lines, clearer
                  naming, reduced duplication). PR explains what was
                  simplified and why.
  -----------------------------------------------------------------------

+-----------------------------------------------------------------------+
| **Universal DoD Items**                                               |
|                                                                       |
| These apply to every task type regardless of the per-type criteria    |
| above:                                                                |
|                                                                       |
| • All CI stages pass (lint, type check, unit tests, integration       |
| tests, runtime import scan).                                          |
|                                                                       |
| • PR description is complete: what changed, what the agent did, what  |
| was manually reviewed.                                                |
|                                                                       |
| • The GitHub Issue acceptance criteria are all checked off.           |
|                                                                       |
| • The branch is deleted after merge.                                  |
|                                                                       |
| • The issue is closed with a comment noting the agent tool(s) used.   |
+-----------------------------------------------------------------------+

**7. Agent Session Hygiene**

Agent sessions produce noise alongside useful code: debug print
statements, commented-out alternatives, scaffolding stubs, and
over-broad imports. The following practices keep sessions productive and
the codebase clean.

**7.1 Before the Session**

-   The GitHub Issue is written with clear acceptance criteria before
    opening Claude Code.

-   The prompt template is filled in and reviewed. Vague prompts produce
    vague code.

-   The agent/\* branch is checked out and confirmed clean (no
    uncommitted changes).

-   The existing test suite passes locally before the session begins.

**7.2 During the Session**

-   Monitor output as Claude Code generates. Intervene early if the
    direction is wrong.

-   If Claude Code asks an architecture question, answer it explicitly.
    Do not let it decide.

-   Commit incrementally during long sessions: \'agent: implemented
    \[X\], in progress on \[Y\]\'.

-   If Claude Code stalls or loops, stop the session. Diagnose manually.
    Restart with a refined prompt.

**7.3 After the Session**

-   Run git diff and read every changed line before running any tests.

-   Remove: debug prints, commented-out code, unused imports, leftover
    stubs.

-   Verify: all new functions have type hints and docstrings.

-   Run the runtime import scan locally before pushing:

> python .github/scripts/check_runtime_imports.py

-   Commit the cleanup separately from the agent output: \'chore:
    post-session cleanup for #\[issue\]\'.

**8. Applying This ADLC to Other Projects**

This ADLC is a reusable framework. To apply it to a new project:

1.  Update the project name and repo reference in the title block.

2.  Replace ESOD constraint references in prompt templates with the new
    project\'s ESOD.

3.  Adjust the database and infrastructure references in Section 5.1 to
    match the new stack.

4.  Add or remove task type variations in Sections 4--6 based on the
    project\'s work patterns.

5.  Keep the universal loop (Section 2) and decision checkpoints
    (Section 3) unchanged --- these are stack-agnostic.

+-----------------------------------------------------------------------+
| **Version This Document**                                             |
|                                                                       |
| As agent tooling evolves, prompt templates should be updated to       |
| reflect what works.                                                   |
|                                                                       |
| When a prompt template is improved based on real session experience,  |
| increment the document version and note what changed.                 |
|                                                                       |
| Recommended location in repo: /docs/adlc-workflow.docx                |
+-----------------------------------------------------------------------+
