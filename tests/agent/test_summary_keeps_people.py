"""The compaction summary prompt asks for every person, open commitment and decision (Athena, Oct 21 2026)."""
from agent.context_compressor import ContextCompressor, _SECTION_INSTRUCTIONS


def test_both_summary_forms_ask_for_people_commitments_and_who_decided():
    for has_user_turn in (True, False):
        text = ContextCompressor._summary_template_sections(_SECTION_INSTRUCTIONS[has_user_turn], 2000, "")
        section = text.split("## People & Commitments", 1)[1].split("\n## ", 1)[0]
        assert "by name" in section and "who owes it" in section and "due date and time" in section
        assert "who made it" in section
