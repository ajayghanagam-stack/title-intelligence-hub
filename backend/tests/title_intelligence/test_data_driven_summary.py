"""Tests for the data-driven executive summary generator."""

import pytest
from unittest.mock import MagicMock


def _mock_flag(
    flag_type: str = "unresolved_lien",
    severity: str = "high",
    title: str = "Test flag",
    status: str = "open",
) -> MagicMock:
    """Create a mock Flag object."""
    f = MagicMock()
    f.flag_type = flag_type
    f.severity = severity
    f.title = title
    f.status = status
    return f


def _mock_extraction(
    extraction_type: str = "property",
    label: str = "Property Address",
    value: dict | str = "123 Main St",
) -> MagicMock:
    """Create a mock Extraction object."""
    e = MagicMock()
    e.extraction_type = extraction_type
    e.label = label
    e.value = value
    return e


class TestGenerateDataDrivenSummary:
    """Tests for generate_data_driven_summary()."""

    def test_ready_no_flags(self):
        from app.micro_apps.title_intelligence.services.report_service import generate_data_driven_summary

        summary = generate_data_driven_summary(
            pack_name="Test Pack",
            extractions=[],
            flags=[],
            readiness_score=95,
        )

        lines = summary.strip().split("\n")
        assert all(line.startswith("- ") for line in lines)
        assert "ready to close" in lines[0].lower()
        assert "95/100" in lines[0]
        assert any("cleared for closing" in line.lower() or "resolved" in line.lower() for line in lines)

    def test_at_risk_with_high_flags(self):
        from app.micro_apps.title_intelligence.services.report_service import generate_data_driven_summary

        flags = [
            _mock_flag(flag_type="unresolved_lien", severity="high", title="Open Mortgage Lien"),
            _mock_flag(flag_type="missing_endorsement", severity="medium", title="EPA Endorsement Missing"),
        ]

        summary = generate_data_driven_summary(
            pack_name="Test Pack",
            extractions=[],
            flags=flags,
            readiness_score=70,
        )

        lines = summary.strip().split("\n")
        assert all(line.startswith("- ") for line in lines)
        assert "at risk" in lines[0].lower()
        assert "70/100" in lines[0]
        # Should mention the high flag specifically
        assert any("Open Mortgage Lien" in line for line in lines)
        # Should have a medium summary bullet
        assert any("medium" in line.lower() for line in lines)

    def test_not_ready_with_critical_flags(self):
        from app.micro_apps.title_intelligence.services.report_service import generate_data_driven_summary

        flags = [
            _mock_flag(flag_type="chain_of_title_gap", severity="critical", title="Missing Chain Link"),
            _mock_flag(flag_type="unreleased_mortgage", severity="critical", title="First Bank Mortgage"),
            _mock_flag(flag_type="name_discrepancy", severity="medium", title="Name Mismatch"),
        ]

        summary = generate_data_driven_summary(
            pack_name="Test Pack",
            extractions=[],
            flags=flags,
            readiness_score=35,
        )

        lines = summary.strip().split("\n")
        assert all(line.startswith("- ") for line in lines)
        assert "not ready" in lines[0].lower()
        assert "35/100" in lines[0]
        # Each critical flag gets its own bullet
        critical_lines = [l for l in lines if "CRITICAL" in l]
        assert len(critical_lines) == 2
        assert any("Missing Chain Link" in l for l in critical_lines)
        assert any("First Bank Mortgage" in l for l in critical_lines)

    def test_resolved_flags_ignored(self):
        from app.micro_apps.title_intelligence.services.report_service import generate_data_driven_summary

        flags = [
            _mock_flag(severity="critical", title="Resolved Issue", status="resolved"),
            _mock_flag(severity="high", title="Approved Issue", status="approved"),
        ]

        summary = generate_data_driven_summary(
            pack_name="Test Pack",
            extractions=[],
            flags=flags,
            readiness_score=92,
        )

        lines = summary.strip().split("\n")
        # Resolved flags should not appear as issues
        assert not any("CRITICAL" in line for line in lines)
        assert "ready to close" in lines[0].lower()

    def test_only_low_flags(self):
        from app.micro_apps.title_intelligence.services.report_service import generate_data_driven_summary

        flags = [
            _mock_flag(severity="low", title="Minor Note"),
            _mock_flag(severity="low", title="Informational Item"),
        ]

        summary = generate_data_driven_summary(
            pack_name="Test Pack",
            extractions=[],
            flags=flags,
            readiness_score=85,
        )

        lines = summary.strip().split("\n")
        assert any("low" in line.lower() for line in lines)

    def test_mixed_severities(self):
        from app.micro_apps.title_intelligence.services.report_service import generate_data_driven_summary

        flags = [
            _mock_flag(severity="critical", title="Critical Issue"),
            _mock_flag(severity="high", title="High Issue"),
            _mock_flag(severity="medium", title="Medium Issue"),
            _mock_flag(severity="low", title="Low Issue"),
        ]

        summary = generate_data_driven_summary(
            pack_name="Test Pack",
            extractions=[],
            flags=flags,
            readiness_score=40,
        )

        lines = summary.strip().split("\n")
        # Should have at least: status + critical + high + medium/low summary + next steps
        assert len(lines) >= 4

    def test_bullet_format_consistency(self):
        """Every line must start with '- ' to match frontend parsing."""
        from app.micro_apps.title_intelligence.services.report_service import generate_data_driven_summary

        for score, flag_list in [
            (95, []),
            (70, [_mock_flag(severity="high", title="Issue")]),
            (30, [_mock_flag(severity="critical", title="Big Issue")]),
        ]:
            summary = generate_data_driven_summary(
                pack_name="Test",
                extractions=[],
                flags=flag_list,
                readiness_score=score,
            )
            for line in summary.strip().split("\n"):
                assert line.startswith("- "), f"Line doesn't start with '- ': {line!r}"

    def test_deterministic_same_input_same_output(self):
        """Same inputs should always produce the exact same summary."""
        from app.micro_apps.title_intelligence.services.report_service import generate_data_driven_summary

        flags = [
            _mock_flag(severity="critical", title="Chain Gap"),
            _mock_flag(severity="medium", title="Name Issue"),
        ]

        summary1 = generate_data_driven_summary("Pack", [], flags, 55)
        summary2 = generate_data_driven_summary("Pack", [], flags, 55)
        assert summary1 == summary2

    def test_single_flag_grammar(self):
        """Verify correct singular grammar for single flags."""
        from app.micro_apps.title_intelligence.services.report_service import generate_data_driven_summary

        flags = [_mock_flag(severity="high", title="Single Issue")]

        summary = generate_data_driven_summary(
            pack_name="Test",
            extractions=[],
            flags=flags,
            readiness_score=65,
        )

        # Should use singular "issue" not "issues"
        first_line = summary.split("\n")[0]
        assert "1 open issue " in first_line or "1 open issue\n" in first_line or first_line.endswith("1 open issue.")

    def test_empty_flags_next_steps(self):
        """When all clear, next steps should confirm readiness."""
        from app.micro_apps.title_intelligence.services.report_service import generate_data_driven_summary

        summary = generate_data_driven_summary("Pack", [], [], 100)
        lines = summary.strip().split("\n")
        last_line = lines[-1].lower()
        assert "cleared" in last_line or "resolved" in last_line


class TestFlagTypeLabels:
    """Test that flag type labels produce readable output."""

    def test_known_flag_types_have_labels(self):
        from app.micro_apps.title_intelligence.services.report_service import _FLAG_TYPE_LABELS
        from app.micro_apps.title_intelligence.services.flag_rules import VALID_FLAG_TYPES

        for ft in VALID_FLAG_TYPES:
            assert ft in _FLAG_TYPE_LABELS, f"Missing label for flag type: {ft}"

    def test_critical_flag_includes_type_label(self):
        from app.micro_apps.title_intelligence.services.report_service import generate_data_driven_summary

        flag = _mock_flag(
            flag_type="chain_of_title_gap",
            severity="critical",
            title="Missing Transfer Deed",
        )

        summary = generate_data_driven_summary("Pack", [], [flag], 30)
        assert "chain of title gap" in summary.lower()
