pass

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, StringConstraints


RequiredString = Annotated[str, StringConstraints(min_length=1)]


class JiraResponseModel(BaseModel):
    pass

    model_config = ConfigDict(extra="ignore", strict=True)


class JiraStatusCategoryResponse(JiraResponseModel):
    id: int
    key: Literal["new", "indeterminate", "done"]
    name: RequiredString


class JiraStatusResponse(JiraResponseModel):
    id: RequiredString
    name: RequiredString
    statusCategory: JiraStatusCategoryResponse


class JiraAssigneeResponse(JiraResponseModel):
    accountId: RequiredString
    displayName: RequiredString


class JiraResolutionResponse(JiraResponseModel):
    id: RequiredString
    name: RequiredString


class JiraIssueFieldsResponse(JiraResponseModel):
    status: JiraStatusResponse
    assignee: JiraAssigneeResponse | None
    resolution: JiraResolutionResponse | None


class JiraIssueResponse(JiraResponseModel):
    id: RequiredString
    key: RequiredString
    fields: JiraIssueFieldsResponse
