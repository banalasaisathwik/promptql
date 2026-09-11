from datetime import UTC, datetime

from app.evals.fix_proposal.models import (
    FixProposalEvalCase,
    FixProposalEvalCategory,
    FixProposalEvalDataset,
)
from app.investigations import (
    CommitChangedFileEvidenceContent,
    CommitDiffHunkEvidenceContent,
    DiffLine,
    DiffLineKind,
    Evidence,
    EvidenceKind,
    EvidenceProvenance,
    EvidenceSource,
    FileChangeType,
    StackFrameEvidenceContent,
)


_FIXTURE_TIME = datetime(2026, 9, 11, 12, 0, tzinfo=UTC)
_REPOSITORY_OWNER = "octo-org"
_REPOSITORY_NAME = "analytics"


def _commit_scoped_evidence(
    *,
    case_id: str,
    file_path: str,
    function_name: str,
    body_lines: tuple[str, ...],
    new_start: int,
    failure_line_number: int,
    error_category: str,
    commit_sha: str,
) -> tuple[Evidence, ...]:
    changed_file = Evidence(
        evidence_id=f"github:commit:{case_id}:file",
        source=EvidenceSource.GITHUB,
        kind=EvidenceKind.COMMIT_CHANGED_FILE,
        provenance=EvidenceProvenance(
            source_reference=f"github:commit:{case_id}:file",
            retrieved_at=_FIXTURE_TIME,
        ),
        content=CommitChangedFileEvidenceContent(
            repository_owner=_REPOSITORY_OWNER,
            repository_name=_REPOSITORY_NAME,
            commit_sha=commit_sha,
            path=file_path,
            change_type=FileChangeType.MODIFIED,
            additions=len(body_lines),
            deletions=1,
            changes=len(body_lines) + 1,
            patch_available=True,
        ),
    )
    hunk = Evidence(
        evidence_id=f"github:commit:{case_id}:hunk",
        source=EvidenceSource.GITHUB,
        kind=EvidenceKind.COMMIT_DIFF_HUNK,
        provenance=EvidenceProvenance(
            source_reference=f"github:commit:{case_id}:hunk",
            retrieved_at=_FIXTURE_TIME,
        ),
        content=CommitDiffHunkEvidenceContent(
            repository_owner=_REPOSITORY_OWNER,
            repository_name=_REPOSITORY_NAME,
            commit_sha=commit_sha,
            file_path=file_path,
            old_start=new_start,
            old_count=1,
            new_start=new_start,
            new_count=len(body_lines),
            lines=(
                DiffLine(kind=DiffLineKind.CONTEXT, text=body_lines[0]),
                *(
                    DiffLine(kind=DiffLineKind.ADDITION, text=line)
                    for line in body_lines[1:]
                ),
            ),
        ),
    )
    stack_frame = Evidence(
        evidence_id=f"incident:{case_id}:frame",
        source=EvidenceSource.INCIDENT,
        kind=EvidenceKind.STACK_FRAME,
        provenance=EvidenceProvenance(
            source_reference=f"incident:{case_id}:frame",
            retrieved_at=_FIXTURE_TIME,
        ),
        content=StackFrameEvidenceContent(
            file_path=file_path,
            function_name=function_name,
            line_number=failure_line_number,
            error_category=error_category,
        ),
    )
    return (changed_file, hunk, stack_frame)


def _case_a_key_error() -> FixProposalEvalCase:
    file_path = "app/inventory.py"
    body_lines = (
        "def get_remaining_stock(items, stock):",
        "    remaining = stock[0]",
        "    return remaining",
    )
    return FixProposalEvalCase(
        case_id="fix-eval-a-key-error",
        category=FixProposalEvalCategory.KEY_ERROR,
        evidence=_commit_scoped_evidence(
            case_id="fix-eval-a",
            file_path=file_path,
            function_name="get_remaining_stock",
            body_lines=body_lines,
            new_start=10,
            failure_line_number=11,
            error_category="KeyError",
            commit_sha="a" * 40,
        ),
        hypothesis_subject=file_path,
        expected_file_path=file_path,
        expect_fix_available=True,
        grounding_keywords=("keyerror", "key", "index", "missing"),
        buggy_line_substring="    remaining = stock[0]",
        fixed_line_substring='    remaining = stock.get(items[0], 0)',
    )


