"""organize/journal.py - write-ahead journal + undo. uses real files in a
tmp dir for moves and an in-memory dict as the tag store, so it needs
neither mediafile nor beets."""
import json
import os
import shutil

from organize.journal import Journal, journal_path, list_runs, undo_run


class FakeTags:
    """dict path -> {field: value}; write honors an optional skip rule so
    tests can simulate write_tag() declining a write."""

    def __init__(self, data, skip=None):
        self.data = data
        self.skip = skip or (lambda path, field, new, old: False)

    def read(self, path, field):
        d = self.data.get(path)
        return None if d is None else d.get(field, '')

    def write(self, path, **fields):
        for f, v in fields.items():
            if not self.skip(path, f, v, self.data[path].get(f, '')):
                self.data[path][f] = v

    def write_exact(self, path, **fields):
        for f, v in fields.items():
            self.data[path][f] = v


def _mk(tmp_path, rel, text='x'):
    p = tmp_path / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)
    return str(p)


def _journal(tmp_path, tags=None):
    tags = tags or FakeTags({})
    return Journal(str(tmp_path), 'test', move_fn=_plain_move,
                   read_fn=tags.read, write_fn=tags.write), tags


def _plain_move(src, dst):
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    shutil.move(src, dst)
    return dst


def _lines(tmp_path):
    with open(journal_path(str(tmp_path)), encoding='utf-8') as f:
        return [json.loads(l) for l in f if l.strip()]


def test_move_is_written_before_and_after(tmp_path):
    src = _mk(tmp_path, 'a/one.mp3')
    dst = str(tmp_path / 'b' / 'one.mp3')
    j, _ = _journal(tmp_path)
    with j:
        assert j.move(src, dst) == dst
    recs = [r for r in _lines(tmp_path) if r['t'] == 'move']
    assert [r['st'] for r in recs] == ['planned', 'done']
    assert os.path.exists(dst) and not os.path.exists(src)


def test_failed_move_recorded_and_raised(tmp_path):
    def boom(src, dst):
        raise OSError('disk on fire')
    j = Journal(str(tmp_path), 'test', move_fn=boom)
    try:
        with j:
            j.move('nope', 'nada')
    except OSError:
        pass
    else:
        raise AssertionError('should re-raise')
    st = [r['st'] for r in _lines(tmp_path) if r['t'] == 'move']
    assert st == ['planned', 'failed']
    assert _lines(tmp_path)[-1] == {'t': 'end', 'run': j.run_id, 'ok': False}


def test_move_returns_actual_destination(tmp_path):
    def renaming(src, dst):
        real = dst.replace('.mp3', ' (2).mp3')
        os.makedirs(os.path.dirname(real), exist_ok=True)
        shutil.move(src, real)
        return real
    src = _mk(tmp_path, 'a/one.mp3')
    j = Journal(str(tmp_path), 'test', move_fn=renaming)
    with j:
        final = j.move(src, str(tmp_path / 'b' / 'one.mp3'))
    assert final.endswith('one (2).mp3')
    done = [r for r in _lines(tmp_path) if r['t'] == 'move' and r['st'] == 'done'][0]
    assert done['dst'] == final


def test_tag_done_and_skipped(tmp_path):
    tags = FakeTags({'f1': {'album': 'Old'}, 'f2': {'album': '4x4 SCORPION'}},
                    skip=lambda p, f, new, old: p == 'f2')  # simulates Bug 7's decline
    j, _ = _journal(tmp_path, tags)
    with j:
        assert j.tag('f1', album='New') == 'done'
        assert j.tag('f2', album='4 X 4 Scorpion') == 'skipped'
        assert j.tag('missing', album='x') == 'failed'
    info = list_runs(str(tmp_path))[0]
    assert (info['tags'], info['skipped_tags'], info['failed']) == (1, 1, 1)


def test_undo_reverses_moves_and_tags_newest_first(tmp_path):
    a = _mk(tmp_path, 'in/a.mp3')
    b = str(tmp_path / 'out' / 'a.mp3')
    tags = FakeTags({b: {'albumartist': 'Old AA'}})
    j, _ = _journal(tmp_path, tags)
    # real flow: move, then tag the moved path
    with j:
        tags.data[a] = tags.data.pop(b)
        final = j.move(a, b)
        tags.data[final] = tags.data.pop(a)
        j.tag(final, albumartist='New AA')
    assert tags.data[b]['albumartist'] == 'New AA'

    # dry-run changes nothing
    undo_run(str(tmp_path), apply=False, write_fn=tags.write_exact)
    assert os.path.exists(b) and not os.path.exists(a)

    res = undo_run(str(tmp_path), apply=True, write_fn=tags.write_exact)
    assert res['reverted'] == 2 and res['blocked'] == 0
    assert tags.data[b]['albumartist'] == 'Old AA'
    assert os.path.exists(a) and not os.path.exists(b)
    # the run is now marked undone and is not picked again
    assert list_runs(str(tmp_path))[0]['undone'] is True
    assert undo_run(str(tmp_path), apply=True)['run'] is None


def test_undo_blocked_when_original_path_occupied(tmp_path):
    a = _mk(tmp_path, 'in/a.mp3', 'original')
    b = str(tmp_path / 'out' / 'a.mp3')
    j, _ = _journal(tmp_path)
    with j:
        j.move(a, b)
    _mk(tmp_path, 'in/a.mp3', 'someone else')   # occupy the original path
    res = undo_run(str(tmp_path), apply=True)
    assert res['blocked'] == 1 and res['reverted'] == 0
    assert open(b).read() == 'original'          # untouched


def test_in_flight_move_treated_as_done_when_dest_exists(tmp_path):
    a = _mk(tmp_path, 'in/a.mp3')
    b = str(tmp_path / 'out' / 'a.mp3')
    # simulate a crash after the move but before the 'done' record
    with open(journal_path(str(tmp_path)), 'w', encoding='utf-8') as f:
        f.write(json.dumps({'t': 'run', 'run': 'R1', 'label': 'x', 'ts': 't'}) + '\n')
        f.write(json.dumps({'t': 'move', 'run': 'R1', 'op': 1, 'st': 'planned',
                            'src': a, 'dst': b}) + '\n')
    _plain_move(a, b)
    res = undo_run(str(tmp_path), run_id='R1', apply=True)
    assert res['reverted'] == 1 and os.path.exists(a)


def test_torn_last_line_is_ignored(tmp_path):
    p = journal_path(str(tmp_path))
    with open(p, 'w', encoding='utf-8') as f:
        f.write(json.dumps({'t': 'run', 'run': 'R1', 'label': 'x', 'ts': 't'}) + '\n')
        f.write('{"t": "move", "run": "R1", "op"')   # killed mid-write
    assert [r['run'] for r in list_runs(str(tmp_path))] == ['R1']
