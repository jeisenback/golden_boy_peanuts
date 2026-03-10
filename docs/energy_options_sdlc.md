**SDLC Workflow**

Agent-Assisted Development Framework

Version 1.0 • March 2026 • Reference: Energy Options Opportunity Agent

+-----------------------------------------------------------------------+
| **Framework Scope**                                                   |
|                                                                       |
| This document defines a reusable SDLC workflow for agent-assisted     |
| Python development projects.                                          |
|                                                                       |
| The Energy Options Opportunity Agent is used throughout as the        |
| reference implementation.                                             |
|                                                                       |
| To apply this framework to a new project: replace the reference       |
| project name, adjust the phase labels in Section 6, and update the    |
| repo URL in Section 3.                                                |
+-----------------------------------------------------------------------+

**1. Purpose**

This SDLC Workflow document defines how software is planned, developed,
reviewed, tested, and shipped in an agent-assisted development
environment. It establishes a lightweight but disciplined process suited
to a solo contributor using AI tools, with a clear path to scale as team
size grows.

The workflow is built entirely on GitHub-native tooling: GitHub Issues
for tracking, GitHub Flow for branching, and GitHub Actions for CI/CD.
This keeps the process integrated, low-overhead, and accessible without
additional SaaS subscriptions.

**2. Guiding Principles**

-   **AI tools write code faster, but the developer is responsible for
    every line that merges to main. Review is non-negotiable.**Agents
    accelerate, humans decide.

-   **Prefer frequent, focused commits over large batch changes. Each
    commit should express a single coherent change.**Small commits,
    clear intent.

-   **Because agents can produce plausible-but-wrong code, tests are
    especially critical. No feature is done until it has a test.**Tests
    are the safety net for agent code.

-   **Ceremonies and documentation should take minutes, not hours. The
    goal is a decision trail, not process theater.**Keep the process
    lighter than the work.

-   **Even as a solo contributor, write code and structure branches as
    if a second developer will join tomorrow.**Design for growth from
    day one.

**3. Toolchain**

**3.1 Repository**

-   **GitHub**Platform:

-   **github.com/jeisenback/golden_boy_peanuts**Repository:

-   **main (protected)**Default branch:

-   **develop**Integration branch:

**3.2 Agent Development Tools**

  ------------------------------------------------------------------------
  **Tool**        **Role**         **Permitted Usage** **Constraints**
  --------------- ---------------- ------------------- -------------------
  **Claude Code   **Primary agent  Scaffold agents,    Must not introduce
  (CLI)**         dev tool**       write pipeline      langchain.\*
                                   code, generate      runtime imports.
                                   tests, refactor     Validate with test
                                   modules, implement  suite after each
                                   features end-to-end session.
                                   from terminal.      

  **Cursor / IDE  **In-editor AI   Inline code         Review all
  Agent**         assistance**     completion,         AI-suggested code
                                   file-level          before commit. Do
                                   refactoring,        not auto-accept
                                   docstring           bulk changes
                                   generation, local   without inspection.
                                   debugging within    
                                   the IDE.            

  **GitHub        **Inline code    Line-by-line        Same review
  Copilot**       suggestions**    completions during  standard as Cursor.
                                   active coding. Best Copilot suggestions
                                   for boilerplate,    must pass linting
                                   repetitive          and type checking
                                   patterns, and test  before commit.
                                   case stubs.         

  **Claude.ai     **Design & docs  Architecture        Outputs are
  (Chat)**        assistant**      decisions, document reference material,
                                   generation (PRD,    not production
                                   ESOD, SDLC), prompt code. All code must
                                   engineering, ADR    be reviewed and
                                   drafting, code      tested before use.
                                   review discussion.  
  ------------------------------------------------------------------------

+-----------------------------------------------------------------------+
| **Critical Rule**                                                     |
|                                                                       |
| No agent tool output goes directly to main or develop without human   |
| review and a passing CI run. The agent/branch type exists             |
| specifically to hold agent-driven work until it is reviewed and       |
| cleaned.                                                              |
+-----------------------------------------------------------------------+

