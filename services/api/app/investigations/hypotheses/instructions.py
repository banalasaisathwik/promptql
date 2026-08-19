"""Versioned instructions for constrained hypothesis generation."""


HYPOTHESIS_PROMPT_ID = "investigation-hypothesis-generation"
HYPOTHESIS_PROMPT_VERSION = "v2.17.1"
HYPOTHESIS_SYSTEM_INSTRUCTIONS = """Generate at most three candidate hypotheses from the supplied Facts.

Hypotheses are uncertain causal interpretations, never authoritative Facts.
Use only supplied Fact IDs. Do not invent Facts, claim certainty, use numeric
confidence, or return a free-form final answer. Choose only the supported
generic hypothesis kinds. If the Facts cannot support a causal candidate,
return an empty candidates list. Return only the typed schema."""
