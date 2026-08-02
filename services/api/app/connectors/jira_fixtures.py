pass

from types import MappingProxyType

from app.connectors.fixture_catalog import JIRA_IN_PROGRESS_REQUEST
from app.connectors.github_fixtures import GITHUB_FIXTURES
from app.connectors.models import (
    BlockerState,
    JiraAssignee,
    JiraIssue,
    JiraIssueStatus,
)


_DONE_JIRA_ASSIGNEE = JiraAssignee(
    account_id="jira-user-1",
    display_name="Avery Engineer",
)


                                                                            
                                                                                 
                                                                          
_jira_fixtures = {
    request: JiraIssue(
        issue_key=github_fixture.linked_jira_key,
        status=JiraIssueStatus.DONE,
        blocker_state=BlockerState.NOT_BLOCKED,
        assignee=_DONE_JIRA_ASSIGNEE,
    )
    for request, github_fixture in GITHUB_FIXTURES.items()
    if github_fixture.linked_jira_key is not None
}


                                                                               
                             
_jira_fixtures[JIRA_IN_PROGRESS_REQUEST] = JiraIssue(
    issue_key="ENG-108",
    status=JiraIssueStatus.IN_PROGRESS,
    blocker_state=BlockerState.NOT_BLOCKED,
    assignee=JiraAssignee(
        account_id="jira-user-2",
        display_name="Riley Developer",
    ),
)


                                                                       
JIRA_FIXTURES = MappingProxyType(_jira_fixtures)
