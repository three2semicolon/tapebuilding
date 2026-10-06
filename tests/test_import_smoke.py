"""import smoke test (NEW_FEATURE_GUIDE.md section 5.2 / TEST_PLANS.md section 0).

the cheapest test in the repo: every module a CLI touches must import, and
the names cross-module imports rely on must be re-exported. this is exactly
what would have caught the three ImportErrors found in the refactor.
"""
import importlib

import pytest

pytest.importorskip('mediafile')   # lib.tags exits at import without it

MODULES = [
    'lib.text', 'lib.tags', 'lib.paths', 'lib.catalog.indexer', 'lib.catalog.matcher',
    'organize.cli', 'organize.journal',
    'organize.cleanup', 'organize.cleanup.apply', 'organize.cleanup.grouping',
    'organize.cleanup.common', 'organize.cleanup.resplit', 'organize.cleanup.resplit_plan',
    'organize.preimport', 'organize.preimport.apply', 'organize.preimport.plan',
    'organize.normalize_artists',
]


@pytest.mark.parametrize('mod', MODULES)
def test_module_imports(mod):
    importlib.import_module(mod)


# names other modules import *from the package*, not from the submodule
def test_cleanup_package_reexports():
    from organize import cleanup
    # organize/cli.py
    for name in ('resolve_crate', 'run_cleanup', 'check_tags'):
        assert hasattr(cleanup, name), f"organize.cleanup must re-export {name}"
    # organize/preimport/apply.py, plan.py
    for name in ('group_files', 'is_unrelated_va_collision'):
        assert hasattr(cleanup, name), f"organize.cleanup must re-export {name}"


def test_preimport_package_reexports():
    from organize import preimport
    assert hasattr(preimport, 'stage')   # organize/cli.py
