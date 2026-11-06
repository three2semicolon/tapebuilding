"""lib.results - shared structured-result helpers.

Centralises step-result aggregation so core/download.py and
core/process_unmatched.py (and any future orchestrator) share one
implementation instead of duplicating it.
"""


def calculate_overall_result(results):
    """Calculate the overall result from a list of step result dicts.

    Each step dict is expected to have keys ``ok`` (bool) and ``skipped``
    (bool). Skipped steps are ignored; the overall result is True only if
    every non-skipped step has ``ok == True``.

    Args:
        results: list of step result dicts, e.g.
            [{'step': 'download', 'ok': True, 'skipped': False}, ...]

    Returns:
        bool: True if all non-skipped steps succeeded, False otherwise.
    """
    return all(r['ok'] for r in results if not r['skipped'])
