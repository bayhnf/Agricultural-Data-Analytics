# AI Usage Disclosure

This portfolio documents how AI tools were used, verified, and limited while
building this project. It is written to be honest rather than promotional.

## What AI did

- **Code generation and assistance.** AI assistants generated or helped write
  analysis scripts (`scripts/`), the dashboard builder
  (`scripts/build_dashboard.py`), the repository privacy verifier
  (`scripts/verify_repository.py`), the static dashboard markup, styling, and
  script in `docs/`, and supporting notebooks.
- **Tests.** AI wrote or assisted with the unit tests in `tests/`, including
  the dashboard data-contract, page-structure, and documentation tests.
- **Documentation.** AI drafted or assisted with this file, the `README.md`,
  reports under `docs/reports/`, and the design and plan notes under
  `docs/superpowers/`.

## How outputs were verified

- Every analysis and dashboard artifact is regenerated deterministically from
  committed inputs; repeated builds produce identical output.
- Unit tests (`python -m unittest discover -s tests`) and the repository
  verifier (`python -m scripts.verify_repository`) are run and their results
  reviewed, not just assumed to pass.
- Human review of the dashboard, figure correctness, source attribution, and
  limitation language will be completed before the filtered dashboard is
  published to GitHub Pages.
- No number, figure, or claim in this repository is accepted from AI output
  without checking it against the pipeline outputs or the public sources.

## Data

- All analysis input is public data: USDA NASS Cropland Data Layer, USDA ARS
  ACPF field boundaries, Copernicus Sentinel-2 (via Element 84 search),
  NASA POWER weather, and USDA NRCS SSURGO soil data.
- No private, purchased, or course-proprietary dataset was used or published.
- No synthetic agricultural values were invented; where a layer (such as
  measured yield) does not exist in the sources, the dashboard discloses the
  gap instead of estimating it.

## What AI did not do

- AI did not decide the study area, scope, or project direction; those were
  human decisions.
- AI did not submit anything to Google Classroom or any external service.
- AI did not handle, read for its own purposes, or publish credentials,
  tokens, `.env` files, Google Classroom material, or other private content.
- AI did not generate the agricultural data itself; every value traces to a
  cited public source recorded in the provenance manifests.

## Runtime AI

- The dashboard does not call any AI or language-model API at runtime. The
  dynamic captions are deterministic templates generated in the browser from
  the committed data, not AI-generated text on load.

## Credentials and privacy

- Repository scanning rejects tracked secrets, OAuth tokens, private course
  archives, and machine-local paths. The verifier is run before the repository
  goes public; no credential or private material is handled here.
