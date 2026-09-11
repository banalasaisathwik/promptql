HYPOTHESIS_PROMPT_ID = "investigation-hypothesis-generation"
HYPOTHESIS_PROMPT_VERSION = "v2.17.3"
HYPOTHESIS_SYSTEM_INSTRUCTIONS = """Generate at most three candidate hypotheses from the supplied Facts.

Hypotheses are uncertain causal interpretations, never authoritative Facts.
Use only supplied Fact IDs. Set subject to the exact "path" or "file_path"
string of one of the supporting Facts, copied character-for-character --
never a shortened, basename-only, or otherwise reconstructed form of it.
supporting_fact_ids must include every supplied Fact needed to fully
establish the claim on its own -- for a code-change hypothesis this means
both the Fact that a file changed and the separate Fact that the same file
matches the observed failure location, whenever both are supplied; omitting
either one, even when a similar Fact is present, causes rejection. Do not
invent Facts, claim certainty, use numeric confidence, or return a free-form
final answer. Choose only the supported generic hypothesis kinds. If the
Facts cannot support a causal candidate, return an empty candidates list.
Return only the typed schema."""
