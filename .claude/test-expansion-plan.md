# Test Expansion Plan

## Overview
The current test suite (`tests/*.py`) consists of lightweight import/smoke tests that verify modules can be loaded and basic symbols exist. There is no functional coverage of the core behaviors of the packages (download, export, pipeline, import, CLI, organizer, playlists, tapedeck, retry, etc.). This plan outlines the addition of comprehensive unit and integration tests to raise coverage and confidence in the functionality.

---

## Goals
1. **Functional Coverage** – Test actual behavior, not just import existence.
2. **Error/Edge‑Case Handling** – Verify proper handling of failures, empty inputs, and exceptional conditions.
3. **Integration Paths** – Test multi‑step workflows (e.g., download → import → playlist) in isolation.
4. **Maintainability** – Use fixtures, parametrization, and clear naming to keep tests manageable.
5. **CI‑Ready** – All new tests should be discoverable by `pytest` and runnable in a CI pipeline.

---

## Test Additions by Package

### 1. `downloader`
- **File:** `tests/test_downloader_functional.py`
- **Scope:** Real download flow using spotdl/yt‑dlp (via `subprocess`), file‑system side‑effects, error handling.
- **Key Tests:**
  - Successful download of a mock URL (use a local static file as a stand‑in).
  - Retry behavior when spotdl returns a non‑zero exit code.
  - Fallback to yt‑dlp when spotdl fails.
  - Verbose output captures correct log messages.
  - Destination directory creation when missing.
  - Proper cleanup of partially‑downloaded files on error.

### 2. `exporter`
- **File:** `tests/test_exporter.py`
- **Scope:** `write_csv` and `write_manifest` utilities.
- **Key Tests:**
  - Atomic write semantics (tmp file replacement).
  - Header handling (`write_header=False` suppression).
  - CSV formatting (commas, quoting) with special characters.
  - Manifest URL extraction and line‑wise writing.
  - Error handling on unwritable paths (permission errors).

### 3. `pipeline`
- **File:** `tests/test_pipeline.py`
- **Scope:** `Pipeline` class composition and step execution.
- **Key Tests:**
  - Adding steps preserves order.
  - Running a pipeline with a mocked step updates context correctly.
  - Dry‑run vs apply semantics via CLI flags (use `subprocess` to invoke `python -m tapebuilding`).

### 4. `importer`
- **File:** `tests/test_importer.py`
- **Scope:** `import_drop` wrapper around `beets import`.
- **Key Tests:**
  - Correct command line construction (including `--reindex`, `--dry-run`, `-q`).
  - Passing of `verbose` flag influences stdout/stderr.
  - Proper exit on import failure (non‑zero return code).
  - Integration with a temporary crate directory (use `tmp_path`).

### 5. `cli`
- **File:** `tests/test_cli.py`
- **Scope:** `main()` argument parsing and flow control.
- **Key Tests:**
  - `--dry-run` flag prints appropriate message and exits with code 0.
  - `--apply` flag triggers “Apply selected” message.
  - `--only` options filter steps correctly.
  - Help (`-h`) displays expected flags.

### 6. `organize`
- **File:** `tests/test_organize.py` (expand existing)
- **Scope:** `cleanup`, `preimport`, `normalize_artists`, `beets_import`.
- **Key Tests:**
  - `cleanup` correctly identifies album groups (≥2 files) vs singletons.
  - `preimport` stages files into proper `<Artist - Album>/` layout.
  - `normalize_artists` transforms collab strings to canonical form.
  - `beets_import` respects `--dry-run` and `--reindex` flags.

### 7. `retry`
- **File:** `tests/test_retry.py`
- **Scope:** `filter_existing` and list generation logic.
- **Key Tests:**
  - Deduplication across `soft_failures.txt` and `failed_downloads.txt`.
  - Filtering out `track_unavailable` when default option is on.
  - CSV reporting (`--report-csv`) produces sorted, clickable URLs.
  - Manual‑hunt sheet generation with correct columns (`artist, track, album, reason, spotify_url, search`).

### 8. `playlists`
- **File:** `tests/test_playlists.py` (expand existing)
- **Scope:** Playlist resolution, `.m3u8` generation, track matching.
- **Key Tests:**
  - Exact‑title + primary‑artist matching logic.
  - Fallback matching strategies (any‑artist, album).
  - Fuzzy prefix matching with ratio threshold.
  - CSV index rebuild (`--reindex`) updates `.playlist_index.jsonl`.
  - Unmatched track handoff writes correct `unmatched.csv` and `unmatched_urls.txt`.

### 9. `tapedeck`
- **File:** `tests/test_tapedeck.py` (expand existing)
- **Scope:** Load/unload operations, spec resolution, copy vs hardlink.
- **Key Tests:**
  - Path‑relative mirroring preserves crate‑relative structure.
  - Name‑based spec resolution resolves to correct crate paths.
  - Playlist unload respects refcounting and does not delete shared files.
  - `--apply` performs actual file actions; dry‑run only logs.

### 10. Integration / End‑to‑End
- **File:** `tests/test_integration.py`
- **Scope:** Full pipeline (`download_songs` → `playlists --reindex`) on a temporary crate.
- **Key Tests:**
  - End‑to‑end download of a sample URL results in a file under `albums/` or `singles/`.
  - Import step detects the file and updates the beets library (use a mock beets DB).
  - Playlist rebuild writes correct `.m3u8` files with proper relative paths.
  - Cleanup leaves no stray temporary directories.

---

## Test Writing Conventions
- **Fixtures:** Use `tmp_path` (built‑in pytest fixture) for all temporary files/directories.
- **Mocking:** Patch `subprocess.run` and other external commands to avoid real network or filesystem access. Return deterministic `CompletedProcess` objects.
- **Parameterization:** Use `@pytest.mark.parametrize` for multiple input variations (e.g., different URL formats, duplicate tracks).
- **Helpers:** Keep reusable helpers (e.g., `run_tapebuilding_cmd(args, env)`) in `tests/helpers.py`.
- **Coverage:** Aim for at least 80% line coverage on new test files; use `pytest-cov` in CI.

---

## Execution Plan
1. **Create new test files** as listed above.
2. **Implement helper utilities** (`tests/helpers.py`) for common patterns.
3. **Add parametrized test cases** for edge conditions.
4. **Run `pytest` locally** to verify discovery and passing tests.
5. **Integrate into CI** (e.g., GitHub Actions) with `pytest --cov=tapebuilding`.
6. **Iterate** on failing tests, refine expectations, and add missing coverage until all listed test cases pass.

---

## Risks & Mitigations
- **External Dependencies (spotdl/yt‑dlp):** Mock these tools to avoid flaky network calls; ensure tests still simulate command‑line parsing and exit‑code handling.
- **Beets DB Interaction:** Use an in‑memory SQLite beets database or a temporary directory to avoid persisting real library state.
- **File‑SystemRace Conditions:** Always use `tmp_path` and unique subfolders; clean up after each test.
- **Atomic Writes:** Verify that temporary files are correctly replaced; handle permission errors gracefully in CI.

---

### Summary
Expanding the test suite as outlined will transform the current trivial smoke tests into a robust, behavior‑driven suite that validates each functional pathway across the tapebuilding codebase. This will improve confidence in future changes, aid debugging, and meet CI quality gates.