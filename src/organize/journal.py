"""organize.journal - write-ahead move/tag journal + undo (BUGFIX_PLAN.md
Phase 0).

every mutating step of an `--apply` run (a file move, a tag write) is
appended to <crate>/.organize_journal.jsonl BEFORE it happens and marked
done/failed after, with the old and new value. that gives:

  - a real undo (`organize undo`): reverse a run's completed ops newest-first
  - resumable/diagnosable interrupted runs: an op that is `planned` with no
    matching `done` was in flight when the process died
  - an honest record of what write_tag() actually did: ops where the tag was
    unchanged afterwards are recorded as `skipped` (this is how Bug 7's
    "normalize_key says equal, so nothing was written" shows up)

deliberately thin: lib.tags.safe_move()/write_tag() stay dumb; the journal
wraps them in the apply layer. dry-runs never touch the journal.

record shapes (one JSON object per line):
  {"t":"run",  "run":ID, "label":"cleanup", "ts":...}
  {"t":"move", "run":ID, "op":N, "st":"planned"|"done"|"failed", "src":..., "dst":..., ["error":...]}
  {"t":"tag",  "run":ID, "op":N, "st":"planned"|"done"|"skipped"|"failed", "path":..., "field":..., "old":..., "new":...}
  {"t":"end",  "run":ID, "ok":bool}
  {"t":"undone","run":ID, "of":ORIGINAL_RUN_ID}
"""

import json
import os
import time
import uuid

JOURNAL_NAME = '.organize_journal.jsonl'


def journal_path(crate):
    return os.path.join(crate, JOURNAL_NAME)


# --- default backends (lazy imports: this module imports without mediafile) --

def _read_field(path, field):
    from lib.tags import read_tags
    t = read_tags(path)
    return None if t is None else t.get(field)


def _write_field_checked(path, **fields):
    """the normal write path - lib.tags.write_tag(), whose skip-if-equal
    rule is whatever it currently is (Bug 7 changes it in Phase 1)."""
    from lib.tags import write_tag
    write_tag(path, **fields)


def _write_field_exact(path, **fields):
    """exact-string write used only by undo, so a case-only restore isn't
    swallowed by write_tag()'s comparison."""
    from mediafile import MediaFile
    m = MediaFile(path)
    for k, v in fields.items():
        setattr(m, k, v)
    m.save()


def _default_move(src, dst):
    from lib.tags import safe_move
    return safe_move(src, dst)


class Journal:
    """context manager; use one per apply run.

        with Journal(crate, 'cleanup') as j:
            final = j.move(src, dst)       # returns the path actually used
            j.tag(final, albumartist='X')  # -> 'done' | 'skipped' | 'failed'
    """

    def __init__(self, crate, label, move_fn=None, read_fn=None, write_fn=None):
        self.crate = crate
        self.label = label
        self.path = journal_path(crate)
        self.run_id = time.strftime('%Y%m%dT%H%M%S') + '-' + uuid.uuid4().hex[:6]
        self._move = move_fn or _default_move
        self._read = read_fn or _read_field
        self._write = write_fn or _write_field_checked
        self._fh = None
        self._op = 0

    # -- lifecycle
    def __enter__(self):
        os.makedirs(self.crate, exist_ok=True)
        self._fh = open(self.path, 'a', encoding='utf-8')
        self._emit({'t': 'run', 'run': self.run_id, 'label': self.label,
                    'ts': time.strftime('%Y-%m-%dT%H:%M:%S')})
        return self

    def __exit__(self, exc_type, exc, tb):
        self._emit({'t': 'end', 'run': self.run_id, 'ok': exc_type is None})
        self._fh.close()
        self._fh = None
        return False  # never swallow

    def _emit(self, rec):
        self._fh.write(json.dumps(rec, ensure_ascii=False) + '\n')
        self._fh.flush()
        os.fsync(self._fh.fileno())

    def _next(self):
        self._op += 1
        return self._op

    # -- operations
    def move(self, src, dst):
        """journal + perform a move. returns the final path (safe_move may
        rename on collision). re-raises on failure after recording it."""
        op = self._next()
        base = {'t': 'move', 'run': self.run_id, 'op': op}
        self._emit({**base, 'st': 'planned', 'src': src, 'dst': dst})
        try:
            final = self._move(src, dst) or dst
        except Exception as e:
            self._emit({**base, 'st': 'failed', 'src': src, 'dst': dst, 'error': str(e)})
            raise
        self._emit({**base, 'st': 'done', 'src': src, 'dst': final})
        return final

    def tag(self, path, **fields):
        """journal + perform tag write(s), one record per field. returns the
        status of the last field ('done' | 'skipped' | 'failed')."""
        status = 'failed'
        for field, new in fields.items():
            op = self._next()
            base = {'t': 'tag', 'run': self.run_id, 'op': op,
                    'path': path, 'field': field}
            old = self._read(path, field)
            if old is None:
                self._emit({**base, 'st': 'failed', 'old': None, 'new': new,
                            'error': 'unreadable'})
                status = 'failed'
                continue
            self._emit({**base, 'st': 'planned', 'old': old, 'new': new})
            try:
                self._write(path, **{field: new})
            except Exception as e:
                self._emit({**base, 'st': 'failed', 'old': old, 'new': new, 'error': str(e)})
                status = 'failed'
                continue
            after = self._read(path, field)
            if after == new and after != old:
                status = 'done'
            elif after == old:
                status = 'skipped'   # write_tag() declined (equal under its rule) or no-op
            else:
                status = 'done'      # something else landed (e.g. normalised by mediafile)
            self._emit({**base, 'st': status, 'old': old, 'new': after})
        return status


