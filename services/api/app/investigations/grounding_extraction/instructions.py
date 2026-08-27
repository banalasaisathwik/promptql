from app.investigations.grounding_extraction.models import GroundingExtractionInput


GROUNDING_EXTRACTION_PROMPT_ID = "grounding-extraction"
GROUNDING_EXTRACTION_PROMPT_VERSION = "v1.0.0"


GROUNDING_EXTRACTION_SYSTEM_INSTRUCTIONS = """You extract structured grounding references from a
plain-English incident description. Extract only repository_owner, repository_name,
incident_reference, deployment_reference, and pull_request_number. Copy each value
exactly as it appears in the text; never invent, guess, autocomplete, normalize, or
infer a value that is not explicitly present. If a field is not clearly and
unambiguously stated in the text, leave it null instead of guessing — a missing
field is always safer than a wrong one. Do not create authoritative facts,
hypotheses, root-cause claims, or an investigation question; extraction only
identifies where to look, never what happened. Return only the required structured
output as one top-level object with the five named fields."""


GROUNDING_EXTRACTION_KNOWN_FIELDS_SECTION = """

The following fields are already confirmed by the user and must not be
re-derived or contradicted; treat them as fixed context, not text to re-extract:
{known_fields_summary}"""


def build_grounding_extraction_system_instructions(
    extraction_input: GroundingExtractionInput,
) -> str:
    known_fields = {
        "repository_owner": extraction_input.known_repository_owner,
        "repository_name": extraction_input.known_repository_name,
        "incident_reference": extraction_input.known_incident_reference,
        "deployment_reference": extraction_input.known_deployment_reference,
        "pull_request_number": extraction_input.known_pull_request_number,
    }
    known_present = {
        name: value for name, value in known_fields.items() if value is not None
    }
    if not known_present:
        return GROUNDING_EXTRACTION_SYSTEM_INSTRUCTIONS
    summary = ", ".join(f"{name}={value!r}" for name, value in known_present.items())
    return GROUNDING_EXTRACTION_SYSTEM_INSTRUCTIONS + GROUNDING_EXTRACTION_KNOWN_FIELDS_SECTION.format(
        known_fields_summary=summary
    )
