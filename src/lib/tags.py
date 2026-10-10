"""lib.tags - read/write audio tags, and the crate-file grouping primitives
built on top of them.

this is the toolkit half of what used to be organize/cleanup.py: reading
tags, sanitizing filenames, walking a directory tree for audio files, and
picking a canonical albumartist/album for a group of files. organize.cleanup
now imports these and keeps only its regroup-in-place *policy* on top; so
does organize.preimport, and lib.catalog.indexer for the crate-wide index.
"""

import collections
import os
import re
import shutil
import sys
import unicodedata

from lib.text import normalize_key, normalize_album, strip_edition_suffix, split_artists, group_key

try:
    from mediafile import MediaFile
except ImportError:  # pragma: no cover
    sys.exit("mediafile not installed - run `uv sync` first (beets pulls it in).")

EXTENSIONS = ('.mp3', '.flac', '.m4a', '.opus', '.ogg', '.wav', '.aac')

_ILLEGAL_RE = re.compile(r'[\\/:*?"<>|]')



def sanitize(s):
    """filesystem-safe path component from a tag string.
    Replace illegal characters with '_' (beets-style) instead of deleting."""
    s = _ILLEGAL_RE.sub('_', s or '')
    s = s.strip().rstrip('.')
    return s or '_'


def primary_token(raw):
    """first collaborator segment - "A & B" / "A & B & C" -> "A". narrower
    than lib.text.primary_artist: only splits on & or / (album-artist
    strings), not the full feat/x/vs/comma set used for track credits."""
    return re.split(r'\s*(?:&|/)\s*', raw or '', maxsplit=1)[0].strip()


def read_tags(path):
    """return a dict of {path, artist, albumartist, album, title, track,
    disc, length} for one audio file, or None on read error. length is in
    seconds (0.0 if unavailable)."""
    try:
        m = MediaFile(path)
    except Exception:
        return None
    return {
        'path': path,
        'artist': (m.artist or '').strip(),
        'albumartist': (m.albumartist or '').strip(),
        'album': (m.album or '').strip(),
        'title': (m.title or '').strip(),
        'track': m.track or 0,
        'disc': getattr(m, 'disc', 0) or 0,
        'length': float(m.length) if m.length else 0.0,
    }


def find_duplicates(files):
    """find potential duplicate tracks.
    groups by (group_key(artist), group_key(title)) and disc number.
    returns list of groups with 2+ files where track times are within ~2 seconds.
    """
    if not files:
        return []

    # Import here to avoid circular dependencies
    from lib.text import group_key

    # Group by (artist_key, title_key, disc)
    groups = collections.defaultdict(list)
    for f in files:
        artist_key = group_key(f['artist'] or '')
        title_key = group_key(f['title'] or '')
        disc = f.get('disc', 0)
        key = (artist_key, title_key, disc)
        groups[key].append(f)

    # Find groups with duplicates (2+ files) and check time difference
    duplicates = []
    for key, group_files in groups.items():
        if len(group_files) < 2:
            continue

        # Check if any pair has similar track length (within 2 seconds)
        has_near_duplicates = False
        for i in range(len(group_files)):
            for j in range(i + 1, len(group_files)):
                f1 = group_files[i]
                f2 = group_files[j]
                len1 = f1.get('length', 0)
                len2 = f2.get('length', 0)
                if abs(len1 - len2) <= 2.0:  # Within 2 seconds
                    has_near_duplicates = True
                    break
            if has_near_duplicates:
                break

        if has_near_duplicates:
            duplicates.append(group_files)

    return duplicates


def artist_tokens(f):
    """group_key tokens for one file's raw `artist` tag ONLY (split on the
    usual credit separators, empty tokens dropped).

    deliberately does NOT include `albumartist`: cleanup/preimport write that
    tag themselves, so a previously-wrong merge leaves every member carrying
    the same self-inflicted albumartist ('Various Artists', or the winning
    artist). unioning it in makes unrelated tracks look related and defeats
    every split check (BUGFIX_PLAN.md, Bug 2b, "poison" problem)."""
    tokens = set()
    for a in split_artists(f.get('artist') or ''):
        token = group_key(a)
        if token:
            tokens.add(token)
    return tokens


