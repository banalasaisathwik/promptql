from dataclasses import dataclass
import re

from app.connectors.errors import (
    GitHubIncompleteResultError,
    GitHubInvalidResponseError,
)
from app.investigations import DiffLine, DiffLineKind


MAX_PATCH_CHARACTERS = 200_000
MAX_HUNKS_PER_FILE = 100
MAX_LINES_PER_HUNK = 500
MAX_LINE_CHARACTERS = 4096
HUNK_HEADER = re.compile(
    r"^@@ -(?P<old_start>\d+)(?:,(?P<old_count>\d+))? "
    r"\+(?P<new_start>\d+)(?:,(?P<new_count>\d+))? @@(?: .*)?$"
)


@dataclass(frozen=True)
class ParsedDiffHunk:
    old_start: int
    old_count: int
    new_start: int
    new_count: int
    lines: tuple[DiffLine, ...]


def parse_github_patch(patch: str) -> tuple[ParsedDiffHunk, ...]:
    if not patch or len(patch) > MAX_PATCH_CHARACTERS:
        if len(patch) > MAX_PATCH_CHARACTERS:
            raise GitHubIncompleteResultError()
        raise GitHubInvalidResponseError()

    parsed_hunks: list[ParsedDiffHunk] = []
    header: re.Match[str] | None = None
    lines: list[DiffLine] = []

    def finish_hunk() -> None:
        nonlocal header, lines
        if header is None:
            return
        old_count = _range_count(header, "old_count")
        new_count = _range_count(header, "new_count")
        old_consumed = sum(
            line.kind in {DiffLineKind.CONTEXT, DiffLineKind.DELETION}
            for line in lines
        )
        new_consumed = sum(
            line.kind in {DiffLineKind.CONTEXT, DiffLineKind.ADDITION}
            for line in lines
        )


        if old_consumed != old_count or new_consumed != new_count:
            raise GitHubIncompleteResultError()
        if not lines:
            raise GitHubInvalidResponseError()
        parsed_hunks.append(
            ParsedDiffHunk(
                old_start=int(header.group("old_start")),
                old_count=old_count,
                new_start=int(header.group("new_start")),
                new_count=new_count,
                lines=tuple(lines),
            )
        )
        header = None
        lines = []

    for raw_line in patch.splitlines():
        possible_header = HUNK_HEADER.fullmatch(raw_line)
        if possible_header is not None:
            finish_hunk()
            if len(parsed_hunks) >= MAX_HUNKS_PER_FILE:
                raise GitHubIncompleteResultError()
            header = possible_header
            continue
        if raw_line == r"\ No newline at end of file":
            if header is None:
                raise GitHubInvalidResponseError()
            continue
        if header is None or not raw_line or raw_line[0] not in " +-":
            raise GitHubInvalidResponseError()
        if len(lines) >= MAX_LINES_PER_HUNK or len(raw_line[1:]) > MAX_LINE_CHARACTERS:
            raise GitHubIncompleteResultError()
        line_kind = {
            " ": DiffLineKind.CONTEXT,
            "+": DiffLineKind.ADDITION,
            "-": DiffLineKind.DELETION,
        }[raw_line[0]]
        lines.append(DiffLine(kind=line_kind, text=raw_line[1:]))

    finish_hunk()
    if not parsed_hunks:
        raise GitHubInvalidResponseError()
    return tuple(parsed_hunks)


def _range_count(header: re.Match[str], group_name: str) -> int:
    raw_count = header.group(group_name)
    return 1 if raw_count is None else int(raw_count)
