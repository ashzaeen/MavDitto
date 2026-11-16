"""Word-level diffing: what actually changed inside a passage.

Marks the words that were added or removed between two versions of the same
passage, so a reviewer reading two blocks side by side is not left spotting
differences by eye.

A deterministic fact-extraction pass (numbers, dates, fees, percentages) used
to live here too. It was removed: it only ever read bare figures, so it fired
on numbers that had migrated just fine and said nothing about the far more
common case of prose that changed substance without touching a digit. The
passages it flagged are exactly the ambiguous band this module's docstring
still hands to the LLM judge -- that is the real answer, not a numeric regex.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from difflib import SequenceMatcher

# Split on whitespace but keep it, so a rebuilt string is byte-identical to the
# original and highlighting never silently reflows a passage.
_TOKENS = re.compile(r"(\s+)")


@dataclass(frozen=True)
class Segment:
    """One run of text, labelled by what happened to it."""

    kind: str      # "equal" | "delete" | "insert"
    text: str


# --------------------------------------------------------------------------
# word diff
# --------------------------------------------------------------------------

def _tokenize(text: str) -> list[str]:
    return [t for t in _TOKENS.split(text or "") if t != ""]


def word_diff(old: str, new: str) -> tuple[list[Segment], list[Segment]]:
    """Return (old_segments, new_segments).

    The old side carries `equal` and `delete` runs, the new side `equal` and
    `insert`. Rebuilding either side's text from its segments reproduces the
    input exactly, so a highlighted passage reads as the passage.
    """
    old_tokens, new_tokens = _tokenize(old), _tokenize(new)
    # Compare case-insensitively: a migration that recapitalizes a heading has
    # not changed what the page says.
    matcher = SequenceMatcher(
        None, [t.lower() for t in old_tokens], [t.lower() for t in new_tokens])

    old_out: list[Segment] = []
    new_out: list[Segment] = []

    def push(target: list[Segment], kind: str, text: str) -> None:
        if not text:
            return
        if target and target[-1].kind == kind:
            target[-1] = Segment(kind, target[-1].text + text)
        else:
            target.append(Segment(kind, text))

    for op, i1, i2, j1, j2 in matcher.get_opcodes():
        old_text = "".join(old_tokens[i1:i2])
        new_text = "".join(new_tokens[j1:j2])
        if op == "equal":
            push(old_out, "equal", old_text)
            push(new_out, "equal", new_text)
        elif op == "delete":
            push(old_out, "delete", old_text)
        elif op == "insert":
            push(new_out, "insert", new_text)
        else:                                   # replace
            push(old_out, "delete", old_text)
            push(new_out, "insert", new_text)

    return old_out, new_out


def change_ratio(old: str, new: str) -> float:
    """Share of the old passage's words that did not survive verbatim."""
    old_segments, _ = word_diff(old, new)
    deleted = sum(len(s.text.split()) for s in old_segments if s.kind == "delete")
    total = len((old or "").split())
    return deleted / total if total else 0.0


# --------------------------------------------------------------------------
# item-level diff, for lists and tables
# --------------------------------------------------------------------------

# Below this, two items are not one item reworded -- they are different items,
# and pairing them would hide one drop plus one addition as a "change".
ITEM_REWORD_FLOOR = 0.4


@dataclass(frozen=True)
class ItemDiff:
    """One list bullet or table row, labelled by what happened to it."""

    text: str
    kind: str      # "kept" | "changed" | "dropped" | "added"


def diff_items(old_items: list[str],
               new_items: list[str]) -> tuple[list[ItemDiff], list[ItemDiff]]:
    """Align two ordered lists of items -- bullets, or table rows -- and say
    what happened to each one.

    A list or a table is matched as a whole passage (see embed.chunk_page), so
    a list that only dropped its third bullet would otherwise show as one
    vague "reworded" block. This aligns items by whole-string similarity, the
    same way `diff_structural.align_headings` aligns headings, so the review
    screen can shade the one bullet that changed instead of the whole list.
    """
    old_keys = [" ".join((i or "").lower().split()) for i in old_items]
    new_keys = [" ".join((i or "").lower().split()) for i in new_items]
    matcher = SequenceMatcher(None, old_keys, new_keys)

    old_out: list[ItemDiff] = []
    new_out: list[ItemDiff] = []

    for op, i1, i2, j1, j2 in matcher.get_opcodes():
        if op == "equal":
            old_out += [ItemDiff(old_items[i], "kept") for i in range(i1, i2)]
            new_out += [ItemDiff(new_items[j], "kept") for j in range(j1, j2)]
            continue
        if op == "delete":
            old_out += [ItemDiff(old_items[i], "dropped") for i in range(i1, i2)]
            continue
        if op == "insert":
            new_out += [ItemDiff(new_items[j], "added") for j in range(j1, j2)]
            continue

        # replace: pair what can be paired by similarity, report the rest as
        # a drop plus an addition rather than guessing a pairing that isn't
        # there.
        remaining_new = list(range(j1, j2))
        for i in range(i1, i2):
            best_j, best_r = None, 0.0
            for j in remaining_new:
                r = SequenceMatcher(None, old_keys[i], new_keys[j]).ratio()
                if r > best_r:
                    best_j, best_r = j, r
            if best_j is not None and best_r >= ITEM_REWORD_FLOOR:
                remaining_new.remove(best_j)
                old_out.append(ItemDiff(old_items[i], "changed"))
                new_out.append(ItemDiff(new_items[best_j], "changed"))
            else:
                old_out.append(ItemDiff(old_items[i], "dropped"))
        new_out += [ItemDiff(new_items[j], "added") for j in remaining_new]

    return old_out, new_out
