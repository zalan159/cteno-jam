import copy

import pytest

from cteno_jam import patches as P
from cteno_jam import theory


def song():
    return {
        "key": "E major", "tempo": 120, "duration": 40.0, "meter": 4,
        "chords": [
            {"id": "c001", "start": 0.0, "end": 4.0, "chord": "E", "beats": 8},
            {"id": "c002", "start": 4.0, "end": 8.0, "chord": "Abm", "beats": 8},
            {"id": "c003", "start": 8.0, "end": 8.5, "chord": "F", "beats": 1},
            {"id": "c004", "start": 8.5, "end": 12.0, "chord": "A", "beats": 7},
            {"id": "c005", "start": 12.0, "end": 16.0, "chord": "B7", "beats": 8},
            {"id": "c006", "start": 16.0, "end": 20.0, "chord": "Dbm", "beats": 8},
            {"id": "c007", "start": 20.0, "end": 40.0, "chord": "E", "beats": 40},
        ],
        "lyrics": {"source": "user", "lines": [
            {"id": "l001", "start": 1.0, "end": 6.0, "text": "hello world again and again",
             "chars": [{"c": w, "t": 1.0 + i, "end": 1.9 + i} for i, w in enumerate(["hello ", "world ", "again ", "and ", "again "])]},
            {"id": "l002", "start": 7.0, "end": 9.0, "text": "bye",
             "chars": [{"c": "bye", "t": 7.0, "end": 8.0}]},
        ]},
        "sections": [],
    }


# ------------------------------------------------------------- theory
def test_spelling_in_key():
    e = theory.parse_key("E major")
    assert theory.spell("Abm", e) == "G#m"
    assert theory.spell("Dbm7", e) == "C#m7"
    assert theory.spell("B/D#", e) == "B/D#"
    f = theory.parse_key("F major")
    assert theory.spell("A#", f) == "Bb"
    assert theory.spell("C7", f) == "C7"
    assert theory.parse_key("C# minor").name == "C# minor"


def test_simplify_and_capo():
    assert theory.simplify("F#m7") == "F#m"
    assert theory.simplify("Bsus4") == "B"
    assert theory.simplify("B/D#") == "B"
    assert theory.is_simplification("F#m7", "F#m")
    assert not theory.is_simplification("F#m7", "Gm")
    fret, share = theory.best_capo([("F", 4), ("Bb", 4), ("C", 4), ("Dm", 4)])
    assert fret == 3 and share >= 0.75  # F major -> capo 3, D shapes (D G A Bm)
    assert theory.best_capo([("G", 1), ("C", 1), ("D", 1), ("Em", 1)])[0] == 0


def test_transpose_follows_new_key():
    e = theory.parse_key("E major")
    assert theory.transpose("G#m", 1, e) == "Am"
    assert theory.transpose("E", 1, e) == "F"
    assert theory.transpose("B7", 1, e) == "C7"


# ------------------------------------------------------------- valid patches
def test_respell_and_merge_apply():
    a = song()
    a2 = P.apply(a, {"op": "respell_chord", "id": "c002", "chord": "G#m", "reason": "E major has G#"})
    assert [c["chord"] for c in a2["chords"]][:2] == ["E", "G#m"]
    assert a["chords"][1]["chord"] == "Abm", "apply must not mutate its input"
    a3 = P.apply(a2, {"op": "merge_chord", "id": "c003", "into": "next", "reason": "1-beat blip"})
    ids = [c["id"] for c in a3["chords"]]
    assert "c003" not in ids
    nxt = next(c for c in a3["chords"] if c["id"] == "c004")
    assert nxt["start"] == 8.0 and nxt["beats"] == 8


def test_sections_capo_rhythm_lines():
    a = song()
    a = P.apply(a, {"op": "add_section", "start": 0, "end": 12, "label": "verse", "reason": "first lines"})
    a = P.apply(a, {"op": "add_section", "start": 12, "end": 20, "label": "chorus", "reason": "B7 lift"})
    assert [s["label"] for s in a["sections"]] == ["verse", "chorus"]
    a = P.apply(a, {"op": "set_capo", "fret": 4, "shapes": "C", "reason": "C shapes sound in E"})
    assert a["capo"] == {"fret": 4, "shapes": "C"}
    a = P.apply(a, {"op": "simplify_chord", "id": "c005", "chord": "B", "reason": "triad for kids"})
    assert a["simplified"]["c005"] == "B"
    a = P.apply(a, {"op": "set_rhythm", "kind": "strum", "pattern": "D-DU-UDU", "reason": "pop 4/4"})
    a = P.apply(a, {"op": "split_line", "line": "l001", "at": 2, "reason": "two phrases"})
    texts = [l["text"] for l in a["lyrics"]["lines"]]
    assert texts[:2] == ["hello world", "again and again"]
    a = P.apply(a, {"op": "merge_lines", "line": "l001", "reason": "rejoin"})
    assert a["lyrics"]["lines"][0]["text"] == "hello world again and again"


