"""Unified diffs between two configurations, redacted.

The diff is computed on the stored (complete) texts and only then redacted line by line:
a changed secret still shows as a removed and an added line, both with the marker, while
neither value is shown. Line numbers in hunk headers refer to the redacted texts (what
the viewer shows; certificate payloads are collapsed there).
"""

import difflib
from dataclasses import dataclass

from netops.configmgmt.redact import redact_lines


@dataclass(frozen=True)
class RedactedDiff:
    text: str
    added: int
    removed: int


def redacted_diff(
    old: str, new: str, *, from_label: str, to_label: str, context: int = 3
) -> RedactedDiff:
    old_raw, new_raw = old.splitlines(), new.splitlines()
    old_shown, new_shown = redact_lines(old), redact_lines(new)

    def numbering(shown: list[str | None]) -> list[int]:
        """1-based line number in the redacted text at each raw position."""
        numbers, count = [], 0
        for line in shown:
            if line is not None:
                count += 1
            numbers.append(max(count, 1))
        return numbers

    old_numbers, new_numbers = numbering(old_shown), numbering(new_shown)
    out = [f"--- {from_label}", f"+++ {to_label}"]
    added = removed = 0
    matcher = difflib.SequenceMatcher(a=old_raw, b=new_raw, autojunk=False)
    for group in matcher.get_grouped_opcodes(context):
        body: list[str] = []
        old_count = new_count = 0
        for tag, i1, i2, j1, j2 in group:
            if tag == "equal":
                for line in old_shown[i1:i2]:
                    if line is not None:
                        body.append(f" {line}")
                        old_count += 1
                        new_count += 1
                continue
            for line in old_shown[i1:i2]:
                if line is not None:
                    body.append(f"-{line}")
                    old_count += 1
                    removed += 1
            for line in new_shown[j1:j2]:
                if line is not None:
                    body.append(f"+{line}")
                    new_count += 1
                    added += 1
        if not any(line[0] in "+-" for line in body):
            continue  # only collapsed certificate lines changed... shown as nothing
        first = group[0]
        old_start = old_numbers[first[1]] if first[1] < len(old_numbers) else len(old_shown)
        new_start = new_numbers[first[3]] if first[3] < len(new_numbers) else len(new_shown)
        out.append(f"@@ -{old_start},{old_count} +{new_start},{new_count} @@")
        out.extend(body)
    text = "\n".join(out) + "\n" if len(out) > 2 else ""
    return RedactedDiff(text=text, added=added, removed=removed)
