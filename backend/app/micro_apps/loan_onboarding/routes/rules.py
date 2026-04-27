"""Rules catalog routes — list available presets."""
from fastapi import APIRouter, Depends

from app.core.deps import get_current_member
from app.micro_apps.loan_onboarding.services.validation_presets import PRESET_IDS
from app.models.user import User

router = APIRouter()


_PRESET_CATALOG = [
    {
        "rule_id": "missing_signatures",
        "label": "Missing signatures",
        "description": "Flag stacks that do not contain a signature page.",
        "config_schema": [],
    },
    {
        "rule_id": "missing_pages",
        "label": "Missing first/last page",
        "description": "Flag stacks that don't have both a first_page and a last_page marker.",
        "config_schema": [],
    },
    {
        "rule_id": "missing_fields",
        "label": "Missing required fields",
        "description": "Flag stacks where named fields are absent from detected_fields.",
        "config_schema": [
            {
                "name": "required_fields",
                "type": "string_list",
                "label": "Required fields",
                "default": [],
            }
        ],
    },
]


router = APIRouter()


@router.get("/rules/presets")
async def list_preset_catalog(
    member: User = Depends(get_current_member),
):
    """Return the catalog of available preset validation rules."""
    # Sanity: every dispatched preset id must appear in the catalog.
    catalog_ids = {entry["rule_id"] for entry in _PRESET_CATALOG}
    missing = set(PRESET_IDS) - catalog_ids
    if missing:
        # Engineering error — keep it loud so it's caught in CI.
        raise RuntimeError(f"Preset catalog is missing entries: {missing}")
    return _PRESET_CATALOG
