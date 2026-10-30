---
icon: lucide/folder-open
---

# organize

turn raw downloads into a clean beets-managed crate.

two-pass beets importer: pass 1 groups multi-track albums and matches against musicbrainz; pass 2 imports remaining loose tracks as singletons. runs a pre-import staging pass automatically (regroups the drop into one folder per album before beets ever sees it) unless `--no-preimport`.

```bash
organize import -i <crate>/unorganized -o <crate>
organize import -i ... -o ... --dry-run
organize import -i ... -o ... --pass albums   # album pass only
organize import -i ... -o ... --pass singles  # singles pass only
organize import --export-csv                   # dump library to csv
```

`archive_path` (or `-o`) is required here - no fallback - since this command moves files and rewrites tags.

## organize cleanup

regroups an already-imported crate that ended up with per-track-artist album splits or scattered singletons (the two failure modes beets' own importer is prone to on this library).

```bash
organize cleanup                        # dry-run: print plan, move nothing
organize cleanup --apply                # move files + write albumartist tags
organize cleanup --apply --rebuild-db   # ...then rebuild beets.db from the reorganized crate
organize cleanup --verbose              # print every planned move
organize cleanup --crate <crate>
```

idempotent - re-running on an already-clean crate is a no-op.

## configuration

beets configuration lives in `library_config.yaml` (a machine-specific file) with a path-templated example in `library_config.yaml.example`. see [configuration](config.md).
