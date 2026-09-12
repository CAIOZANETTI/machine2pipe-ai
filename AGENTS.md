# AGENTS.md

## Mission

Build Machine2Pipe AI as a reproducible, web-hosted field agent that connects a pipe project, real telemetry, photo evidence, and engineer confirmation through Telegram.

## Read first

Before changing code, read:

1. `README.md`
2. `docs/IMPLEMENTATION_PLAN.md`
3. Existing tests and the modules touched by the task

## Source of truth

- Product scope and architecture: `README.md`
- Task order and acceptance criteria: `docs/IMPLEMENTATION_PLAN.md`
- Real telemetry source: `CAIOZANETTI/gps_maquina`
- Runtime target: Railway
- Dashboard: Streamlit
- Persistence: SQLite on a Railway persistent volume

If implementation and documentation disagree, stop and update the documentation in the same change.

## Engineering boundary

Deterministic Python must perform:

- coordinate and timestamp validation;
- CRS conversion;
- distances, chainage, and segment matching;
- engine, movement, dwell, and event-window calculations;
- data persistence and aggregate totals.

AI may perform:

- photo and text interpretation;
- confidence-aware classification;
- action selection: ignore, log, notify, ask;
- concise explanations;
- structured extraction from engineer replies;
- optional Exa research.

AI must never calculate authoritative engineering quantities, infer installed length from presence alone, or claim measured depth from an unscaled image.

## Main branch workflow

All project work is committed directly to `main`.

Before editing:

1. fetch the latest `main`;
2. inspect recent commits;
3. select an unchecked backlog item;
4. confirm that another agent is not changing the same files.

Before pushing:

1. run the relevant tests;
2. review the diff for secrets and unrelated changes;
3. use a small descriptive commit;
4. update `docs/CONTRIBUTIONS.md`;
5. push without rewriting history.

Never force-push, reset, or revert another contributor's work without Caio's explicit approval. If `main` changed during the task, integrate the new work before pushing.

## Collaboration rules

- Work on one backlog item at a time.
- State the targeted backlog item in the commit description.
- Prefer small, reviewable commits.
- Do not silently change a data contract.
- Add or update tests for deterministic logic.
- Do not edit unrelated files.
- Do not commit generated telemetry, private photos, API keys, tokens, or `.env`.
- Use fixtures or authorized samples in tests.
- Preserve input data unchanged; write derived data separately.
- Record assumptions in code comments only when they are not obvious from tests or names.

## Coordination between coding agents

Before starting:

1. Check recent commits and open work.
2. Choose an unchecked item from `docs/IMPLEMENTATION_PLAN.md`.
3. Avoid files currently being modified by another agent.
4. Report files changed, tests run, and unresolved risks when handing off.

Suggested ownership split:

- **Claude — platform/data:** deployment, configuration, SQLite, Parquet, KML/KMZ, and geospatial calculations.
- **Codex — interaction/integration:** Telegram, photos, vision output, agent tools, Exa integration, review, and system integration.
- **Caio — product/engineering:** KMZ scope, field meaning, historical ground truth, thresholds, and acceptance of engineering interpretations.

## Definition of done for a code change

A change is complete only when:

- its acceptance criterion is satisfied;
- tests pass locally;
- secrets are absent;
- errors are handled visibly;
- documentation is updated when behavior changes;
- the handoff lists the exact next action.

## Commands

Expected commands once the scaffold exists:

```bash
pytest
streamlit run app/streamlit_app.py
python worker.py
```

The deployed start command must launch both the public Streamlit process and the worker, or define them as separate Railway services.
