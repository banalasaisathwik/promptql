pass

from dataclasses import dataclass
from enum import StrEnum

from app.connectors.models import ConnectorRequest


                                                                             
                                                                              
FIXTURE_REPOSITORY_OWNER = "acme"
FIXTURE_REPOSITORY_NAME = "analytics"


def _request(pr_number: int) -> ConnectorRequest:
    pass

    return ConnectorRequest(
        repository_owner=FIXTURE_REPOSITORY_OWNER,
        repository_name=FIXTURE_REPOSITORY_NAME,
        pr_number=pr_number,
    )


                                                                            
                                       
MERGE_READY_REQUEST = _request(1)
DRAFT_REQUEST = _request(2)
FAILED_CI_REQUEST = _request(3)
PENDING_CI_REQUEST = _request(4)
MISSING_APPROVAL_REQUEST = _request(5)
CHANGES_REQUESTED_REQUEST = _request(6)
MERGE_CONFLICT_REQUEST = _request(7)
JIRA_IN_PROGRESS_REQUEST = _request(8)


class FixtureScenarioId(StrEnum):
    pass

    MERGE_READY = "merge-ready"
    DRAFT = "draft"
    FAILED_CI = "failed-ci"
    PENDING_CI = "pending-ci"
    MISSING_APPROVAL = "missing-approval"
    CHANGES_REQUESTED = "changes-requested"
    MERGE_CONFLICT = "merge-conflict"
    JIRA_IN_PROGRESS = "jira-in-progress"


@dataclass(frozen=True)
class FixtureScenario:
    pass

    id: FixtureScenarioId
    label: str
    request: ConnectorRequest


                                                                                
                                                                      
FIXTURE_SCENARIOS = (
    FixtureScenario(FixtureScenarioId.MERGE_READY, "Merge ready", MERGE_READY_REQUEST),
    FixtureScenario(FixtureScenarioId.DRAFT, "Draft", DRAFT_REQUEST),
    FixtureScenario(FixtureScenarioId.FAILED_CI, "Failed CI", FAILED_CI_REQUEST),
    FixtureScenario(FixtureScenarioId.PENDING_CI, "Pending CI", PENDING_CI_REQUEST),
    FixtureScenario(
        FixtureScenarioId.MISSING_APPROVAL,
        "Missing approval",
        MISSING_APPROVAL_REQUEST,
    ),
    FixtureScenario(
        FixtureScenarioId.CHANGES_REQUESTED,
        "Changes requested",
        CHANGES_REQUESTED_REQUEST,
    ),
    FixtureScenario(
        FixtureScenarioId.MERGE_CONFLICT,
        "Merge conflict",
        MERGE_CONFLICT_REQUEST,
    ),
    FixtureScenario(
        FixtureScenarioId.JIRA_IN_PROGRESS,
        "Jira in progress",
        JIRA_IN_PROGRESS_REQUEST,
    ),
)