**4. Branching & GitHub Flow**

**4.1 Branch Strategy**

  -------------------------------------------------------------------------------------
  **Branch Type**  **Purpose**        **Naming Example**              **Rules**
  ---------------- ------------------ ------------------------------- -----------------
  **main**         Production-ready   main                            Never commit
                   code                                               directly. Merge
                                                                      via PR only. All
                                                                      CI gates must
                                                                      pass.

  **develop**      Integration branch develop                         All feature
                   for active work                                    branches merge
                                                                      here first. Kept
                                                                      stable and
                                                                      deployable.

  **feature/\***   New features or    feature/ingest-eia-feed         Branch from
                   agents                                             develop. PR back
                                                                      to develop.
                                                                      Delete after
                                                                      merge.

  **fix/\***       Bug fixes          fix/volatility-gap-calc         Branch from
                                                                      develop (or main
                                                                      for hotfix). PR
                                                                      with test
                                                                      covering the fix.

  **chore/\***     Tooling, deps,     chore/update-dependencies       Branch from
                   docs                                               develop. No
                                                                      functional
                                                                      changes. PR
                                                                      required.

  **agent/\***     Agent-scaffolded   agent/scaffold-event-detector   Used when Claude
                   work in progress                                   Code is driving a
                                                                      session. Must be
                                                                      reviewed and
                                                                      cleaned up before
                                                                      PR to develop.
  -------------------------------------------------------------------------------------

**4.2 Standard Feature Workflow**

The following steps apply to all feature, fix, and chore work:

1.  Create a GitHub Issue describing the work. Apply labels (type,
    phase, agent-assisted if applicable).

2.  Branch from develop using the appropriate prefix: feature/\*,
    fix/\*, chore/\*, or agent/\*.

3.  Implement the change. If using Claude Code or Cursor, work on an
    agent/\* branch.

4.  Write or update tests. Run the full test suite locally before
    pushing.

5.  Push the branch and open a Pull Request to develop. Reference the
    issue number in the PR description.

6.  Apply the needs-review label. Pause. Review the PR as if you were a
    second developer.

7.  Confirm all CI checks pass. Merge using Squash and Merge to keep
    history clean.

8.  Delete the branch. Close the issue.

**4.3 Agent Session Workflow**

When using Claude Code (CLI) or Cursor for a development session, follow
this pattern:

9.  Create or identify the GitHub Issue for the work.

10. Check out a new agent/\* branch from develop.

11. Run the agent session. Let it scaffold, implement, and iterate
    freely on this branch.

12. When the session ends, review every file changed. Remove any
    scaffolding noise, debug output, or leftover stubs.

13. Run the full local test suite. Fix any failures before proceeding.

14. Verify no langchain.\* or langgraph.\* imports exist in src/
    directories.

15. Open a PR from agent/\* to develop with a summary of what the agent
    did and what you changed during review.

16. Let CI run. Merge only when all checks pass.

**4.4 Merging to Main**

main represents production-ready code. Merges to main follow an elevated
standard:

-   All CI stages must pass including integration tests and security
    scan.

-   The develop branch must be stable and tested end-to-end against the
    relevant MVP phase criteria.

-   A brief release note must be added to the GitHub Release describing
    what changed.

-   Merges to main use a standard Merge Commit (not squash) to preserve
    the develop history.

**5. CI / CD Pipeline**