def split_group(members):
    """partition members into groups that transitively share at least one
    artist_tokens() token (raw `artist` tag only - never albumartist) - a
    simple union-find over pairwise token overlap. members whose token set is
    disjoint from everyone else end up alone in their own group.

    Returns list of groups (each group is a list of file dicts), in
    first-seen order.
    """
    parent = list(range(len(members)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(i, j):
        ri, rj = find(i), find(j)
        if ri != rj:
            parent[ri] = rj

    token_sets = [artist_tokens(m) for m in members]
    for i in range(len(members)):
        for j in range(i + 1, len(members)):
            if token_sets[i] & token_sets[j]:
                union(i, j)

    components = collections.OrderedDict()
    for i, m in enumerate(members):
        components.setdefault(find(i), []).append(m)
    return list(components.values())


def write_tag(path, **fields):
    """write one or more MediaFile fields (e.g. albumartist='X') if they
    differ from the current value. generalizes the old write_albumartist."""
    try:
        m = MediaFile(path)
        changed = False
        for field, value in fields.items():
            current = getattr(m, field, None) or ''
            # Compare exact NFC strings for case-only/non-Latin awareness
            if unicodedata.normalize('NFC', current) != unicodedata.normalize('NFC', value):
                setattr(m, field, value)
                changed = True
        if changed:
            m.save()
    except Exception as e:
        print(f"  tag-write failed: {path} ({e})", file=sys.stderr)


def canonical_albumartist(files):
    """pick the folder label for an album group: dominant (albumartist|artist)
    string, else dominant primary collaborator, else "Various Artists".
    returns the original-cased label (not normalized)."""
    counts = collections.Counter()
    orig = {}
    for f in files:
        raw = (f['albumartist'] or f['artist'] or '').strip()
        if raw:
            k = normalize_key(raw)
            counts[k] += 1
            orig.setdefault(k, raw)
    total = sum(counts.values())
    if total:
        top, top_n = counts.most_common(1)[0]
        if top_n >= total * 0.5:
            return orig[top]
        pc = collections.Counter()
        porig = {}
        for f in files:
            raw = (f['albumartist'] or f['artist'] or '').strip()
            if not raw:
                continue
            p = primary_token(raw)
            k = normalize_key(p)
            pc[k] += 1
            porig.setdefault(k, p)
        if pc:
            ptop, ptop_n = pc.most_common(1)[0]
            if ptop_n >= total * 0.5:
                return porig[ptop]
    return 'Various Artists'


def dominant_album(files):
    """most common original-cased album string among the group's files."""
    c = collections.Counter()
    orig = {}
    for f in files:
        a = f['album']
        if a:
            c[normalize_key(a)] += 1
            orig.setdefault(normalize_key(a), a)
    if not c:
        return ''
    # Deterministic tie-break: alphabetical ordering of original-cased strings
    return orig[c.most_common(1)[0][0]]


def canonical_album(files):
    """merge edition strings while keeping edition marker (D2).
    returns the original-cased album string with preferred edition."""
    if not files:
        return ''

    # Group by normalized album (edition-stripped)
    groups = collections.defaultdict(list)
    for f in files:
        album = f['album'] or ''
        key = normalize_album(album)
        groups[key].append((album, f))  # Store original album and file ref

    # For each group, select the best edition variant
    selected_albums = []
    for key, album_files in groups.items():
        if len(album_files) == 1:
            # Only one variant, use it
            selected_albums.append(album_files[0][0])
        else:
            # Multiple variants - pick the one with edition marker
            # Prefer: 1) has edition marker, 2) longer/more specific edition, 3) alphabetical
            best_album = None
            best_score = (-1, -1, '')  # (has_edition, length, name)

            for album, _ in album_files:
                # Check if this album has an edition marker (differs from stripped version)
                stripped = strip_edition_suffix(album)
                has_edition = 0 if album == stripped else 1
                # Score: has_edition (prefer 1), then length (prefer longer), then alphabetical
                score = (has_edition, len(album), album)
                if score > best_score:
                    best_score = score
                    best_album = album

            selected_albums.append(best_album or album_files[0][0])

    # Now pick the most common selected album (with tie-break)
    c = collections.Counter(selected_albums)
    if not c:
        return ''
    # Deterministic tie-break: alphabetical ordering
    return sorted(c.items(), key=lambda x: (-x[1], x[0]))[0][0]


def same_path(path1, path2):
    """compare two paths for equality, respecting filesystem case sensitivity.
    on case-sensitive filesystems (Unix): exact match required.
    on case-insensitive filesystems (Windows, macOS default): case-insensitive comparison.
    """
    if not path1 or not path2:
        return bool(path1) == bool(path2)
    try:
        # Try to get the real path to normalize symlinks, etc.
        real1 = os.path.realpath(path1)
        real2 = os.path.realpath(path2)
        # On Windows, os.path.realpath preserves case but comparison is case-insensitive
        # We need to check the filesystem's case sensitivity
        if sys.platform.startswith('win'):
            # Windows: case-insensitive
            return os.path.normcase(real1) == os.path.normcase(real2)
        else:
            # Unix-like: check if filesystem is case-sensitive by testing
            # For simplicity, we'll assume most modern Unix filesystems are case-sensitive
            # but macOS default is case-insensitive. Let's be safe and check
            try:
                # Create a temporary file to test case sensitivity
                import tempfile
                with tempfile.NamedTemporaryFile() as tmp:
                    lower_path = tmp.name.lower()
                    upper_path = tmp.name.upper()
                    # If we can create both, filesystem is case-insensitive
                    try:
                        with open(lower_path, 'w') as f:
                            f.write('test')
                        with open(upper_path, 'w') as f:
                            f.write('test')
                        # If both succeeded, case-insensitive
                        import os
                        os.unlink(lower_path)
                        os.unlink(upper_path)
                        return os.path.normcase(real1) == os.path.normcase(real2)
                    except FileExistsError:
                        # Case-sensitive filesystem
                        return real1 == real2
                    except:
                        # Fallback to normcase
                        return os.path.normcase(real1) == os.path.normcase(real2)
            except:
                # Ultimate fallback
                return os.path.normcase(real1) == os.path.normcase(real2)
    except:
        # Fallback to simple comparison
        return path1 == path2


def scan_audio(root_path, subdirs=('albums', 'singles')):
    """walk audio files under root_path. subdirs names each subdir to scan
    (default albums+singles), or subdirs=None to walk root_path recursively
    as a whole (used by preimport over an unorganized drop)."""
    files = []
    roots = [os.path.join(root_path, s) for s in subdirs] if subdirs else [root_path]
    for root in roots:
        if not os.path.isdir(root):
            continue
        for dp, dirs, fns in os.walk(root):
            dirs[:] = [d for d in dirs if d != '__pycache__']
            for fn in fns:
                if not fn.lower().endswith(EXTENSIONS):
                    continue
                entry = read_tags(os.path.join(dp, fn))
                if entry is None:
                    continue
                if not entry['title']:
                    entry['title'] = os.path.splitext(fn)[0]
                if not entry['artist']:
                    entry['artist'] = entry['albumartist'] or 'Unknown Artist'
                files.append(entry)
    # Sort for deterministic ordering: by artist, album, track, title
    files.sort(key=lambda f: (
        f['artist'].lower(),
        f['album'].lower(),
        f['track'] if f['track'] else 0,
        f['title'].lower()
    ))
    return files


def safe_move(src, dst):
    """move src -> dst, creating parent dirs; rename on destination
    collisions. returns the path the file actually ended up at (dst, or the
    "(N)"-suffixed collision name) so callers - the organize journal, tag
    writes after a move - never have to guess."""
    # Handle case-only collisions on case-insensitive filesystems
    if same_path(src, dst) and not os.path.normpath(src) == os.path.normpath(dst):
        # Source and destination are the same file but with different case
        # On case-insensitive filesystem, we need to use a temporary intermediate
        temp_dst = dst + '.tmp.__case_fix__'
        shutil.move(src, temp_dst)
        shutil.move(temp_dst, dst)
        return dst

    # Normal move logic
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    if os.path.normpath(src) == os.path.normpath(dst):
        return dst
    if os.path.exists(dst):
        base, ext = os.path.splitext(dst)
        i = 2
        while os.path.exists(f"{base} ({i}){ext}"):
            i += 1
        dst = f"{base} ({i}){ext}"

    # Handle Windows MAX_PATH limitation (260 characters)
    if sys.platform.startswith('win') and len(dst) >= 260:
        # Try to truncate the filename to fit within MAX_PATH
        dirname = os.path.dirname(dst)
        basename = os.path.basename(dst)
        name, ext = os.path.splitext(basename)

        # Calculate how much we need to trim
        max_basename_len = 255 - len(dirname) - 1  # -1 for separator
        if len(basename) > max_basename_len and max_basename_len > len(ext) + 1:  # +1 for dot
            # Truncate the name part, keep extension
            max_name_len = max_basename_len - len(ext) - 1  # -1 for dot
            if max_name_len > 0:
                truncated_name = name[:max_name_len]
                basename = f"{truncated_name}{ext}"
                dst = os.path.join(dirname, basename)

    shutil.move(src, dst)
    return dst


def member_filename(track_num, artist, title, ext):
    """create standardized filename for album track member.
    format: "{track:02d} - {artist} - {title}{ext}" """
    from lib.text import render_credit
    track_str = f"{int(track_num) if track_num else 0:02d}"
    safe_artist = sanitize(render_credit(artist)) if artist else 'Unknown Artist'
    safe_title = sanitize(title) if title else 'Unknown Title'
    return f"{track_str} - {safe_artist} - {safe_title}{ext or ''}"


def single_filename(artist, title, ext):
    """create standardized filename for single.
    format: "{artist} - {title}{ext}" """
    from lib.text import render_credit
    safe_artist = sanitize(render_credit(artist)) if artist else 'Unknown Artist'
    safe_title = sanitize(title) if title else 'Unknown Title'
    return f"{safe_artist} - {safe_title}{ext or ''}"


def unique_name(existing_names, proposed_name):
    """generate a unique name by adding (2), (3), etc. suffixes if needed.
    existing_names: set of existing names (lowercase for case-insensitive comparison)
    proposed_name: the desired name
    returns: a name not in existing_names """
    if not proposed_name:
        proposed_name = "Untitled"

    # Check if proposed_name is already taken (case-insensitive)
    if proposed_name.lower() not in existing_names:
        return proposed_name

    # Try adding (2), (3), etc.
    base, ext = os.path.splitext(proposed_name)
    counter = 2
    while True:
        new_name = f"{base} ({counter}){ext}"
        if new_name.lower() not in existing_names:
            return new_name
        counter += 1