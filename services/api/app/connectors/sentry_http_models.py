from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints


RequiredString = Annotated[str, StringConstraints(min_length=1)]


class SentryResponseModel(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True)


class SentryProjectResponse(SentryResponseModel):
    id: RequiredString
    slug: RequiredString


class SentryIssueResponse(SentryResponseModel):
    id: RequiredString
    shortId: RequiredString
    status: Literal["unresolved", "resolved", "ignored"]
    firstSeen: RequiredString
    lastSeen: RequiredString
    project: SentryProjectResponse


class SentryStackFrameResponse(SentryResponseModel):
    filename: RequiredString | None = None
    function: RequiredString | None = None


    lineNo: Annotated[int, Field(gt=0)] | None = None


class SentryStacktraceResponse(SentryResponseModel):
    frames: list[SentryStackFrameResponse] = []


class SentryExceptionValueResponse(SentryResponseModel):
    type: RequiredString | None = None
    stacktrace: SentryStacktraceResponse | None = None


class SentryExceptionEntryDataResponse(SentryResponseModel):
    values: list[SentryExceptionValueResponse] = []


class SentryEventEntryResponse(SentryResponseModel):
    model_config = ConfigDict(extra="ignore", strict=False)

    type: RequiredString
    data: dict


class SentryEventResponse(SentryResponseModel):
    eventID: RequiredString
    entries: list[SentryEventEntryResponse] = []


class SentryCommitResponse(SentryResponseModel):
    id: RequiredString


class SentryReleaseProjectResponse(SentryResponseModel):
    slug: RequiredString


class SentryReleaseResponse(SentryResponseModel):
    version: RequiredString
    dateCreated: RequiredString
    dateReleased: RequiredString | None = None
    lastCommit: SentryCommitResponse | None = None
    projects: list[SentryReleaseProjectResponse] = []


class SentryDeployResponse(SentryResponseModel):
    id: RequiredString
    environment: RequiredString
    dateFinished: RequiredString | None = None


class SentryStatsBucketValueResponse(SentryResponseModel):
    count: Annotated[int, Field(ge=0)]


class SentryEventsStatsResponse(SentryResponseModel):
    model_config = ConfigDict(extra="ignore", strict=False)

    data: list[tuple[int, list[SentryStatsBucketValueResponse]]]
