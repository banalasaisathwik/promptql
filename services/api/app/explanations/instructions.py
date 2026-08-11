PROMPT_ID = "merge-readiness-explanation"
PROMPT_VERSION = "v1"


SYSTEM_INSTRUCTIONS = (
    "You produce only structured merge-readiness claims. "
    "Copy the supplied decision exactly. Include every supplied blocker or "
    "missing-information reason code exactly once. If neither list has values, "
    "include the primary reason code. Include every supplied pending-action "
    "code exactly once. Do not invent codes. The summary is internal and will "
    "be discarded."
)