def _case_b_none_dereference() -> FixProposalEvalCase:
    file_path = "app/users.py"
    body_lines = (
        "def get_user_email(user_id):",
        "    user = lookup_user(user_id)",
        "    return user.email",
    )
    return FixProposalEvalCase(
        case_id="fix-eval-b-none-dereference",
        category=FixProposalEvalCategory.NONE_DEREFERENCE,
        evidence=_commit_scoped_evidence(
            case_id="fix-eval-b",
            file_path=file_path,
            function_name="get_user_email",
            body_lines=body_lines,
            new_start=5,
            failure_line_number=7,
            error_category="AttributeError",
            commit_sha="b" * 40,
        ),
        hypothesis_subject=file_path,
        expected_file_path=file_path,
        expect_fix_available=True,
        grounding_keywords=("none", "attributeerror", "null", "nonetype"),
        buggy_line_substring="    return user.email",
        fixed_line_substring="    return user.email if user is not None else None",
    )


def _case_c_input_boundary() -> FixProposalEvalCase:
    file_path = "app/orders.py"
    body_lines = (
        "def parse_quantity(payload):",
        '    quantity = int(payload["quantity"])',
        "    return quantity",
    )
    return FixProposalEvalCase(
        case_id="fix-eval-c-input-boundary",
        category=FixProposalEvalCategory.INPUT_BOUNDARY,
        evidence=_commit_scoped_evidence(
            case_id="fix-eval-c",
            file_path=file_path,
            function_name="parse_quantity",
            body_lines=body_lines,
            new_start=20,
            failure_line_number=21,
            error_category="ValueError",
            commit_sha="c" * 40,
        ),
        hypothesis_subject=file_path,
        expected_file_path=file_path,
        expect_fix_available=True,
        grounding_keywords=("valueerror", "invalid", "quantity", "input", "missing"),
        buggy_line_substring='    quantity = int(payload["quantity"])',
        fixed_line_substring=(
            '    raw_quantity = payload.get("quantity")\n'
            "    if raw_quantity is None:\n"
            '        raise ValueError("quantity is required")\n'
            "    quantity = int(raw_quantity)"
        ),
    )


def _case_d_configuration_mismatch() -> FixProposalEvalCase:
    file_path = "app/config.py"
    body_lines = (
        "def load_payment_gateway():",
        '    gateway_url = os.environ["PAYMENT_GATEWAY_URL"]',
        "    return connect(gateway_url)",
    )
    return FixProposalEvalCase(
        case_id="fix-eval-d-configuration-mismatch",
        category=FixProposalEvalCategory.CONFIGURATION_MISMATCH,
        evidence=_commit_scoped_evidence(
            case_id="fix-eval-d",
            file_path=file_path,
            function_name="load_payment_gateway",
            body_lines=body_lines,
            new_start=8,
            failure_line_number=9,
            error_category="KeyError",
            commit_sha="d" * 40,
        ),
        hypothesis_subject=file_path,
        expected_file_path=file_path,
        expect_fix_available=True,
        grounding_keywords=(
            "environ",
            "configuration",
            "payment_gateway_url",
            "deployment",
            "missing",
            "keyerror",
        ),
        buggy_line_substring='    gateway_url = os.environ["PAYMENT_GATEWAY_URL"]',
        fixed_line_substring=(
            '    gateway_url = os.environ.get("PAYMENT_GATEWAY_URL")\n'
            "    if gateway_url is None:\n"
            '        raise RuntimeError("PAYMENT_GATEWAY_URL is not configured '
            'for this deployment")'
        ),
    )


def _case_e_insufficient_context() -> FixProposalEvalCase:
    file_path = "app/notifications.py"
    body_lines = (
        "def send_receipt_email(order_id):",
        "    message = build_receipt_message(order_id)",
        "    smtp_client.send(message)",
    )
    return FixProposalEvalCase(
        case_id="fix-eval-e-insufficient-context",
        category=FixProposalEvalCategory.INSUFFICIENT_CONTEXT,
        evidence=_commit_scoped_evidence(
            case_id="fix-eval-e",
            file_path=file_path,
            function_name="send_receipt_email",
            body_lines=body_lines,
            new_start=30,
            failure_line_number=32,
            error_category="TimeoutError",
            commit_sha="e" * 40,
        ),
        hypothesis_subject=file_path,
        expected_file_path=file_path,
        expect_fix_available=False,
        grounding_keywords=("timeout", "transient", "network"),
        buggy_line_substring=None,
        fixed_line_substring=None,
    )


def build_fix_proposal_eval_dataset() -> FixProposalEvalDataset:
    return FixProposalEvalDataset(
        dataset_id="v1-fix-proposal-eval",
        dataset_version="2026-09-11.1",
        cases=(
            _case_a_key_error(),
            _case_b_none_dereference(),
            _case_c_input_boundary(),
            _case_d_configuration_mismatch(),
            _case_e_insufficient_context(),
        ),
    )
