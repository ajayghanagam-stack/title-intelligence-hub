"""Tests for TSA deterministic flag detection rules engine."""
import uuid

from app.micro_apps.title_search.services.flag_rules import (
    RULES_VERSION,
    VALID_FLAG_TYPES,
    VALID_SEVERITIES,
    SEVERITY_FLOOR,
    SEVERITY_CAP,
    LOW_CONFIDENCE_THRESHOLD,
    detect_unreleased_mortgages,
    detect_low_confidence,
    detect_all_flags,
    normalize_flags,
    _clamp_severity,
)


class MockDoc:
    """Lightweight ORM-like object for testing."""
    def __init__(self, **kw):
        for k, v in kw.items():
            setattr(self, k, v)


def test_rules_version_exists():
    """RULES_VERSION is a non-empty string."""
    assert isinstance(RULES_VERSION, str)
    assert len(RULES_VERSION) > 0


def test_valid_flag_types_is_frozenset():
    """VALID_FLAG_TYPES is a frozenset with expected types."""
    assert isinstance(VALID_FLAG_TYPES, frozenset)
    assert "unreleased_mortgage" in VALID_FLAG_TYPES
    assert "low_confidence" in VALID_FLAG_TYPES
    assert "chain_gap" in VALID_FLAG_TYPES


def test_severity_floor_applied():
    """chain_gap floor is 'high' — medium gets promoted."""
    result = _clamp_severity("chain_gap", "medium")
    assert result == "high"


def test_severity_floor_not_applied_when_already_higher():
    """chain_gap with critical stays critical (above floor)."""
    result = _clamp_severity("chain_gap", "critical")
    assert result == "critical"


def test_severity_cap_applied():
    """low_confidence cap is 'medium' — critical gets demoted."""
    result = _clamp_severity("low_confidence", "critical")
    assert result == "medium"


def test_severity_cap_not_applied_when_already_lower():
    """low_confidence with low stays low (below cap is fine)."""
    result = _clamp_severity("low_confidence", "low")
    assert result == "low"


def test_invalid_severity_defaults_to_medium():
    """Unknown severity string defaults to 'medium'."""
    result = _clamp_severity("chain_gap", "banana")
    # "banana" → "medium", then floor for chain_gap → "high"
    assert result == "high"


def test_detect_unreleased_mortgages_found():
    """Mortgage without satisfaction produces a flag."""
    docs = [
        MockDoc(id=uuid.uuid4(), doc_type="mortgage", recording_ref="MTG-001", confidence=0.9),
    ]
    flags = detect_unreleased_mortgages(docs)
    assert len(flags) == 1
    assert flags[0]["flag_type"] == "unreleased_mortgage"
    assert flags[0]["severity"] == "high"


def test_detect_unreleased_mortgages_satisfied():
    """Mortgage with matching satisfaction produces no flag."""
    docs = [
        MockDoc(id=uuid.uuid4(), doc_type="mortgage", recording_ref="MTG-001", confidence=0.9),
        MockDoc(id=uuid.uuid4(), doc_type="satisfaction", recording_ref="MTG-001", confidence=0.9),
    ]
    flags = detect_unreleased_mortgages(docs)
    assert len(flags) == 0


def test_detect_low_confidence():
    """Document below threshold produces a flag."""
    doc_id = uuid.uuid4()
    docs = [
        MockDoc(id=doc_id, doc_type="deed", recording_ref="D-001", confidence=0.50),
    ]
    flags = detect_low_confidence(docs)
    assert len(flags) == 1
    assert flags[0]["flag_type"] == "low_confidence"
    assert flags[0]["severity"] == "medium"
    assert flags[0]["document_id"] == doc_id


def test_detect_low_confidence_above_threshold():
    """Document above threshold produces no flag."""
    docs = [
        MockDoc(id=uuid.uuid4(), doc_type="deed", recording_ref="D-001", confidence=0.85),
    ]
    flags = detect_low_confidence(docs)
    assert len(flags) == 0


def test_detect_all_flags_runs_all_rules():
    """detect_all_flags combines unreleased mortgages and low confidence."""
    docs = [
        MockDoc(id=uuid.uuid4(), doc_type="mortgage", recording_ref="MTG-001", confidence=0.5),
        MockDoc(id=uuid.uuid4(), doc_type="deed", recording_ref="D-001", confidence=0.85),
    ]
    flags = detect_all_flags(docs)
    flag_types = {f["flag_type"] for f in flags}
    assert "unreleased_mortgage" in flag_types
    assert "low_confidence" in flag_types


def test_normalize_flags_rejects_invalid_type():
    """Flags with unknown flag_type are dropped."""
    flags = [{"flag_type": "bogus_type", "severity": "high", "title": "X", "description": "Y"}]
    result = normalize_flags(flags)
    assert len(result) == 0


def test_normalize_flags_deduplicates():
    """Two flags with same (flag_type, document_id) merge; higher severity wins."""
    doc_id = uuid.uuid4()
    flags = [
        {"flag_type": "unreleased_mortgage", "severity": "medium", "title": "A", "description": "A", "document_id": doc_id},
        {"flag_type": "unreleased_mortgage", "severity": "high", "title": "B", "description": "B", "document_id": doc_id},
    ]
    result = normalize_flags(flags)
    assert len(result) == 1
    # Floor for unreleased_mortgage is high, so both get clamped to high regardless
    assert result[0]["severity"] == "high"


def test_normalize_flags_deterministic_sort():
    """Flags are sorted by severity (critical first), then flag_type, then description."""
    flags = [
        {"flag_type": "low_confidence", "severity": "medium", "title": "LC", "description": "Z"},
        {"flag_type": "chain_gap", "severity": "high", "title": "CG", "description": "A"},
        {"flag_type": "unreleased_mortgage", "severity": "high", "title": "UM", "description": "B"},
    ]
    result = normalize_flags(flags)
    assert len(result) == 3
    # high severity items come before medium
    assert result[0]["severity"] == "high"
    assert result[1]["severity"] == "high"
    assert result[2]["severity"] == "medium"
    # Within same severity, sorted by flag_type
    assert result[0]["flag_type"] == "chain_gap"
    assert result[1]["flag_type"] == "unreleased_mortgage"


def test_detect_all_flags_deterministic():
    """Same inputs produce identical flag output every time."""
    docs = [
        MockDoc(id=uuid.uuid4(), doc_type="mortgage", recording_ref="MTG-001", confidence=0.5),
        MockDoc(id=uuid.uuid4(), doc_type="deed", recording_ref="D-001", confidence=0.60),
    ]
    flags1 = detect_all_flags(docs)
    flags2 = detect_all_flags(docs)
    assert flags1 == flags2


def test_detect_all_flags_works_with_dicts():
    """Flag detection works with dict inputs (not just ORM objects)."""
    docs = [
        {"id": uuid.uuid4(), "doc_type": "mortgage", "recording_ref": "MTG-001", "confidence": 0.5},
    ]
    flags = detect_all_flags(docs)
    flag_types = {f["flag_type"] for f in flags}
    assert "unreleased_mortgage" in flag_types
    assert "low_confidence" in flag_types
