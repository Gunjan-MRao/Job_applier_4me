"""End-to-end render guard for the Setup page's extracted-profile block.

This is the exact block that crashed the Streamlit page with
"SyntaxError: f-string expression part cannot include a backslash" on Python
< 3.12 (the "Name:" / "Email:" / "Experience:" lines used an em-dash fallback
inside the f-string braces). Parsing the file is not enough proof -- these tests
actually RUN app.py via Streamlit's AppTest and assert the profile block renders
without raising, on both the populated and the missing-value (EM_DASH fallback)
paths.
"""
import pytest

from streamlit.testing.v1 import AppTest

APP = "app.py"

FULL_PROFILE = {
    "candidate_name": "Ada Lovelace",
    "email": "ada@example.com",
    "years_of_experience_hint": "graduate",
    "likely_roles": ["Supply Chain Analyst"],
    "skills": ["logistics", "sap"],
    "education": ["BSc Maths"],
    "preview": "sample resume text",
}
MISSING_PROFILE = {"candidate_name": None, "email": None, "skills": []}


def _run_setup_with_profile(profile):
    at = AppTest.from_file(APP, default_timeout=30)
    at.session_state["page"] = "setup"
    at.session_state["resume_profile"] = profile
    at.session_state["resume_filename"] = "cv.pdf"
    at.run()
    return at


def test_profile_block_renders_with_full_values():
    at = _run_setup_with_profile(FULL_PROFILE)
    assert not at.exception, f"app raised while rendering profile: {at.exception}"
    text = "\n".join([m.value for m in at.markdown] + [i.value for i in at.info])
    assert "Name:" in text and "Ada Lovelace" in text


def test_profile_block_renders_with_missing_values_using_em_dash():
    at = _run_setup_with_profile(MISSING_PROFILE)
    assert not at.exception, f"app raised on the missing-value fallback path: {at.exception}"
    text = "\n".join(m.value for m in at.markdown)
    # The EM_DASH fallback must render where a value is absent.
    assert "Name:" in text
    assert "—" in text, "em-dash fallback (EM_DASH) should appear for missing values"
