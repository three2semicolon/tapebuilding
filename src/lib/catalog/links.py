"""lib.catalog.links - manual track -> crate-file associations.

when the matcher can't find a track that's already on disk (tags too
different from the playlist row for any tier to hit), the fallback prompt
lets the user point at the existing file. this module stores that
association instead of copying the file under the name the matcher wanted,
which used to leave two copies of the same song in the crate.

storage: a single JSON sidecar next to the index sidecar
(exports_dir()/.manual_links.json) - deliberately NOT a column on
unmatched.csv, which is regenerated on every pull and would lose it.

    {
      "https://open.spotify.com/track/abc": {
        "path": "albums/Some Artist/Some Album/03 - Song.flac",
        "basename": "03 - Song.flac",
        "artist": "Some Artist",
        "title": "Song",
        "added": "2026-10-30"
      }
    }

- keys are link_key(url): the track URL minus query string/fragment/trailing
  slash, so "?si=..." share-links and "?in=..." soundcloud context don't
  create distinct identities. soundcloud rows work the same way, since their
  URL lives in the same spotify_url column.
- paths are crate-relative with forward slashes, so the crate can move
  between mounts/machines without invalidating every link.
- basename is kept so check_links() can re-find a file that was moved
  (e.g. by organize cleanup). it can't recover a file that was *renamed*
  (beets path formats do that) - those fall through to normal tag matching,
  which is what would have found them anyway.

only files the indexer actually walks can be linked: anything under the
indexer's skipped top-level dirs (duplicates/, unorganized/, playlists/,
...) is rejected at link time, because the matcher resolves links through
the catalog and would never see them.
"""

import datetime
import json
import os
from collections import defaultdict
from urllib.parse import urlsplit

from lib.paths import archive_path, exports_dir
from lib.tags import EXTENSIONS
from .indexer import _SKIP_TOPLEVEL

LINKS_NAME = '.manual_links.json'


class LinksError(Exception):
    """the links file exists but can't be read/parsed. writers must never
    treat this as "empty" - that would overwrite the user's associations."""


class LinkRejected(ValueError):
    """the given file can't be linked (reason in the message)."""


class OutsideCrate(LinkRejected):
    """the file isn't under the crate root at all - callers may want to copy
    it in instead."""


class NotIndexed(LinkRejected):
    """the file is inside the crate but under a top-level dir the indexer
    skips (duplicates/, unorganized/, ...), so a link could never resolve."""


def links_path(exports_dir_value=None):
    return os.path.join(exports_dir_value or exports_dir(), LINKS_NAME)


def link_key(url):
    """stable identity for a track URL: scheme://host/path, no query,
    fragment or trailing slash. non-URL strings are just stripped."""
    s = (url or '').strip()
    if not s or '://' not in s:
        return s
    parts = urlsplit(s)
    return f"{parts.scheme}://{parts.netloc}{parts.path}".rstrip('/')


def path_key(p):
    """comparison key for filesystem paths (symlinks resolved, case-folded
    on Windows)."""
    return os.path.normcase(os.path.realpath(p))


def load_links(path=None):
    """read the sidecar -> dict. missing file -> {}. unreadable/corrupt ->
    LinksError (see its docstring for why this isn't {})."""
    path = path or links_path()
    if not os.path.exists(path):
        return {}
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        raise LinksError(f"can't read {path}: {e}") from e
    if not isinstance(data, dict):
        raise LinksError(f"{path} is not a JSON object")
    return data


def load_links_safe(path=None):
    """read-only convenience for the matcher: never raises, so a bad links
    file degrades to "no manual links" instead of breaking a playlist build.
    (writers use load_links() directly so they can't clobber a bad file.)"""
    try:
        return load_links(path)
    except LinksError as e:
        print(f"warning: ignoring manual links - {e}")
    except Exception:
        # path resolution itself failed (no exports dir configured, etc.)
        pass
    return {}


