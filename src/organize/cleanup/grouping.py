"""organize.cleanup.grouping - the forward-looking regroup pass: decide
where every file in <crate>/albums + <crate>/singles belongs.

  - group every audio file by its album tag (group_files)
  - >=2 files sharing an album -> one album folder, named
    <albumartist> - <album>; canonical albumartist per group is the
    dominant artist string across the group's files (lib.tags.
    canonical_albumartist)
  - exactly 1 file per album, or no album tag -> singleton
  - a 2-track "album" that canonical_albumartist() only resolved to
    'Various Artists' because the two members share zero artist tokens
    - and neither file's own albumartist tag actually says VA - is an
    unrelated same-titled-singles collision (is_unrelated_va_collision),
    not a real compilation, and gets filed as two singletons instead of
    merged. Fixes e.g. "Anysia Kym - Automatic" and "Spencer. -
    Automatic" colliding into one "Various Artists - Automatic" folder
    just because they share a title. See BUGFIX_PLAN.md's Bug 2.

this module only decides where things go (build_plan()'s returned move
lists); apply.py's run_cleanup() performs the moves/tag-writes and owns
the printed report. resplit.py is the separate, opt-in repair pass for
folders that were already wrongly merged before this module's
grouping-key fix landed - it recomputes from each file's raw 'artist'
tag rather than reusing anything here, since a wrongly-merged folder's
on-disk albumartist tag is exactly what this module's own tag-writes
would have set, so it can't be trusted as an input to a repair pass.
"""

import collections
import os

from lib.tags import canonical_albumartist, dominant_album, sanitize
from lib.text import normalize_album, normalize_key, split_artists


def _artist_tokens(f):
    """normalized artist-name tokens for one file, unioning artist +
    albumartist so a featured/collab credit on either field counts - same
    union lib.catalog.matcher._entry_artist_set() does for playlist
    matching."""
    tokens = set()
    for field in ('artist', 'albumartist'):
        for a in split_artists(f.get(field) or ''):
            tokens.add(normalize_key(a))
    return tokens


def _is_explicit_va(f):
    """True if this file's own albumartist tag already says Various
    Artists/VA outright - an intentional compilation signal we should
    trust, as opposed to canonical_albumartist() *falling back* to
    'Various Artists' only because a group's artists never agreed on
    anything."""
    return normalize_key(f.get('albumartist') or '') in ('variousartists', 'va')


def shares_artist_token(members):
    """True if at least two members of the group share a normalized
    artist token (artist/albumartist union). False means every member's
    artist set is completely disjoint from every other's - the "two
    unrelated singles that happen to share an album title" pattern Bug 2
    covers, not a genuine multi-artist album or compilation."""
    token_sets = [_artist_tokens(m) for m in members]
    for i in range(len(token_sets)):
        for j in range(i + 1, len(token_sets)):
            if token_sets[i] & token_sets[j]:
                return True
    return False


def is_unrelated_va_collision(members):
    """True when a group of files that ended up with a shared album key
    are actually two unrelated same-titled singles, not a genuine album
    or compilation — regardless of what canonical_albumartist() resolved
    to. The previous version only caught the case where
    canonical_albumartist() fell back to 'Various Artists', but a 2-track
    group with completely disjoint artist tokens can resolve to one of
    the two artists on a tie (50% threshold), skipping the check entirely.

    The real condition: exactly 2 tracks with completely disjoint
    normalized artist tokens (artist + albumartist union), and neither
    track's own albumartist tag explicitly says Various Artists/VA. This
    catches both the 'Various Artists' fallback case and the tie-break
    case (e.g. Diversa's "Ego Death" and The Internet's "Ego Death"
    landing in the same group — canonical_albumartist picks one artist,
    but the tracks are unrelated).

    Deliberately scoped to exactly two members. A 3+ track group with
    no full overlap is left to the existing ambiguous-VA flagging path
    instead of being auto-split — that's a genuinely murkier case (could
    be a real collab album with scattered features, could be an
    accidental collision) that hasn't been confirmed to be the same
    pattern. See BUGFIX_PLAN.md's Bug 2."""
    if len(members) != 2:
        return False
    if any(_is_explicit_va(m) for m in members):
        return False
    return not shares_artist_token(members)



def group_files(files):
    """group by normalised album identity (empty album -> its own
    single-element bucket so it stays a singleton). Uses
    lib.text.normalize_album() rather than plain normalize_key() so a
    track tagged "Album" and one tagged "Album (Deluxe)"/"Album (2009
    Remaster)" land in the same group instead of forking into two -
    canonical_albumartist()/dominant_album() then pick the folder
    name/tag from whichever raw string is more common across the merged
    group, same majority-vote behavior as any other tag disagreement (no
    new canonical string is invented here - see TODO.md's separate
    apply-time-cleanup item for that). returns {group_key: [file, ...]}
    preserving order."""
    groups = collections.OrderedDict()
    for i, f in enumerate(files):
        if f['album']:
            key = ('album', normalize_album(f['album']))
        else:
            key = ('single', i)  # unique per file - never merge missing-album files
        groups.setdefault(key, []).append(f)
    return groups