# --- reading the journal back ------------------------------------------------

def _read_records(crate):
    path = journal_path(crate)
    if not os.path.exists(path):
        return []
    recs = []
    with open(path, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                recs.append(json.loads(line))
            except json.JSONDecodeError:
                continue  # a torn final line from a killed process
    return recs


def list_runs(crate):
    """-> [{'run','label','ts','moves','tags','skipped_tags','failed','ended','ok','undone'}], oldest first."""
    runs = {}
    order = []
    for r in _read_records(crate):
        rid = r.get('run')
        if r['t'] == 'run':
            _handle_run_record(runs, order, r, rid)
        elif r['t'] == 'undone':
            _handle_undone_record(runs, r)
        elif rid in runs:
            _handle_existing_run_record(runs, r, rid)
    return [runs[i] for i in order]


def _handle_run_record(runs, order, record, run_id):
    """Handle a 'run' type record by initializing a new run entry."""
    runs[run_id] = {
        'run': run_id,
        'label': record.get('label'),
        'ts': record.get('ts'),
        'moves': 0,
        'tags': 0,
        'skipped_tags': 0,
        'failed': 0,
        'ended': False,
        'ok': None,
        'undone': False
    }
    order.append(run_id)


def _handle_undone_record(runs, record):
    """Handle an 'undone' type record by marking the original run as undone."""
    original_run_id = record.get('of')
    if original_run_id in runs:
        runs[original_run_id]['undone'] = True


def _handle_existing_run_record(runs, record, run_id):
    """Handle move/tag/end records for an existing run."""
    info = runs[run_id]
    if record['t'] == 'move':
        _handle_move_record(info, record)
    elif record['t'] == 'tag':
        _handle_tag_record(info, record)
    elif record['t'] == 'end':
        _handle_end_record(info, record)


def _handle_move_record(info, record):
    """Handle a move record by updating move/failed counts."""
    if record['st'] == 'done':
        info['moves'] += 1
    elif record['st'] == 'failed':
        info['failed'] += 1


def _handle_tag_record(info, record):
    """Handle a tag record by updating tag/skipped/failed counts."""
    if record['st'] == 'done':
        info['tags'] += 1
    elif record['st'] == 'skipped':
        info['skipped_tags'] += 1
    elif record['st'] == 'failed':
        info['failed'] += 1


def _handle_end_record(info, record):
    """Handle an end record by updating ended status and ok flag."""
    info['ended'] = True
    info['ok'] = record.get('ok')


def _run_ops(crate, run_id):
    """ops for one run, in journal order, with in-flight (planned, never
    resolved) ops flagged."""
    ops = {}
    seq = []
    for r in _read_records(crate):
        if r.get('run') != run_id or r['t'] not in ('move', 'tag'):
            continue
        key = r['op']
        if key not in ops:
            seq.append(key)
        ops[key] = r  # later record for the same op wins
    return [ops[k] for k in seq]


def _same_file(a, b):
    try:
        return os.path.samefile(a, b)
    except OSError:
        return False


def _move_back(cur, orig):
    """move cur -> orig without renaming on collision. returns (ok, msg)."""
    if not os.path.exists(cur):
        return False, 'missing'
    if os.path.exists(orig):
        if _same_file(cur, orig):
            # case-only rename on a case-insensitive fs: two-step
            tmp = orig + '.undo-' + uuid.uuid4().hex[:6]
            os.replace(cur, tmp)
            os.replace(tmp, orig)
            return True, 'case-only'
        return False, 'blocked (original path is occupied)'
    os.makedirs(os.path.dirname(orig), exist_ok=True)
    os.replace(cur, orig)
    try:
        os.rmdir(os.path.dirname(cur))   # tidy the folder the move created, if now empty
    except OSError:
        pass
    return True, 'moved'


def undo_run(crate, run_id=None, apply=False, write_fn=None):
    """reverse one run's completed operations, newest first. dry-run unless
    apply=True. run_id defaults to the most recent run that hasn't been
    undone. returns a summary dict. in-flight moves (planned, never
    resolved) are treated as done when the destination exists and the
    source doesn't."""
    run_id = _get_run_id(crate, run_id)
    if run_id is None:
        return {'run': None, 'reverted': 0, 'blocked': 0}

    ops = _get_valid_operations(crate, run_id)
    if not ops:
        return {'run': run_id, 'reverted': 0, 'blocked': 0}

    _print_undo_header(run_id, apply)
    todo = _build_todo_list(ops)
    reverted, blocked = _process_todo_list(todo, apply, write_fn or _write_field_exact)
    _print_undo_summary(reverted, blocked, apply, crate, run_id)

    return {'run': run_id, 'reverted': reverted, 'blocked': blocked}


def _get_run_id(crate, run_id):
    """Get the run ID to process, defaulting to the most recent un-undone run."""
    runs = [r for r in list_runs(crate) if not r['undone']]
    if run_id is None:
        if not runs:
            print('nothing to undo - no un-undone runs in the journal.')
            return None
        run_id = runs[-1]['run']
    return run_id


def _get_valid_operations(crate, run_id):
    """Get operations for the specified run ID, or return empty list if none."""
    ops = _run_ops(crate, run_id)
    if not ops:
        print(f'no operations recorded for run {run_id}.')
        return []
    return ops


def _print_undo_header(run_id, apply):
    """Print the undo header information."""
    print(f"run   : {run_id}")
    print(f"mode  : {'apply (reverting)' if apply else 'dry run (nothing changes)'}")


def _build_todo_list(ops):
    """Build the list of operations to revert from the raw operations."""
    todo = []
    for op in ops:
        if op['t'] == 'move':
            src, dst = op['src'], op['dst']
            if op['st'] == 'failed' or os.path.abspath(src) == os.path.abspath(dst):
                continue  # failed, or safe_move() no-op'd an identical path
            if op['st'] == 'planned' and not (os.path.exists(dst) and not os.path.exists(src)):
                continue  # never actually happened
            todo.append(op)
        elif op['t'] == 'tag' and op['st'] == 'done':
            todo.append(op)
    return todo


def _process_todo_list(todo, apply, write_fn):
    """Process the todo list of operations to revert."""
    reverted = blocked = 0
    for op in reversed(todo):
        if op['t'] == 'move':
            label = f"move  {op['dst']}  ->  {op['src']}"
            if not apply:
                print(f"  would revert {label}")
                reverted += 1
                continue
            ok, msg = _move_back(op['dst'], op['src'])
        else:
            label = f"tag   {op['path']}  {op['field']}: {op['new']!r} -> {op['old']!r}"
            if not apply:
                print(f"  would revert {label}")
                reverted += 1
                continue
            try:
                write_fn(op['path'], **{op['field']: op['old']})
                ok, msg = True, 'restored'
            except Exception as e:
                ok, msg = False, str(e)
        if ok:
            reverted += 1
        else:
            blocked += 1
            print(f"  SKIPPED ({msg}): {label}")
    return reverted, blocked


def _print_undo_summary(reverted, blocked, apply, crate, run_id):
    """Print the undo summary information."""
    if apply:
        with open(journal_path(crate), 'a', encoding='utf-8') as f:
            f.write(json.dumps({'t': 'undone', 'run': 'undo-' + uuid.uuid4().hex[:6],
                                'of': run_id}, ensure_ascii=False) + '\n')
        print(f"\nreverted {reverted} operation(s), skipped {blocked}.")
        print("note: beets.db / the catalog index are stale until rebuilt "
              "(`organize cleanup --rebuild-db`, then a playlists reindex).")
    else:
        print(f"\ndry run - {reverted} operation(s) would be reverted. re-run with --apply.")

