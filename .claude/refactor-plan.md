---
name: refactor-plan
description: Plan for moving packages under src and updating imports
metadata:
  type: project
---

# Refactor Plan for tapebuilding Repository

## Goal
Create a clean, reusable package that can be driven by multiple pipelines and eventually by a lightweight local UI. The package should eliminate duplication, centralize configuration, and provide a composable API.

## Current Structure
```
tapebuilding/
├─ .docs/
│   └─ plans/
│       └─ refactor-plan.md   ← this file
├─ tapebuilding/
│   ├─ __init__.py
│   ├─ core/
│   │   ├─ config.py          # global config & .env loading
│   │   ├─ logger.py          # unified logging setup
│   │   └─ utils.py           # helpers: resolve_source, run_child, etc.
│   ├─ downloader.py           # unified download service
│   ├─ exporter.py             # CSV/manifest writing utilities
│   ├─ retry.py                # retry‑list generation & manual‑hunt CSV
│   ├─ pipeline.py             # composable pipeline builder (DAG)
│   ├─ updater.py              # detect Spotify updates / delta generation
│   ├─ importer.py             # beets import wrapper (idempotent)
│   └─ cli.py                  # thin entry‑point that calls pipeline.run(...)
├─ pipelines/
│   └─ download_songs.py       # thin wrapper that delegates to the new API
├─ organize/
│   ├─ __init__.py
│   └─ beets_import.py         # now imports tapebuilding.importer
│   └─ ...                     # other organize modules
├─ download/
│   ├─ __init__.py
│   ├─ download_spotify.py     # entry‑point that calls tapebuilding.downloader
│   ├─ yt_dlp_downloader.py    # entry‑point that calls tapebuilding.downloader
│   └─ retry_failures.py       # now a CLI around tapebuilding.retry
├─ playlists/
│   ├─ __init__.py
│   ├─ build.py                # now uses tapebuilding.exporter & pipeline hooks
│   └─ ...                     # matcher, m3u, etc.
└─ .env.example                # template for required env vars
```

## Concrete Refactor Tasks

| Priority | Task | What It Removes / Fixes | Deliverable |
|---|---|---|---|
| **1️⃣** | Centralize **.env** loading and global flags (`--format`, `--bitrate`, `--verbose`). | Duplicate `load_dotenv()` calls, scattered argparse defaults. | `tapebuilding/core/config.py` + `tapebuilding/core/logger.py`. |
| **2️⃣** | Create **unified downloader** (`tapebuilding/downloader.py`). | Separate `download_spotify.py` & `yt_dlp_downloader.py` logic; duplicated arg handling. | Function `download(urls: Iterable[str], dest: Path, *, format='mp3', bitrate='320k', verbose=False) -> List[Path]`. |
| **3️⃣** | Abstract **retry / failure handling** into `tapebuilding/retry.py`. | Repeated CSV parsing, manual‑hunt CSV generation. | `generate_retry_list(drop: Path) -> List[str]` and `persist_manual_hunt(csv_path: Path, records: List[Dict])`. |
| **4️⃣** | Consolidate **CSV/manifest export** into `tapebuilding/exporter.py`. | Duplicated `csv.DictWriter` boilerplate across scripts. | Class `ManifestExporter` with shared `_write_csv` helper. |
| **5️⃣** | Refactor **beets import** to be idempotent and testable (`tapebuilding/importer.py`). | Tight coupling to drop directory, no dry‑run flag. | Function `import_drop(drop: Path, crate: Path, *, verbose=False, reindex=False, dry_run=False)`. |
| **6️⃣** | Build a **composable pipeline** (`tapebuilding/pipeline.py`). | Monolithic `pipelines/download_songs.py` that runs steps sequentially. | `Pipeline` class with `add_step(name, callable)`; steps can be toggled individually (`--only download`, `--only import`, etc.). |
| **7️⃣** | Add a **CLI wrapper** (`tapebuilding/cli.py`). | Each script re‑implements its own `argparse` and flow control. | Thin CLI that forwards flags to `pipeline.run(...)`. |
| **8️⃣** | (Optional) Implement a **Rich‑based TUI** (`tapebuilding/ui/console.py`). | Future UI for listing pending tracks, triggering pipelines. | Simple menu that maps menu items to pipeline steps. |
| **9️⃣** | Write **tests** for core functions (downloader, retry, exporter). | Prevent regressions during refactor. | `tests/` with pytest fixtures. |
| **🔟** | Update **setup** (`pyproject.toml`/`setup.cfg`) to expose a console script `tapebuilding`. | Makes the package installable via `uv pip install -e .`. | `[project.scripts] tapebuilding = "tapebuilding.cli:main"` |

## Immediate Cleanup Wins
1. Remove duplicated flag parsing – move all flags to `core/config.py`.  
2. Replace scattered `print` statements with unified `logger`.  
3. Delete unused scripts (`soundbyte_albums.py` if not needed).  
4. Add type hints and a minimal pytest suite.  
5. Introduce a `pyproject.toml` entry point for `tapebuilding`.

## Future UI Sketch
- **CLI menu** (`tapebuilding ui`) with options:  
  1. Pull updates  
  2. Review pending downloads  
  3. Run full sync  
  4. Open manual‑hunt sheet  
- **Implementation** – each menu action triggers the composable pipeline steps, respecting `--apply` vs. dry‑run.  
- **Tech choice** – start with the `rich` library for a terminal UI; later can be wrapped in an Electron‑style desktop app that calls the same Python package over a local HTTP API.

## Next Steps
1. Create the directory layout as shown above.  
2. Implement `tapebuilding/core/config.py` and migrate `.env` loading there.  
3. Build the unified downloader (`tapebuilding/downloader.py`).  
4. Extract the retry logic into `tapebuilding/retry.py`.  
5. Refactor the pipeline in `tapebuilding/pipeline.py` and update `pipelines/download_songs.py` to delegate to it.  
6. Run the test suite after each refactor to ensure no regression.

*This plan is stored at `.docs/plans/refactor-plan.md` for reference and future iteration.*