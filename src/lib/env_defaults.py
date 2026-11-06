"""lib.env_defaults - shared helpers for "env var as CLI default" pattern.

Several packages repeat the same inline logic for resolving an environment
variable as a fallback when a CLI option is at its default. This module
centralises that pattern so call sites read declaratively instead of
re-implementing the same conditional inline.

Usage examples:

    # PLAYLISTS_EXCLUDE: combine CLI + env (CLI first, env appended)
    exclude_names = combine_lists(exclude_names, config.PLAYLISTS_EXCLUDE)

    # DOWNLOAD_PRE_SKIP_EXISTING: apply env only if CLI is at its default (False)
    pre_skip_existing = apply_if_default(pre_skip_existing, config.DOWNLOAD_PRE_SKIP_EXISTING, False)

    # DOWNLOAD_COOKIES_FILE: apply env only if CLI is None
    cookie_file = apply_if_none(cookie_file, config.DOWNLOAD_COOKIES_FILE)

    # DOWNLOAD_RETRIES: apply env only if CLI is at its default (0)
    retries = apply_if_default(retries, config.DOWNLOAD_RETRIES, 0)
"""


def combine_lists(cli_values, env_values):
    """Combine a CLI list with an env list (CLI values first, env appended).

    Returns cli_values unchanged if env_values is empty/falsy. Returns a new
    list in all cases (callers should not mutate the result in place expecting
    it to be the original list).
    """
    if not env_values:
        return cli_values
    if cli_values:
        return list(cli_values) + list(env_values)
    return list(env_values)


def apply_if_default(cli_value, env_value, default_sentinel):
    """Apply env_value only when cli_value equals default_sentinel and env_value is not None.

    Otherwise returns cli_value unchanged. Use this when the CLI default is a
    concrete value (False, 0, etc.) and "not yet set by the user" means
    cli_value == default_sentinel.
    """
    if cli_value == default_sentinel and env_value is not None:
        return env_value
    return cli_value


def apply_if_none(cli_value, env_value):
    """Apply env_value only when cli_value is None and env_value is truthy.

    Otherwise returns cli_value unchanged. Use this when the CLI default is
    None and "not yet set by the user" means cli_value is None.
    """
    if cli_value is None and env_value:
        return env_value
    return cli_value
