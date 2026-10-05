"""V8 (BUGFIX_PLAN.md): find artist tags the old normalize_artists plugin
probably mangled ("Daft Punk" -> "Da feat. Punk"). READ-ONLY: it only reads
the catalog sidecar (.playlist_index.jsonl) - no tags are touched.

    uv run python scripts/v8_plugin_damage.py [path/to/.playlist_index.jsonl]

default sidecar: PLAYLISTS_PATH/exports/.playlist_index.jsonl.

an artist string is SUSPECT when it looks like "<=4 chars + ' feat. ' + rest"
or ends in ' feat.'. it is CONFIRMED when putting the swallowed marker back
("ft", "f.", "feat") yields a string that also exists as an artist elsewhere
in the catalog (e.g. a spotdl-downloaded "Daft Punk" next to the beets-made
"Da feat. Punk"). confirmed rows are near-certain damage; suspects need an eye.
"""
import collections
import json
import os
import re
import sys

SUSPECT_RE = re.compile(r'^(?P<p>\S{1,4}) feat\.(?: (?P<q>.+))?$', re.IGNORECASE)
MARKERS = ('ft', 'f.', 'feat', 'ft.', 'feat.')


def default_sidecar():
    base = os.environ.get('PLAYLISTS_PATH')
    if not base:
        sys.exit('pass the sidecar path, or set PLAYLISTS_PATH')
    return os.path.join(base, 'exports', '.playlist_index.jsonl')


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else default_sidecar()
    counts = collections.Counter()
    with open(path, encoding='utf-8') as f:
        for line in f:
            if not line.strip():
                continue
            e = json.loads(line)
            for field in ('artist', 'albumartist'):
                v = (e.get(field) or '').strip()
                if v:
                    counts[v] += 1
    known = {k.lower() for k in counts}
    confirmed, suspects = [], []
    for name, n in counts.items():
        m = SUSPECT_RE.match(name)
        if not m:
            continue
        p, q = m.group('p'), m.group('q') or ''
        guess = None
        for mk in MARKERS:
            for cand in (f"{p}{mk} {q}".strip(), f"{p}{mk}{q}".strip()):
                if cand.lower() in known and cand.lower() != name.lower():
                    guess = cand
                    break
            if guess:
                break
        (confirmed if guess else suspects).append((name, n, guess))
    print(f"{len(counts)} distinct artist strings scanned in {path}\n")
    print(f"CONFIRMED mangled ({len(confirmed)}):")
    for name, n, guess in sorted(confirmed):
        print(f"  {n:>4}x  {name!r}  ->  probably {guess!r}")
    print(f"\nSUSPECT, review by eye ({len(suspects)}):")
    for name, n, _ in sorted(suspects):
        print(f"  {n:>4}x  {name!r}")


if __name__ == '__main__':
    main()