def build_plan(groups, crate):
    """decide a target path + tag fix for every file.
    returns (album_moves, singleton_moves, noop_count, tag_writes,
    album_tag_writes, va_groups, split_groups)."""
    albums_dir = os.path.join(crate, 'albums')
    singles_dir = os.path.join(crate, 'singles')

    album_moves = []      # (src, dst, new_albumartist)
    singleton_moves = []  # (src, dst)
    tag_writes = []       # (src, new_albumartist)
    album_tag_writes = [] # (src, new_album)
    va_groups = []        # (album, track_count, src_skewed_folders)
    split_groups = []     # (album, track_count) - Bug 2: false-VA collisions split apart
    noop = 0

    # de-dup track numbers within a group: prefer the tag's track, else sequence
    def track_label(idx_in_group, f):
        n = f['track'] or (idx_in_group + 1)
        return f"{int(n) if n else idx_in_group+1:02d}"

    for (kind, _), members in groups.items():
        if kind == 'single' or len(members) == 1:
            # singleton: <crate>/singles/<artist> - <title>.ext
            f = members[0]
            ext = os.path.splitext(f['path'])[1]
            dst = os.path.join(singles_dir,
                               f"{sanitize(f['artist'])} - {sanitize(f['title'])}{ext}")
            if os.path.normpath(dst) != os.path.normpath(f['path']):
                singleton_moves.append((f['path'], dst))
            else:
                noop += 1
            continue

        # album group
        aa = canonical_albumartist(members)
        album = dominant_album(members)

        # If the folder ends up as Various Artists, try to infer the real artist
        # from the raw artist tags; this prevents mis‑labeling a single‑artist
        # album as a compilation.
        if aa == 'Various Artists':
            artist_counts = {}
            for m in members:
                art = m.get('artist') or ''
                if art:
                    artist_counts[art] = artist_counts.get(art, 0) + 1
            if artist_counts:
                # override only if there is a clear majority
                top, top_n = max(artist_counts.items(), key=lambda kv: kv[1])
                total = sum(artist_counts.values())
                if top_n >= total * 0.5:
                    aa = top

        if is_unrelated_va_collision(members):
            # Bug 2: two different artists' singles that happen to share a
            # title collided into one "Various Artists" folder purely
            # because canonical_albumartist() found no majority between
            # them - that's not a compilation, it's two unrelated tracks.
            # File each one as its own singleton instead of merging them.
            split_groups.append((album or 'Unknown Album', len(members)))
            for f in members:
                ext = os.path.splitext(f['path'])[1]
                dst = os.path.join(singles_dir,
                                   f"{sanitize(f['artist'])} - {sanitize(f['title'])}{ext}")
                if os.path.normpath(dst) != os.path.normpath(f['path']):
                    singleton_moves.append((f['path'], dst))
                else:
                    noop += 1
            continue

        folder = sanitize(f"{aa} - {album}") or 'Unknown Album'

        # did we end up at "Various Artists"? flag for the summary
        src_folders = {os.path.basename(os.path.dirname(m['path'])) for m in members}
        if aa == 'Various Artists':
            va_groups.append((album or folder, len(members), sorted(src_folders)))

        # tag writes: enforce the canonical albumartist so future beets runs don't split
        for m in members:
            if normalize_key(m['albumartist'] or '') != normalize_key(aa):
                tag_writes.append((m['path'], aa))
        # album tag writes: enforce the dominant album string so all files in group agree
        for m in members:
            if normalize_key(m['album'] or '') != normalize_key(album):
                album_tag_writes.append((m['path'], album))

        seen_names = set()
        for idx, m in enumerate(members):
            ext = os.path.splitext(m['path'])[1]
            name = f"{track_label(idx, m)} - {sanitize(m['artist'])} - {sanitize(m['title'])}{ext}"
            # rare filename collision inside the album -> disambiguate
            base, sfx = os.path.splitext(name); c = 2
            while name.lower() in seen_names:
                name = f"{base} ({c}){sfx}"; c += 1
            seen_names.add(name.lower())
            dst = os.path.join(albums_dir, folder, name)
            if os.path.normpath(dst) != os.path.normpath(m['path']):
                album_moves.append((m['path'], dst, aa))
            else:
                noop += 1

    return album_moves, singleton_moves, noop, tag_writes, album_tag_writes, va_groups, split_groups


