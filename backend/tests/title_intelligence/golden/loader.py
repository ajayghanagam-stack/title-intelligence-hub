"""Loader utility for golden dataset fixtures.

Usage:
    from tests.title_intelligence.golden.loader import load_golden_set

    dataset = load_golden_set("simple_commitment")
    assert dataset.metadata.ai_model == "gemini/gemini-2.5-flash"
    assert len(dataset.extractions) > 0
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from tests.title_intelligence.golden.metadata_schema import GoldenMetadata

GOLDEN_DIR = Path(__file__).parent


@dataclass
class GoldenDataset:
    """A loaded golden dataset with all fixture data."""

    name: str
    metadata: GoldenMetadata
    triage: list[dict[str, Any]] = field(default_factory=list)
    transcriptions: list[dict[str, Any]] = field(default_factory=list)
    sections: list[dict[str, Any]] = field(default_factory=list)
    extractions: list[dict[str, Any]] = field(default_factory=list)
    flags_raw: list[dict[str, Any]] = field(default_factory=list)
    flags_normalized: list[dict[str, Any]] = field(default_factory=list)
    chain: dict[str, Any] = field(default_factory=dict)
    pdf_path: Path | None = None

    @property
    def has_pdf(self) -> bool:
        return self.pdf_path is not None and self.pdf_path.exists()


def _load_json(path: Path) -> Any:
    """Load a JSON file, returning empty list/dict if missing."""
    if not path.exists():
        return [] if path.stem != "chain" else {}
    with open(path) as f:
        return json.load(f)


def load_golden_set(name: str) -> GoldenDataset:
    """Load all JSON fixtures for a named golden dataset.

    Args:
        name: Directory name under tests/title_intelligence/golden/
              (e.g., "simple_commitment")

    Returns:
        GoldenDataset with all available fixture data loaded.

    Raises:
        FileNotFoundError: If the dataset directory or metadata.json is missing.
    """
    dataset_dir = GOLDEN_DIR / name
    if not dataset_dir.is_dir():
        raise FileNotFoundError(f"Golden dataset directory not found: {dataset_dir}")

    metadata_path = dataset_dir / "metadata.json"
    if not metadata_path.exists():
        raise FileNotFoundError(f"metadata.json not found in {dataset_dir}")

    with open(metadata_path) as f:
        metadata = GoldenMetadata.model_validate(json.load(f))

    # Find PDF if present
    pdf_path = dataset_dir / "input.pdf"
    if not pdf_path.exists():
        pdf_path = None

    return GoldenDataset(
        name=name,
        metadata=metadata,
        triage=_load_json(dataset_dir / "triage.json"),
        transcriptions=_load_json(dataset_dir / "transcriptions.json"),
        sections=_load_json(dataset_dir / "sections.json"),
        extractions=_load_json(dataset_dir / "extractions.json"),
        flags_raw=_load_json(dataset_dir / "flags_raw.json"),
        flags_normalized=_load_json(dataset_dir / "flags_normalized.json"),
        chain=_load_json(dataset_dir / "chain.json"),
        pdf_path=pdf_path,
    )


def list_golden_sets() -> list[str]:
    """List all available golden dataset names."""
    return [
        d.name for d in GOLDEN_DIR.iterdir()
        if d.is_dir() and (d / "metadata.json").exists()
    ]


def validate_golden_set_versions(dataset: GoldenDataset) -> list[str]:
    """Check if golden set versions match current code.

    Returns list of mismatch descriptions (empty = all match).
    """
    from app.micro_apps.title_intelligence.services.flag_rules import RULES_VERSION
    from app.micro_apps.title_intelligence.services.chain_builder import CHAIN_BUILDER_VERSION
    from app.micro_apps.title_intelligence.services.party_normalizer import NORMALIZER_VERSION

    mismatches = []
    m = dataset.metadata

    if m.flag_rules_version != RULES_VERSION:
        mismatches.append(
            f"flag_rules_version: golden={m.flag_rules_version}, current={RULES_VERSION}"
        )
    if m.chain_builder_version != CHAIN_BUILDER_VERSION:
        mismatches.append(
            f"chain_builder_version: golden={m.chain_builder_version}, current={CHAIN_BUILDER_VERSION}"
        )
    if m.normalizer_version != NORMALIZER_VERSION:
        mismatches.append(
            f"normalizer_version: golden={m.normalizer_version}, current={NORMALIZER_VERSION}"
        )

    return mismatches