All CI is implemented via GitHub Actions. Pipelines run automatically on
push and pull request events. The pipeline is the enforcer of ESOD
technical standards --- it is not advisory.

  --------------------------------------------------------------------------
  **Stage**       **Trigger**     **Tooling**       **Pass Criteria**
  --------------- --------------- ----------------- ------------------------
  **Lint &        Every push      ruff, black       Fail on any lint error
  Format**                                          or format violation.
                                                    Auto-fix not permitted
                                                    in CI (fix locally).

  **Type Check**  Every push      mypy              Strict mode. All public
                                                    functions must have type
                                                    annotations. Fail on
                                                    type errors.

  **Unit Tests**  Every push      pytest            100% of feature
                                                    generators and edge
                                                    scoring functions must
                                                    have coverage. Fail on
                                                    any test failure.

  **Integration   PR to           pytest +          Spins up real Postgres
  Tests**         develop/main    testcontainers    instance. Tests full
                                                    pipeline ingestion and
                                                    output. Must pass before
                                                    merge.

  **Runtime       Every push      Custom script     Scan for langchain.\* or
  Import Check**                  (grep / ast)      langgraph.\* imports in
                                                    src/. Fail if found.
                                                    Enforces ESOD
                                                    architectural rule.

  **Security      PR to main      bandit, pip-audit Fail on high-severity
  Scan**                                            findings. Known false
                                                    positives must be
                                                    documented and
                                                    suppressed explicitly.
  --------------------------------------------------------------------------

**5.1 GitHub Actions Structure**

Recommended workflow file layout in the repository:

> .github/
>
> workflows/
>
> ci.yml \# lint, type check, unit tests --- runs on every push
>
> integration.yml \# integration tests --- runs on PR to develop and
> main
>
> security.yml \# bandit, pip-audit --- runs on PR to main
>
> runtime-check.yml \# langchain import scan --- runs on every push

**5.2 Runtime Import Check**

This CI stage enforces the ESOD architectural rule that LangChain and
LangGraph must not appear as runtime imports. Implement as a simple
script:

