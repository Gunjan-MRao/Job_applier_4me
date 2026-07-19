"""Tests for authoritative GOV.UK sponsor verification in scoring.

Covers the trust-tier separation the UI relies on:
  * a company on the real register  -> "verified"      (green, trustworthy)
  * a company NOT on the register but whose JD text mentions sponsorship
                                     -> "mentioned"     (yellow, unverified)
  * an explicit "no sponsorship" JD  -> "none"          (never over-promise)
  * fuzzy company-name variations still match the register entry.
"""
from backend.pipeline import scoring
from backend.services.sponsor_register import SponsorRegister

# Real-shaped register rows (Organisation Name column, like the GOV.UK CSV).
SAMPLE_CSV = (
    "Organisation Name,Town/City,County,Type & Rating,Route\n"
    "Ferrero,Greenford,Greater London,A (Premium),Skilled Worker\n"
    "Amazon UK Services Ltd,London,Greater London,A (Premium),Skilled Worker\n"
    "Tesco PLC,Welwyn Garden City,Hertfordshire,A (Premium),Skilled Worker\n"
)


def _register(csv_text: str = SAMPLE_CSV) -> SponsorRegister:
    reg = SponsorRegister.__new__(SponsorRegister)
    reg._csv_url = None
    reg._names = set()
    reg._loaded_at = 0.0
    reg._db_session = None
    reg._parse_csv(csv_text)
    return reg


def test_company_on_register_is_verified():
    reg = _register()
    job = {"company": "Ferrero", "description": "Great logistics role."}
    assert scoring.sponsorship_tier(job, reg.verify) == scoring.SPONSOR_VERIFIED


def test_fuzzy_name_variation_still_verified():
    reg = _register()
    # Listing name differs from the register entry by legal/geographic suffixes.
    for name in ("Ferrero UK Ltd", "Amazon", "Tesco Stores Limited"):
        job = {"company": name, "description": "role"}
        assert scoring.sponsorship_tier(job, reg.verify) == scoring.SPONSOR_VERIFIED, name


def test_unregistered_company_with_jd_mention_is_only_mentioned():
    reg = _register()
    job = {
        "company": "Totally Made Up Startup",
        "description": "We offer visa sponsorship for skilled worker candidates.",
    }
    tier = scoring.sponsorship_tier(job, reg.verify)
    assert tier == scoring.SPONSOR_MENTIONED
    assert tier != scoring.SPONSOR_VERIFIED  # must never be conflated


def test_explicit_no_sponsorship_wins_even_if_registered():
    reg = _register()
    job = {
        "company": "Ferrero",
        "description": "You must already have the right to work in the UK; no sponsorship.",
    }
    assert scoring.sponsorship_tier(job, reg.verify) == scoring.SPONSOR_NONE


def test_no_verifier_never_yields_verified():
    job = {"company": "Ferrero", "description": "skilled worker visa available"}
    # Without a register verifier, the strongest label possible is "mentioned".
    assert scoring.sponsorship_tier(job, None) == scoring.SPONSOR_MENTIONED


def test_verify_does_not_false_positive_on_short_token():
    reg = _register()
    # "IT" normalises to a 2-char token — must NOT match any register entry.
    assert reg.verify("IT") is False
    assert reg.verify("Some Unlisted Co") is False
