# Final Project Dashboard Implementation Plan

> **Execution note:** Execute this plan in `/home/bell/projects/Agricultural-Data-Analytics/.worktrees/final-project-dashboard`.
> All delegated agents must use GLM 5.3 only. Do not expose or commit credentials.

**Goal:** Complete Assignment 9 by adding deterministic field/soil filtering,
dynamic agronomic captions, the missing EDA figure, final documentation, and
submission screenshots to the existing GitHub Pages dashboard.

**Architecture:** Keep the current Python-generated JSON plus dependency-free
HTML/CSS/vanilla JavaScript dashboard. Extend the JSON with a validated,
deterministically sorted `fields` array assembled from existing Assignment 2,
5, 7, and 8 products. Compute filtered package summaries in the browser and
render cautious, deterministic caption templates. Do not add Streamlit, Dash,
an API, a database, or a runtime language-model dependency.

## Task 1 — Establish the failing contract

**Files:** `tests/test_dashboard.py`

1. Extend the temporary dashboard fixtures with minimal Assignment 2 GeoJSON,
   Assignment 7 integrated rows, and Assignment 8 soil rows.
2. Require the new `fields` payload key and its exact per-field schema.
3. Add tests for sorted IDs, finite values, cross-source ID mismatch rejection,
   and deterministic payload generation.
4. Add structural tests for two disabled native filter controls, labels,
   reset control, live narrative region, and the Assignment 3 image.
5. Add documentation tests for the final-project README section and
   `docs/AI_DOCS.md`.
6. Run the dashboard tests and confirm the new contract fails before changing
   production files.

## Task 2 — Build the per-field dashboard payload

**Files:** `scripts/build_dashboard.py`, `docs/data/dashboard.json`

1. Add the committed Assignment 2 GeoJSON, Assignment 7 CSV, and Assignment 8
   CSV to the input contract.
2. Read GeoJSON properties with the standard library and validate exactly 25
   unique field IDs.
3. Validate identical field-ID sets across crop, NDVI, integration, soil, and
   geometry inputs.
4. Join one record per field containing the approved data contract, retaining
   crop pixel counts so filtered crop dominance uses the same definition as the
   package KPI.
5. Reject missing, duplicate, mismatched, or non-finite field data.
6. Regenerate sorted `docs/data/dashboard.json` and run the dashboard tests.

## Task 3 — Add accessible filtering and narratives

**Files:** `docs/index.html`, `docs/styles.css`

1. Add native, labelled Field ID and Soil Type selects plus a reset button,
   disabled until validated data loads.
2. Add a polite live narrative region and selection status.
3. Populate options from `fields`, apply both filters, render an explicit
   no-match state, and update filterable KPI values.
4. Mark county-wide weather and scene values when a filter is active.
5. Add deterministic narrative bands for NDVI `< 0.3`, `0.3–0.6`, and `> 0.6`,
   with scouting language and single-scene/SSURGO limitations.
6. Embed `crop_rotation_patterns.png` with descriptive alternative text and a
   source caption.
7. Preserve skip-link behavior, keyboard focus styling, reduced-motion rules,
   attribution, and limitation copy.

## Task 4 — Complete final documentation

**Files:** `README.md`, `docs/AI_DOCS.md`

1. Update the final branch entry to `feature/final-project-dashboard`.
2. Add the final project description, live Pages URL, technologies, local
   dashboard serving command, 25-field/yield limitation, and screenshot links.
3. Add an honest AI usage summary covering assistance, verification, public-data
   provenance, non-fabrication rules, and human review.
4. State that the Google Classroom URL, screenshots, and final reflection still
   require the user's submission action.

## Task 5 — Verify and capture evidence

1. Run the focused dashboard tests and the full Python test suite.
2. Regenerate the dashboard and run `scripts.verify_repository`.
3. Run `git diff --check` and verify no secrets, private archives, absolute
   machine paths, or missing local references are tracked.
4. Serve `docs/` locally and capture three to five honest screenshots of the
   package view and different dashboard sections/filter states.
5. Ensure screenshots are below repository size limits and linked from README.

## Task 6 — Publish

1. Commit the implementation in small logical commits on
   `feature/final-project-dashboard`.
2. Push the branch using the process-only GitHub token from the configured
   Hermes secret environment; never print or persist it.
3. Open a pull request, run its checks, and merge it into `main`.
4. Push/verify `main` and recheck the public GitHub Pages dashboard and asset
   links.
5. Report the PR, merged commit, public URL, test counts, and any remaining
   Google Classroom-only actions.

→ skipped: Streamlit/Dash, a runtime AI API, and a 200-field data migration;
add only if the instructor explicitly rejects the approved 25-field scope.
