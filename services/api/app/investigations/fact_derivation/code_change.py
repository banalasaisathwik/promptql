from app.investigations import (
    ChangedFileEvidenceContent,
    ChangedFileFact,
    ChangedFileMatchesFailureFileFact,
    ChangedHunkOverlapsFailureLineFact,
    DiffHunkEvidenceContent,
    Evidence,
    StackFrameEvidenceContent,
)
from app.investigations.fact_derivation._ids import fact_id, references
from app.investigations.path_normalization import normalized_path


def derive_code_failure_facts(
    evidence: tuple[Evidence, ...],
) -> tuple[
    ChangedFileFact | ChangedFileMatchesFailureFileFact | ChangedHunkOverlapsFailureLineFact,
    ...,
]:
    facts: list[
        ChangedFileFact | ChangedFileMatchesFailureFileFact | ChangedHunkOverlapsFailureLineFact
    ] = []
    changed_files = [item for item in evidence if isinstance(item.content, ChangedFileEvidenceContent)]
    hunks = [item for item in evidence if isinstance(item.content, DiffHunkEvidenceContent)]
    frames = [item for item in evidence if isinstance(item.content, StackFrameEvidenceContent)]


    for changed_file in changed_files:
        facts.append(
            ChangedFileFact(
                fact_id=fact_id("changed-file", changed_file),
                evidence_reference_ids=references(changed_file),
                path=changed_file.content.path,
                change_type=changed_file.content.change_type,
                pull_request_number=changed_file.content.pull_request_number,
            )
        )

    for frame in frames:
        if frame.content.file_path is None:
            continue
        failure_path = normalized_path(frame.content.file_path)
        for changed_file in changed_files:
            if normalized_path(changed_file.content.path) != failure_path:
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
                    or normalized_path(hunk.content.file_path) != failure_path
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