# ------------------------------------------------------------- invalid patches are rejected
BAD = [
    ({"op": "rewrite_song", "reason": "x"}, "unknown or not allowed op"),
    ({"op": "respell_chord", "id": "c002", "chord": "G#m"}, "reason"),
    ({"op": "respell_chord", "id": "c002", "chord": "Am", "reason": "x"}, "must sound the same"),
    ({"op": "respell_chord", "id": "c999", "chord": "G#m", "reason": "x"}, "no chord segment"),
    ({"op": "replace_chord", "id": "c002", "chord": "H7", "reason": "x"}, "not a chord symbol"),
    ({"op": "merge_chord", "id": "c002", "into": "prev", "reason": "x"}, "only blips"),
    ({"op": "merge_chord", "id": "c001", "into": "prev", "reason": "x"}, "no prev neighbour"),
    ({"op": "add_section", "start": 30, "end": 20, "label": "verse", "reason": "x"}, "not inside the song"),
    ({"op": "add_section", "start": 0, "end": 10, "label": "hook", "reason": "x"}, "label must be one of"),
    ({"op": "set_capo", "fret": 12, "reason": "x"}, "fret must be"),
    ({"op": "set_capo", "fret": 2, "shapes": "C", "reason": "x"}, "do not sound in"),
    ({"op": "simplify_chord", "id": "c005", "chord": "Am", "reason": "x"}, "not a simplification"),
    ({"op": "set_rhythm", "kind": "strum", "pattern": "<script>", "reason": "x"}, "may only use"),
    ({"op": "split_line", "line": "l002", "at": 1, "reason": "x"}, "'at' must be"),
    ({"op": "merge_lines", "line": "l002", "reason": "x"}, "last line"),
    ({"op": "delete_chord", "id": "c001", "reason": "x"}, "not allowed"),  # humans only
    ({"op": "set_key", "key": "H major", "reason": "x"}, "not a key"),
    ("not a dict", "must be an object"),
    ({"op": "respell_chord", "id": "c002", "chord": "G#m", "reason": "x" * 400}, "longer than"),
]


@pytest.mark.parametrize("patch,err", BAD)
def test_invalid_patch_rejected(patch, err):
    a = song()
    before = copy.deepcopy(a)
    with pytest.raises(P.PatchError) as e:
        P.apply(a, patch, "ai")
    assert err in str(e.value)
    assert a == before


def test_overlapping_section_rejected():
    a = P.apply(song(), {"op": "add_section", "start": 0, "end": 12, "label": "verse", "reason": "v"})
    with pytest.raises(P.PatchError, match="overlaps"):
        P.apply(a, {"op": "add_section", "start": 10, "end": 20, "label": "chorus", "reason": "c"})


def test_user_may_delete_and_insert():
    a = P.apply(song(), {"op": "delete_chord", "id": "c003", "reason": "x"}, "user")
    assert "c003" not in [c["id"] for c in a["chords"]]
    a = P.apply(a, {"op": "insert_chord", "start": 30.0, "chord": "A", "reason": "x"}, "user")
    assert any(c["chord"] == "A" and c["start"] == 30.0 for c in a["chords"])


# ------------------------------------------------------------- revisions: batch, undo, conflicts
def test_add_patches_keeps_valid_rejects_invalid():
    base = song()
    a, revs, rej = P.add_patches(base, [], [
        {"op": "respell_chord", "id": "c002", "chord": "G#m", "reason": "key"},
        {"op": "respell_chord", "id": "c002", "chord": "Am", "reason": "bad"},
        {"op": "merge_chord", "id": "c003", "into": "next", "reason": "blip"},
        {"op": "respell_chord", "id": "c006", "chord": "C#m", "reason": "key"},
    ], "ai", "b1")
    assert [r["patch"]["op"] for r in revs] == ["respell_chord", "merge_chord", "respell_chord"]
    assert len(rej) == 1 and "must sound the same" in rej[0]["error"]
    assert all(r["reason"] for r in revs) and all(r["batch"] == "b1" for r in revs)
    assert [c["chord"] for c in a["chords"]] == ["E", "G#m", "A", "B7", "C#m", "E"]


def test_undo_one_and_undo_all():
    base = song()
    a, revs, _ = P.add_patches(base, [], [
        {"op": "respell_chord", "id": "c002", "chord": "G#m", "reason": "key"},
        {"op": "respell_chord", "id": "c006", "chord": "C#m", "reason": "key"},
    ], "ai")
    a, revs = P.set_status(base, revs, [revs[0]["id"]], "reverted")
    assert [c["chord"] for c in a["chords"]][1] == "Abm"
    assert a["chords"][5]["chord"] == "C#m"
    a, revs = P.set_status(base, revs, [r["id"] for r in revs], "reverted")
    assert a["chords"] == base["chords"]
    a, revs = P.set_status(base, revs, [revs[0]["id"]], "applied")
    assert a["chords"][1]["chord"] == "G#m"


def test_conflict_when_dependency_reverted():
    base = song()
    # human edit depends on the AI merge (it edits c004, which the merge extended) — fine;
    # an edit of a chord that a reverted patch would re-introduce must not break replay
    a, revs, _ = P.add_patches(base, [], [{"op": "merge_chord", "id": "c003", "into": "next", "reason": "blip"}], "ai")
    a, revs, _ = P.add_patches(base, revs, [{"op": "insert_chord", "start": 8.2, "chord": "B", "reason": "x"}], "user")
    # revert the merge: the user's insert (inside old c003) still applies, so nothing is lost
    a, revs = P.set_status(base, revs, [revs[0]["id"]], "reverted")
    assert revs[1]["status"] == "applied"
    # a patch whose target vanished becomes "conflict", not an exception
    revs.append({"id": "r099", "source": "ai", "patch": {"op": "respell_chord", "id": "c777", "chord": "E", "reason": "x"},
                 "status": "applied", "reason": "x"})
    a, revs = P.replay(base, revs)
    assert revs[-1]["status"] == "conflict" and "no chord segment" in revs[-1]["error"]
