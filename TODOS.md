# TODOS.md

Items deferred from active sprint planning. Each item has full context so it can be
picked up in a future sprint without re-research.

---

## Sprint C pre-requisite: UUID primary key on strategy_candidates

**What:** Add `id UUID PRIMARY KEY DEFAULT gen_random_uuid()` to the `strategy_candidates`
table and update `write_strategy_candidates()` to return the generated UUIDs.

**Why:** The REST API (issue #168, Sprint C) needs to expose individual candidates by
stable identifier. Currently there's no pk — REST routes would require fragile composite
keys. The alerting system ('alert fired for candidate X') and thinkorswim ticket tracking
('ticket submitted for candidate X') both need a stable candidate ID.

**Pros:** Standard REST design. Required for Sprint C audit trail. Enables `/candidates/{id}`
endpoint. Prevents duplicate-alert bugs (alert fires twice for same candidate).

**Cons:** Migration touches the live `strategy_candidates` table with existing rows
(use `ALTER TABLE ... ADD COLUMN ... DEFAULT`). `write_strategy_candidates()` return type
changes from `int` to `List[UUID]` — public interface change, requires human sign-off.

**Context:** Raised during eng review of Phase 3 design doc (2026-03-21). Issue 3 was
resolved for Sprint A by using a separate `backtest_candidates` table (no FK to
`strategy_candidates`). Sprint C will need this UUID to link alerts and TOS tickets back
to the originating candidate. Current state: `db.py:write_strategy_candidates()` returns
row count only; `StrategyCandidate` model has no `id` field.

**Depends on / blocked by:** Human sign-off on schema migration. FastAPI + uvicorn package
approval (also required for Sprint C). Should be done as part of Sprint C kick-off before
any REST API code is written.

---