def save_links(links, path=None):
    path = path or links_path()
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(links, f, ensure_ascii=False, indent=2, sort_keys=True)
        f.write('\n')
    os.replace(tmp, path)


def crate_relpath(file_path, library_root):
    """validate that file_path can be linked and return its crate-relative,
    forward-slash path. raises OutsideCrate / NotIndexed / LinkRejected."""
    if not os.path.isfile(file_path):
        raise LinkRejected(f"not a file: {file_path}")
    root = os.path.realpath(library_root)
    full = os.path.realpath(file_path)
    try:
        rel = os.path.relpath(full, root)
    except ValueError:  # different drive on Windows
        raise OutsideCrate(f"{file_path} is outside the crate ({root})")
    parts = rel.split(os.sep)
    if parts[0] == '..' or os.path.isabs(rel):
        raise OutsideCrate(f"{file_path} is outside the crate ({root})")
    skipped = {os.path.normcase(d) for d in _SKIP_TOPLEVEL}
    if len(parts) > 1 and os.path.normcase(parts[0]) in skipped:
        raise NotIndexed(
            f"{parts[0]}/ isn't indexed, so a link into it could never match "
            f"- import it into the crate first"
        )
    if os.path.splitext(full)[1].lower() not in EXTENSIONS:
        raise LinkRejected(f"not a recognised audio file: {file_path}")
    return '/'.join(parts)


def add_link(key, file_path, artist='', title='', library_root=None, links_file=None):
    """associate track URL `key` with an existing crate file. returns the
    stored crate-relative path. raises LinkRejected (and subclasses) if the
    file can't be linked, LinksError if the existing links file is corrupt."""
    k = link_key(key)
    if not k:
        raise LinkRejected("no track URL to key the link on")
    rel = crate_relpath(file_path, library_root or archive_path())
    links = load_links(links_file)
    links[k] = {
        'path': rel,
        'basename': rel.rsplit('/', 1)[-1],
        'artist': artist or '',
        'title': title or '',
        'added': datetime.date.today().isoformat(),
    }
    save_links(links, links_file)
    return rel


def _ascii_key(s):
    """ASCII-only lowercase key for tolerant path comparison.

    Strips all non-ASCII characters (CJK, Hangul, etc.) so that paths which
    differ only in non-Latin characters still match. Used as a last-resort
    fallback when exact and normalization-based matching both fail.
    """
    return ''.join(c for c in (s or '') if ord(c) < 128).lower()


def resolve_link(link, library_root, catalog=None):
    """a stored link -> absolute path, or None if the file isn't there."""
    rel = (link or {}).get('path')
    if not rel:
        return None
    full = os.path.join(library_root, *rel.split('/'))
    if os.path.isfile(full):
        return full
    # Try Unicode normalization (NFC/NFD) for files whose on-disk encoding
    # differs from what's stored in the links file.
    found = _resolve_link_by_normalization(library_root, rel)
    if found:
        return found
    # Fallback: basename matching against catalog index (handles moved files
    # and minor character differences).
    if catalog is not None:
        return _resolve_link_by_catalog(link, library_root, catalog, rel)
    return None


def _resolve_link_by_normalization(library_root, rel):
    """Try NFC/NFD normalization of the stored path; return match or None."""
    import unicodedata
    for form in ('NFC', 'NFD'):
        normalized = unicodedata.normalize(form, rel)
        if normalized != rel:
            full2 = os.path.join(library_root, *normalized.split('/'))
            if os.path.isfile(full2):
                return full2
    return None


def _resolve_link_by_catalog(link, library_root, catalog, rel):
    """Fall back to basename matching against catalog index."""
    base = (link.get('basename') or rel.rsplit('/', 1)[-1]).lower()
    base_ascii = _ascii_key(base)
    exact_cands = []
    ascii_cands = []
    for entry in catalog:
        p = entry.get('path')
        if not p:
            continue
        try:
            cand_rel = crate_relpath(p, library_root)
        except LinkRejected:
            continue
        cand_base = os.path.basename(p).lower()
        if cand_base == base:
            exact_cands.append(cand_rel)
        elif base_ascii and _ascii_key(cand_base) == base_ascii:
            ascii_cands.append(cand_rel)
    if len(exact_cands) == 1:
        return os.path.join(library_root, *exact_cands[0].split('/'))
    if not exact_cands and len(ascii_cands) == 1:
        return os.path.join(library_root, *ascii_cands[0].split('/'))
    return None


