# Career Quest work plan

Status: AI Engine implemented and frozen; FastAPI/SQLite backend implemented with a
mock engine. Full application/AI integration is still pending.

## Participant 1 - AI Engine

Ownership: backend/app/engine/, tests/ and algorithm documentation; feat/ai-engine.

- [x] Dataset analysis, relationships, constraints and documented ambiguities.
- [x] JSON/CSV loading and Python support for new profiles in the supported schema.
- [x] Current-skill reconstruction using last_review_date, gain and max_level.
- [x] Gap analysis, critical skills, next grade and mapped career goals.
- [x] Candidate filtering: role, grade, prerequisites, availability and completion history.
- [x] Multifactor ranking and score_breakdown.
- [x] Career Digital Twin with skills/readiness before-after simulation.
- [x] WHY THIS / WHY NOT and Recommendation Critic.
- [x] Optional LLM explanation with deterministic fallback.
- [x] Jury/adversarial tests, date-boundary tests and JSON-serializable recommend entry point.
- [ ] Full input-schema validation at the engine boundary; existing checks are partial.

AI suite: 48 tests passed before documentation-conflict resolution. No algorithm changes
without agreement. Recommendations do not persist activity completions.

## Participant 2 - application layer

Ownership: FastAPI, SQLite, future frontend, HTTP contract, access control and startup.
feat/app-ui is already included in main.

- [x] FastAPI profile, history, catalog, mock recommendation, simulation and completion endpoints.
- [x] SQLite storage of profiles, catalog, history and completion results.
- [x] Validated transactional CLI import of the starter dataset.
- [x] Idempotent completion and protection from duplicate/concurrent writes.
- [x] Engine Protocol, mock and fresh database context for each engine call.
- [x] Backend tests for imports, API errors, restart persistence and concurrency.
- [ ] Real engine adapter and end-to-end HTTP progress updates.
- [ ] React/frontend: employee view, trajectory, cards, loading/error/empty states.
- [ ] HR dashboard and aggregates.
- [ ] Server-side employee/HR access control.
- [ ] Import of additional jury profiles/history into an existing database through the application.
- [ ] One-command startup of the complete solution.

CLI import into a new database is not completed jury import. Mock simulation does not
award skill gains or prove an integrated AI completion flow.

## Integration boundary

Both contracts are preserved in docs/api-contract.md: HTTP API and Python AI Engine.
The application expects Engine.recommend(context), while the engine exposes recommend
with employee/history/events/catalog/as_of_date arguments. An application-layer adapter
is required and is not part of this documentation resolution.

The engine owns skill/readiness calculations. The application owns database writes,
transactions, idempotency, selected sessions and authorization. Date/completed_at
semantics require integration tests. Initial integration uses use_llm=False.

## Next steps and acceptance criteria

1. Agree the HTTP/Python mapping and implement the adapter outside the frozen engine.
2. Verify profile -> recommendation -> simulation -> completion -> refreshed progress.
3. Test no double gains, session dates, self_paced and empty recommendation responses.
4. Add employee UI, HR, access control and jury import; test denial of other employees' data.
5. Run both test suites and document reproducible complete startup.
6. Add optional mechanics only after the mandatory scenario works.
