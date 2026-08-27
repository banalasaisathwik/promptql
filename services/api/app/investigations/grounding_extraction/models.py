from enum import StrEnum
from typing import Annotated

from pydantic import Field

from app.connectors.models import ContractModel, NonEmptyString


PullRequestNumber = Annotated[int, Field(strict=True, gt=0)]


class GroundingExtractionInput(ContractModel):
    description: NonEmptyString
    known_repository_owner: NonEmptyString | None = None
    known_repository_name: NonEmptyString | None = None
    known_incident_reference: NonEmptyString | None = None
    known_deployment_reference: NonEmptyString | None = None
    known_pull_request_number: PullRequestNumber | None = None


class GroundingExtractionOutput(ContractModel):
    repository_owner: NonEmptyString | None = None
    repository_name: NonEmptyString | None = None
    incident_reference: NonEmptyString | None = None
    deployment_reference: NonEmptyString | None = None
    pull_request_number: PullRequestNumber | None = None


class GroundingExtractionFailureCode(StrEnum):
    PROVIDER_FAILURE = "provider_failure"
    INVALID_RESPONSE = "invalid_response"
    EXTRACTION_SCHEMA_INVALID = "extraction_schema_invalid"