def _build_by_base_index(catalog, root):
    """Build a basename -> list of crate-relative paths map from the catalog."""
    by_base = defaultdict(list)
    for e in catalog:
        p = e.get('path')
        if not p:
            continue
        try:
            by_base[os.path.basename(p).lower()].append(crate_relpath(p, root))
        except LinkRejected:
            continue
    return by_base


def _classify_link(link, by_base):
    """Classify a broken link against the by-basename index.

    Returns ('relocated', cand), ('ambiguous', cands), or ('missing', None).
    """
    base = (link.get('basename') or (link.get('path') or '').rsplit('/', 1)[-1]).lower()
    cands = by_base.get(base, [])
    if not cands:
        # Tolerant fallback: ASCII-only basename comparison (handles CJK /
        # Hangul character differences between stored path and on-disk file).
        base_ascii = _ascii_key(base)
        if base_ascii:
            for cand_base, cand_paths in by_base.items():
                if _ascii_key(cand_base) == base_ascii:
                    cands.extend(cand_paths)
    if len(cands) == 1:
        return ('relocated', cands[0])
    if cands:
        return ('ambiguous', cands)
    return ('missing', None)


def check_links(library_root=None, links_file=None, catalog=None, fix=False):
    """verify every stored link still points at a file.

    returns {'ok': [...], 'relocated': [...], 'ambiguous': [...],
    'missing': [...]}; each item is (key, link, new_rel_or_candidates).
    a broken link whose basename now exists exactly once in the catalog is
    'relocated' (and rewritten when fix=True); several candidates ->
    'ambiguous', none -> 'missing' (neither is touched - the matcher just
    falls back to normal tag matching for those rows).

    the catalog is only loaded (via get_index()) if something is broken.
    """
    root = library_root or archive_path()
    links = load_links(links_file)
    report = {'ok': [], 'relocated': [], 'ambiguous': [], 'missing': []}
    by_base = None

    for key, link in sorted(links.items()):
        if resolve_link(link, root):
            report['ok'].append((key, link, None))
            continue
        if by_base is None:
            if catalog is None:
                from .indexer import get_index
                catalog = get_index(root)
            by_base = _build_by_base_index(catalog, root)
        status, value = _classify_link(link, by_base)
        if status == 'relocated':
            report['relocated'].append((key, dict(link), value))  # snapshot: fix mutates `link`
            if fix:
                link['path'] = value
                link['basename'] = value.rsplit('/', 1)[-1]
        elif status == 'ambiguous':
            report['ambiguous'].append((key, link, value))
        else:
            report['missing'].append((key, link, None))

    if fix and report['relocated']:
        save_links(links, links_file)
    return report


def print_check_report(report, fixed=False):
    def label(key, link):
        who = ' - '.join(x for x in (link.get('artist'), link.get('title')) if x)
        return f"{who or key}"

    print(f"manual links: {len(report['ok'])} ok, {len(report['relocated'])} relocated, "
          f"{len(report['ambiguous'])} ambiguous, {len(report['missing'])} missing")
    for key, link, new in report['relocated']:
        print(f"  {'fixed' if fixed else 'moved'}: {label(key, link)}  {link['path']} -> {new}")
    for key, link, cands in report['ambiguous']:
        print(f"  ambiguous: {label(key, link)}  ({len(cands)} files named {link.get('basename')})")
    for key, link, _ in report['missing']:
        print(f"  missing: {label(key, link)}  {link.get('path')}")
    if report['relocated'] and not fixed:
        print("re-run with --fix to rewrite the relocated links.")
