# Career Quest work plan

Both participants' components are implemented. The AI Engine is frozen; FastAPI
now uses RealAIEngineAdapter. Final defense acceptance remains pending. Application status reflects commit 653c6a3.

## Project setup

- [x] Career Quest selection and mandatory requirements.
- [x] GitHub repository and participant branches.
- [x] Dataset analysis, relationships, constraints and documented ambiguities.

## Participant 1 - AI Engine

Ownership: backend/app/engine/, tests/ and algorithm documentation; feat/ai-engine.

- [x] JSON/CSV loading and supported imported profiles.
- [x] Current skill reconstruction after last_review_date using gain/max_level.
- [x] Trajectory/gap engine, next-grade requirements, career targets and critical gaps.
- [x] Eligibility: role, grade, prerequisites, availability and completion history.
- [x] Deterministic multifactor ranking with score_breakdown.
- [x] Career Digital Twin and skills/readiness before-after.
- [x] WHY THIS / WHY NOT and independent-evidence Recommendation Critic.
- [x] Optional OpenAI explanation and deterministic fallback.
- [x] AI, jury/adversarial, review-date and JSON-serialization tests.
- [x] Public recommend entry point and complete response example.

The AI suite previously passed 48 tests. Tests were not rerun during this documentation
resolution. Full import-schema validation remains the application's responsibility;
engine boundary checks are partial. No algorithm changes without agreement.

## Participant 2 - application

Ownership: FastAPI, SQLite, frontend/, auth, HTTP contract and startup; feat/app-ui.

- [x] FastAPI and SQLite: profiles, catalog, history, simulations and completions.
- [x] Validated transactional CLI import of the original dataset.
- [x] Employee/HR authentication, sessions and server-side access control.
- [x] React + TypeScript + Vite frontend and employee dashboard.
- [x] Skills, history, trajectory UI and critical gaps.
- [x] Recommendation cards and loading/error/empty/fallback states.
- [x] Simulation/completion workflow with refreshed data.
- [x] Idempotency, duplicate/concurrent completion protection and club sessions.
- [x] HR analytics: common gaps, employees without recommendations, participation.
- [x] Additive jury JSON profiles / CSV history import with preview and atomic validation.
- [x] Engine Protocol and MockEngine with reconstructed skills.
- [x] Application and browser tests for implemented workflows.
- [x] One-command Unix startup: install, build, import and serve through start.sh.

Mock still returns catalog-order recommendations and null readiness/score. Browser
API fixtures do not prove real AI integration. The launcher uses .venv/bin/python;
native Windows needs manual commands or a later portability fix.

## Remaining integration and acceptance

- [x] Connect FastAPI to the REAL AI Engine via RealAIEngineAdapter.
- [x] Map recommend(context), trajectory(context), simulate(context, request), including
      current_skills, skill_changes, readiness and consistent target semantics.
- [x] Expose WHY THIS / WHY NOT, readiness and explanation_source; keep score_breakdown/Critic in Python.
- [ ] Validate completed_at versus original history/session date without double gains.
- [ ] Run final integrated E2E tests with real backend, AI Engine and frontend.
- [ ] Validate final defense scenario, including jury profiles, HR and access denial.
- [ ] Verify final README commands and submission materials.

## Integration ownership and sequence

Both contracts are in docs/api-contract.md. The engine owns skill, gap, ranking and
readiness calculations. The application owns authorization, transactions, idempotency,
session selection, validation and persistence. Stored skills remain the review snapshot.

1. Implement the adapter outside backend/app/engine/ using use_llm=False.
2. Verify E0002, EV_005 and readiness 62 to 66 at the dataset snapshot.
3. Verify recommendation -> simulation -> valid completion -> refreshed skills,
   history, trajectory and recommendations, including duplicate/empty cases.
4. Verify jury imports, date boundaries, employee isolation and HR aggregation.
5. Run both Python suites, frontend build, browser tests and real integrated E2E.
6. Verify optional LLM failure preserves deterministic selection and explanations;
   avoid LLM calls per employee in HR aggregation.
7. Validate the defense scenario and final README before submission.

## Integration validation results

- Python: 137 passed (48 frozen AI tests, 89 application/integration tests), plus
  200 dataset subtests. All 200 profiles also pass adapter consistency validation.
- E0002: EV_005, score 5.408333, readiness 62 -> 66.
- Completion/replay: history grows once, stored assessment remains unchanged,
  reconstructed skills and recommendations recalculate; repeated key replays the result.
- Frontend: production build passed; 15 Playwright scenarios passed, including AI cards.
- Frozen backend/app/engine/ has no changes. No commit or push performed.

The separate final defense scenario, real-browser/live-server E2E and submission
verification remain pending. Scheduled completion-date mismatches return explicit
422 rather than guessing dates; native Windows launcher portability remains pending.