> \# .github/scripts/check_runtime_imports.py
>
> import ast, sys, pathlib
>
> BANNED = \[\'langchain\', \'langgraph\'\]
>
> for path in pathlib.Path(\'src\').rglob(\'\*.py\'):
>
> tree = ast.parse(path.read_text())
>
> for node in ast.walk(tree):
>
> if isinstance(node, (ast.Import, ast.ImportFrom)):
>
> name = getattr(node, \'module\', \'\') or \'\'
>
> if any(b in name for b in BANNED):
>
> print(f\'FAIL: {path}:{node.lineno} imports {name}\')
>
> sys.exit(1)

**6. Issue Tracking & Sprint Cadence**

**6.1 GitHub Issues Setup**

All work is tracked as GitHub Issues in the project repository. Issues
are the single source of truth for what is being built, why, and in
which phase.

**Issue Labels**

  -----------------------------------------------------------------------------
  **Label**            **Meaning**        **Usage**
  -------------------- ------------------ -------------------------------------
  **type: feature**    **New capability** A new agent, signal, data source, or
                                          strategy structure.

  **type: fix**        **Bug or defect**  Incorrect behavior, bad output, or
                                          broken pipeline stage.

  **type: chore**      **Non-functional   Dependency updates, config changes,
                       work**             documentation, tooling.

  **type: test**       **Test coverage    Missing unit, integration, or golden
                       gap**              dataset test.

  **phase: 1 / 2 / 3** **MVP phase        Links the issue to the relevant MVP
                       assignment**       phase from the PRD.

  **agent-assisted**   **AI-accelerated   This issue will be partially or fully
                       work**             implemented using Claude Code,
                                          Copilot, or Cursor.

  **blocked**          **Cannot proceed** Waiting on external dependency, data
                                          access, or another issue.

  **needs-review**     **Ready for        Solo contributor: apply before
                       self-review**      closing any PR to enforce a review
                                          pause.
  -----------------------------------------------------------------------------

**Milestones**

Use GitHub Milestones to represent MVP phases from the PRD:

-   Milestone: Phase 1 --- Core Market Signals & Options

-   Milestone: Phase 2 --- Supply & Event Augmentation

-   Milestone: Phase 3 --- Alternative / Contextual Signals

-   Milestone: Phase 4 --- Optional Enhancements

Each issue is assigned to exactly one milestone. This keeps the backlog
organized by product phase without additional tooling.

**6.2 Issue Template**

Use a consistent issue format to keep context clear across sessions:

> \## Goal
>
> One sentence: what this issue accomplishes.
>
> \## Context
>
> Why this is needed. Link to PRD section or ESOD decision if relevant.
>
> \## Acceptance Criteria
>
> \- \[ \] Criterion 1
>
> \- \[ \] Criterion 2
>
> \- \[ \] Tests written and passing
>
> \## Agent Notes
>
> If agent-assisted: which tool, what prompt or approach was used.

**6.3 Sprint Cadence (Solo)**

A lightweight weekly sprint cadence keeps work moving without overhead.
All ceremonies are async and GitHub-native.

  --------------------------------------------------------------------------
  **Ceremony**      **Tool**               **How It Works (Solo)**
  ----------------- ---------------------- ---------------------------------
  **Sprint Planning **GitHub Issues**      Review backlog. Pull issues into
  (Start of week)**                        current sprint milestone. Assign
                                           labels and phase tags. Set the
                                           week\'s single top-priority
                                           outcome.

  **Daily Standup   **GitHub Issue         Leave a brief comment on the
  (Async, solo)**   comments**             active issue: what was done,
                                           what\'s next, any blockers. Keeps
                                           a decision trail without
                                           meetings.

  **Agent Session   **Branch commit        After each Claude Code or Cursor
  Log (Per          message or PR          session, commit with a
  session)**        comment**              descriptive message noting what
                                           the agent did and what was
                                           manually reviewed.

  **Sprint Review   **GitHub Milestone**   Close completed issues. Move
  (End of week)**                          incomplete issues to next sprint.
                                           Update milestone progress. Note
                                           any scope changes or new
                                           decisions.

  **Retrospective   **ADR or GitHub        Document one process improvement
  (Bi-weekly)**     Discussion**           per cycle. If an agent workflow
                                           is working well or poorly,
                                           capture it as a note for the SDLC
                                           framework.
  --------------------------------------------------------------------------

**7. Applying This Framework to a New Project**

To apply this SDLC framework to a project other than the Energy Options
Opportunity Agent:

17. Copy this document and update the title, reference project name, and
    repository URL in Section 3.

18. Define the project\'s MVP phases and create corresponding GitHub
    Milestones.

19. Update the agent tool table in Section 3.2 if the toolchain differs.

20. Add or remove CI stages in Section 5 based on the project\'s
    language and testing approach.

21. Adjust issue labels in Section 6.1 to match the project\'s phase and
    type taxonomy.

22. Archive the original version of this document as v1.0 before making
    project-specific edits.

+-----------------------------------------------------------------------+
| **Framework Versioning**                                              |
|                                                                       |
| This framework document should itself be version-controlled. When the |
| process improves, update the version number and add a change note at  |
| the top.                                                              |
|                                                                       |
| Recommended location in repo: /docs/sdlc-workflow.docx or             |
| /docs/sdlc-workflow.md                                                |
+-----------------------------------------------------------------------+

**8. Glossary**

-   **Architecture Decision Record. A short document capturing a
    significant technical decision, its context, and rationale.**ADR:

-   **A focused development session driven primarily by an AI coding
    tool (Claude Code, Cursor, Copilot).**Agent session:

-   **A Git branch used to contain agent-driven work before human review
    and merge to develop.**agent/\* branch:

-   **Continuous Integration. Automated test and quality checks that run
    on every code push.**CI:

-   **Engineering Statement of Direction. The document defining
    technical standards for this project.**ESOD:

-   **A curated set of known-good inputs and expected outputs used to
    validate agent output correctness.**Golden dataset:

-   **A TimescaleDB table optimized for time-series data with automatic
    partitioning by time.**Hypertable:

-   **A GitHub label applied by the solo contributor to enforce a
    self-review pause before merging a PR.**needs-review:

-   **Product Requirements Document. The document defining product
    scope, features, and phasing.**PRD:

-   **A library or framework required for the production system to
    execute. LangChain/LangGraph are explicitly not runtime dependencies
    in this project.**Runtime dependency:
