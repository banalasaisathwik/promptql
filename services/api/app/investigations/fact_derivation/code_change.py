from app.investigations import (
    ChangedFileEvidenceContent,
    ChangedFileMatchesFailureFileFact,
    ChangedHunkOverlapsFailureLineFact,
    DiffHunkEvidenceContent,
    Evidence,
    StackFrameEvidenceContent,
)
from app.investigations.fact_derivation._ids import fact_id, references


def _normalized_path(path: str) -> str:
    # Normalize only separators and a harmless leading './'; fuzzy matching
    # would turn a plausible file name into an unsupported fact.
    return path.replace("\\", "/").removeprefix("./")


def derive_code_failure_facts(
    evidence: tuple[Evidence, ...],
) -> tuple[ChangedFileMatchesFailureFileFact | ChangedHunkOverlapsFailureLineFact, ...]:
    # A hunk is useful only when a patch exists and its new-file range contains
    # the observed failure line. A deletion range (new_count == 0) has no new line.
    facts: list[ChangedFileMatchesFailureFileFact | ChangedHunkOverlapsFailureLineFact] = []
    changed_files = [item for item in evidence if isinstance(item.content, ChangedFileEvidenceContent)]
    hunks = [item for item in evidence if isinstance(item.content, DiffHunkEvidenceContent)]
    frames = [item for item in evidence if isinstance(item.content, StackFrameEvidenceContent)]
    for frame in frames:
        if frame.content.file_path is None:
            continue
        failure_path = _normalized_path(frame.content.file_path)
        for changed_file in changed_files:
            if _normalized_path(changed_file.content.path) != failure_path:
                continue
            facts.append(
                ChangedFileMatchesFailureFileFact(
                    fact_id=fact_id("changed-file-matches-failure-file", changed_file, frame),
                    evidence_reference_ids=references(changed_file, frame),
                    file_path=frame.content.file_path,
                )
            )
            if frame.content.line_number is None or not changed_file.content.patch_available:
                continue
            for hunk in hunks:
                if (
                    hunk.content.pull_request_number != changed_file.content.pull_request_number
                    or _normalized_path(hunk.content.file_path) != failure_path
                    or hunk.content.new_count == 0
                ):
                    continue
                first_line = hunk.content.new_start
                last_line = first_line + hunk.content.new_count - 1
                if not first_line <= frame.content.line_number <= last_line:
                    continue
                facts.append(
                    ChangedHunkOverlapsFailureLineFact(
                        fact_id=fact_id("changed-hunk-overlaps-failure-line", changed_file, hunk, frame),
                        evidence_reference_ids=references(changed_file, hunk, frame),
                        file_path=frame.content.file_path,
                        line_number=frame.content.line_number,
                    )
                )
    return tuple(facts)
