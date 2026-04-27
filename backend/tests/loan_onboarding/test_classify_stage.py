"""Tests for the PageClassifierAgent + stage_classify.

The agent's LLM call is mocked at `BaseAIService.call_json_structured` — we do
not hit Gemini/Vertex in CI. Tests cover:
- Schema conformance (per-package enum, Others fallback, confidence clamping)
- Chunked parallel classify with global page number preservation
- stage_classify idempotency and blank-page short-circuit
"""
import uuid
from unittest.mock import AsyncMock, patch

import fitz
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.micro_apps.loan_onboarding.ai.page_classifier_agent import (
    OTHERS_KEY,
    ClassifierChunkError,
    PageClassifierAgent,
    _build_json_schema,
    _coerce_classification,
)
from app.micro_apps.loan_onboarding.models.classification import LOClassification
from app.micro_apps.loan_onboarding.models.package_file import LOPackageFile
from app.micro_apps.loan_onboarding.pipeline.stages import stage_classify
from app.services.storage import get_storage
from tests.conftest import TEST_ORG_ID
from tests.loan_onboarding.conftest import TEST_PACKAGE_ID


# ── unit tests for helpers ────────────────────────────────────────────────

def test_build_json_schema_adds_others_bucket():
    schema = _build_json_schema(["URLA_1003", "PAYSTUB"])
    enum = schema["properties"]["classifications"]["items"]["properties"]["predicted_doc_type"]["enum"]
    assert "URLA_1003" in enum
    assert "PAYSTUB" in enum
    assert OTHERS_KEY in enum


def test_coerce_unknown_doc_type_falls_back_to_others():
    clf = _coerce_classification(
        {"page_number": 2, "predicted_doc_type": "UNKNOWN_TYPE", "confidence": 0.5},
        allowed_set={"URLA_1003", OTHERS_KEY},
    )
    assert clf.predicted_doc_type == OTHERS_KEY


def test_coerce_clamps_confidence_out_of_range():
    clf = _coerce_classification(
        {"page_number": 1, "predicted_doc_type": "URLA_1003", "confidence": 1.7},
        allowed_set={"URLA_1003", OTHERS_KEY},
    )
    assert clf.confidence == 1.0

    clf = _coerce_classification(
        {"page_number": 1, "predicted_doc_type": "URLA_1003", "confidence": -0.2},
        allowed_set={"URLA_1003", OTHERS_KEY},
    )
    assert clf.confidence == 0.0


def test_coerce_drops_bad_bbox_fields():
    clf = _coerce_classification(
        {
            "page_number": 1, "predicted_doc_type": "URLA_1003", "confidence": 0.9,
            "detected_fields": [
                {"field_name": "Name", "value": "Jane", "bbox": [1, 2, 3, 4]},
                {"field_name": "Bad", "value": "x", "bbox": [1, 2]},  # wrong length
                {"field_name": "Missing", "value": "x"},               # no bbox
            ],
        },
        allowed_set={"URLA_1003", OTHERS_KEY},
    )
    assert len(clf.detected_fields) == 1
    assert clf.detected_fields[0].field_name == "Name"


def test_coerce_filters_invalid_alternatives():
    clf = _coerce_classification(
        {
            "page_number": 1, "predicted_doc_type": "URLA_1003", "confidence": 0.9,
            "predicted_doc_type_alternatives": [
                {"type": "PAYSTUB", "confidence": 0.1},
                {"type": "UNKNOWN", "confidence": 0.05},   # not in enum → dropped
            ],
        },
        allowed_set={"URLA_1003", "PAYSTUB", OTHERS_KEY},
    )
    assert len(clf.predicted_doc_type_alternatives) == 1
    assert clf.predicted_doc_type_alternatives[0].type == "PAYSTUB"


def test_agent_rejects_reserved_others_in_config():
    with pytest.raises(ValueError, match="reserved"):
        PageClassifierAgent(
            org_id=uuid.uuid4(),
            allowed_doc_types=["URLA_1003", OTHERS_KEY],
        )


def test_agent_requires_at_least_one_doc_type():
    with pytest.raises(ValueError):
        PageClassifierAgent(org_id=uuid.uuid4(), allowed_doc_types=[])


# ── classify_pdf with mocked LLM ─────────────────────────────────────────

@pytest.mark.asyncio
async def test_classify_pdf_overwrites_page_numbers_with_caller_numbering():
    """The caller supplies global page numbers; the agent stamps them onto output."""
    agent = PageClassifierAgent(
        org_id=uuid.uuid4(),
        allowed_doc_types=["URLA_1003", "PAYSTUB"],
    )

    # Mock out the LLM — returns local (1..N) numbering
    mock_llm = AsyncMock(return_value={
        "classifications": [
            {"page_number": 1, "predicted_doc_type": "URLA_1003", "confidence": 0.9, "page_role": "first_page"},
            {"page_number": 2, "predicted_doc_type": "PAYSTUB", "confidence": 0.88, "page_role": "first_page"},
        ]
    })

    with patch.object(PageClassifierAgent, "call_json_structured", mock_llm):
        result = await agent.classify_pdf(
            pdf_bytes=b"%PDF-1.4 dummy",
            page_numbers=[5, 9],  # global numbering
        )

    assert len(result.classifications) == 2
    # Global page numbers stamped onto output
    assert result.classifications[0].page_number == 5
    assert result.classifications[1].page_number == 9
    assert result.classifications[0].predicted_doc_type == "URLA_1003"


@pytest.mark.asyncio
async def test_classify_pdf_raises_on_llm_failure():
    """classify_pdf signals failure via ClassifierChunkError so the outer
    chunked dispatcher can split-and-retry rather than silently zeroing pages."""
    agent = PageClassifierAgent(
        org_id=uuid.uuid4(),
        allowed_doc_types=["URLA_1003"],
    )
    fail = AsyncMock(side_effect=RuntimeError("gemini is down"))
    with patch.object(PageClassifierAgent, "call_json_structured", fail):
        with pytest.raises(ClassifierChunkError):
            await agent.classify_pdf(
                pdf_bytes=b"x",
                page_numbers=[1, 2, 3],
            )


@pytest.mark.asyncio
async def test_classify_pdf_raises_on_empty_response():
    """An empty {} response (truncation signature) must not become silent
    Others/0.0 — it must raise so the caller splits and retries."""
    agent = PageClassifierAgent(
        org_id=uuid.uuid4(),
        allowed_doc_types=["URLA_1003"],
    )
    empty = AsyncMock(return_value={})
    with patch.object(PageClassifierAgent, "call_json_structured", empty):
        with pytest.raises(ClassifierChunkError):
            await agent.classify_pdf(
                pdf_bytes=b"x",
                page_numbers=[1, 2, 3],
            )


@pytest.mark.asyncio
async def test_classify_pdf_raises_on_short_response():
    """A response missing >30% of requested entries signals partial truncation
    and must raise so the outer dispatcher can retry with smaller splits."""
    agent = PageClassifierAgent(
        org_id=uuid.uuid4(),
        allowed_doc_types=["URLA_1003"],
    )
    # 10 pages requested, only 3 returned → 70% missing, well past the 30% floor
    short = AsyncMock(return_value={
        "classifications": [
            {"page_number": i + 1, "predicted_doc_type": "URLA_1003",
             "confidence": 0.9, "page_role": "continuation"}
            for i in range(3)
        ]
    })
    with patch.object(PageClassifierAgent, "call_json_structured", short):
        with pytest.raises(ClassifierChunkError):
            await agent.classify_pdf(
                pdf_bytes=b"x",
                page_numbers=list(range(1, 11)),
            )


@pytest.mark.asyncio
async def test_classify_pdf_chunked_split_retries_down_to_single_pages():
    """When a chunk fails, classify_pdf_chunked halves the chunk and retries,
    down to single-page calls, before falling back to Others/0.0.

    This is the key behavior that replaced the old silent-fallback contract:
    a failed 4-page call becomes two 2-page calls, then four 1-page calls.
    Only a genuinely unclassifiable single page ends up as Others/0.0.
    """
    agent = PageClassifierAgent(
        org_id=uuid.uuid4(),
        allowed_doc_types=["URLA_1003"],
    )
    pdf_bytes = _make_pdf(["p1", "p2", "p3", "p4"])

    call_page_counts: list[int] = []

    async def fake_call(*, system_prompt, messages, json_schema, **kwargs):
        # The user-visible message text encodes the page count, so we can
        # measure how many pages each dispatched call covered.
        text = messages[0]["content"][0]["text"]
        # Example: "Classify every page of this 4-page PDF. ..."
        import re
        m = re.search(r"this (\d+)-page", text)
        n = int(m.group(1)) if m else 0
        call_page_counts.append(n)

        # Fail any call with more than 1 page; succeed on single-page calls.
        # This exercises the full split-retry tree and proves the recursion
        # terminates at depth where n==1.
        if n > 1:
            raise RuntimeError("simulated truncation on multi-page batch")
        return {
            "classifications": [
                {"page_number": 1, "predicted_doc_type": "URLA_1003",
                 "confidence": 0.9, "page_role": "continuation"},
            ]
        }

    with patch.object(PageClassifierAgent, "call_json_structured", side_effect=fake_call):
        result = await agent.classify_pdf_chunked(
            pdf_bytes_per_chunk=[(pdf_bytes, [10, 11, 12, 13])],
            concurrency=2,
        )

    # All 4 pages eventually classified (via single-page retries)
    assert [c.page_number for c in result.classifications] == [10, 11, 12, 13]
    assert all(c.predicted_doc_type == "URLA_1003" for c in result.classifications)
    # Sanity: the dispatcher actually drilled down to 1-page calls
    assert 1 in call_page_counts, f"expected single-page calls, got {call_page_counts}"
    # And the original 4-page call failed at least once
    assert 4 in call_page_counts, f"expected original 4-page call, got {call_page_counts}"


@pytest.mark.asyncio
async def test_classify_pdf_chunked_single_page_failure_falls_back_to_others():
    """Once split-retry reaches 1 page and still fails, the page is marked
    Others/0.0 — the floor of the silent-fallback bucket. This preserves
    pipeline forward progress without losing the failure signal (confidence=0
    routes the stack to HITL review)."""
    agent = PageClassifierAgent(
        org_id=uuid.uuid4(),
        allowed_doc_types=["URLA_1003"],
    )
    pdf_bytes = _make_pdf(["only page"])

    fail = AsyncMock(side_effect=RuntimeError("gemini is down at every granularity"))

    with patch.object(PageClassifierAgent, "call_json_structured", fail):
        result = await agent.classify_pdf_chunked(
            pdf_bytes_per_chunk=[(pdf_bytes, [42])],
            concurrency=1,
        )

    assert len(result.classifications) == 1
    clf = result.classifications[0]
    assert clf.page_number == 42
    assert clf.predicted_doc_type == OTHERS_KEY
    assert clf.confidence == 0.0


@pytest.mark.asyncio
async def test_classify_pdf_chunked_merges_in_global_order():
    agent = PageClassifierAgent(
        org_id=uuid.uuid4(),
        allowed_doc_types=["URLA_1003"],
    )

    async def fake_call(*, system_prompt, messages, json_schema, **kwargs):
        # Return N 'URLA_1003' entries, matching the batch size requested
        n = len(messages[0]["content"][0]["text"].split())  # noqa — placeholder
        # Use a cleaner signal: count pages by counting the requested page_numbers
        return {
            "classifications": [
                {"page_number": i + 1, "predicted_doc_type": "URLA_1003",
                 "confidence": 0.9, "page_role": "continuation"}
                for i in range(10)  # upper bound; agent only uses first N
            ]
        }

    with patch.object(PageClassifierAgent, "call_json_structured", side_effect=fake_call):
        result = await agent.classify_pdf_chunked(
            pdf_bytes_per_chunk=[
                (b"chunkA", [10, 11]),
                (b"chunkB", [1, 2, 3]),
                (b"chunkC", [20]),
            ],
            concurrency=2,
        )
    # Sorted by global page number regardless of dispatch order
    assert [c.page_number for c in result.classifications] == [1, 2, 3, 10, 11, 20]


# ── stage_classify integration ────────────────────────────────────────────

def _make_pdf(page_texts: list[str]) -> bytes:
    doc = fitz.open()
    for text in page_texts:
        page = doc.new_page(width=612, height=792)
        if text:
            page.insert_text((72, 72), text)
    out = doc.tobytes()
    doc.close()
    return out


async def _upload_file(
    db: AsyncSession, storage, package_id: uuid.UUID, filename: str, pdf_bytes: bytes
) -> LOPackageFile:
    path = storage.make_pack_path(TEST_ORG_ID, package_id, filename)
    await storage.put_object(path, pdf_bytes, content_type="application/pdf")
    row = LOPackageFile(
        org_id=TEST_ORG_ID,
        package_id=package_id,
        filename=filename,
        storage_path=path,
        content_hash="x" * 64,
        size_bytes=len(pdf_bytes),
        page_count=0,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row


@pytest.mark.asyncio
async def test_stage_classify_skips_blank_pages_and_writes_rows(
    sample_package, db_session: AsyncSession
):
    from app.micro_apps.loan_onboarding.pipeline.stages import stage_ingest

    storage = get_storage()
    # Page 1 has lots of text, page 2 is blank, page 3 has text
    pdf_bytes = _make_pdf([
        "URLA 1003 — Borrower: Jane Smith. Loan Amount: $350000. Employment: Acme Inc.",
        "",
        "Pay stub — Gross: $5000. Net: $3800. Period ending 03/15/2026.",
    ])
    await _upload_file(db_session, storage, TEST_PACKAGE_ID, "bundle.pdf", pdf_bytes)

    await stage_ingest(TEST_PACKAGE_ID, TEST_ORG_ID, db_session, storage)
    await db_session.commit()

    # Mock the classifier: returns URLA_1003 for the first content page, PAYSTUB for the second
    # (classifier only ever sees content pages 1 and 3)
    async def fake_call(*, system_prompt, messages, json_schema, **kwargs):
        return {
            "classifications": [
                {"page_number": 1, "predicted_doc_type": "URLA_1003",
                 "confidence": 0.92, "page_role": "first_page"},
                {"page_number": 2, "predicted_doc_type": "PAYSTUB",
                 "confidence": 0.88, "page_role": "first_page"},
            ]
        }

    with patch.object(PageClassifierAgent, "call_json_structured", side_effect=fake_call):
        out = await stage_classify(TEST_PACKAGE_ID, TEST_ORG_ID, db_session, storage)
        await db_session.commit()

    assert out == {
        "pages": 3, "content_pages": 2, "image_pages": 0, "blank_pages": 1,
    }

    rows = (await db_session.execute(
        select(LOClassification)
        .where(LOClassification.package_id == TEST_PACKAGE_ID)
        .order_by(LOClassification.page_number)
    )).scalars().all()
    assert [r.page_number for r in rows] == [1, 2, 3]
    assert rows[0].predicted_doc_type == "URLA_1003"
    assert rows[1].predicted_doc_type == OTHERS_KEY   # blank page
    assert rows[1].confidence == 1.0
    assert rows[2].predicted_doc_type == "PAYSTUB"


@pytest.mark.asyncio
async def test_stage_classify_is_idempotent(
    sample_package, db_session: AsyncSession
):
    from app.micro_apps.loan_onboarding.pipeline.stages import stage_ingest

    storage = get_storage()
    pdf_bytes = _make_pdf(["URLA 1003 page one — Borrower: Jane. Income: $120k."])
    await _upload_file(db_session, storage, TEST_PACKAGE_ID, "bundle.pdf", pdf_bytes)
    await stage_ingest(TEST_PACKAGE_ID, TEST_ORG_ID, db_session, storage)
    await db_session.commit()

    async def fake_call(**kwargs):
        return {"classifications": [
            {"page_number": 1, "predicted_doc_type": "URLA_1003",
             "confidence": 0.9, "page_role": "first_page"},
        ]}

    with patch.object(PageClassifierAgent, "call_json_structured", side_effect=fake_call):
        await stage_classify(TEST_PACKAGE_ID, TEST_ORG_ID, db_session, storage)
        await db_session.commit()
        await stage_classify(TEST_PACKAGE_ID, TEST_ORG_ID, db_session, storage)
        await db_session.commit()

    rows = (await db_session.execute(
        select(LOClassification).where(LOClassification.package_id == TEST_PACKAGE_ID)
    )).scalars().all()
    assert len(rows) == 1  # no duplicates


@pytest.mark.asyncio
async def test_stage_classify_requires_ingest_first(
    sample_package, db_session: AsyncSession
):
    storage = get_storage()
    with pytest.raises(ValueError, match="No pages to classify"):
        await stage_classify(TEST_PACKAGE_ID, TEST_ORG_ID, db_session, storage)


@pytest.mark.asyncio
async def test_stage_classify_routes_image_pages_to_llm(
    sample_package, db_session: AsyncSession
):
    """Hybrid ingest: pages with content_signal='image' must be sent to the LLM.

    Prior behavior (pre-hybrid) auto-Othered any page with text_length < 20,
    which meant scanned loan packages never reached Gemini. This test proves
    the fix: an image-only page lands in the classifier's input and receives
    a real doc_type, not the deterministic Others-with-confidence-1.0.
    """
    from app.micro_apps.loan_onboarding.pipeline.stages import stage_ingest
    from tests.loan_onboarding.test_pipeline_ingest import (
        _make_scanned_pdf,
        _upload_file as _upload_ingest,
    )

    storage = get_storage()
    pdf_bytes = _make_scanned_pdf(num_pages=2)
    await _upload_ingest(db_session, storage, TEST_PACKAGE_ID, "scanned.pdf", pdf_bytes)

    await stage_ingest(TEST_PACKAGE_ID, TEST_ORG_ID, db_session, storage)
    await db_session.commit()

    # The classifier should see 2 pages (the image-bearing pair). Emit
    # URLA_1003 for both so we can prove they did not get auto-Othered.
    captured_page_counts: list[int] = []

    async def fake_call(*, system_prompt, messages, json_schema, **kwargs):
        # Message text mentions the page count — easiest stable signal for
        # the test to cross-check how many pages were actually dispatched.
        text_block = messages[0]["content"][0]["text"]
        captured_page_counts.append(text_block.count("page"))
        return {
            "classifications": [
                {"page_number": 1, "predicted_doc_type": "URLA_1003",
                 "confidence": 0.85, "page_role": "first_page"},
                {"page_number": 2, "predicted_doc_type": "URLA_1003",
                 "confidence": 0.82, "page_role": "continuation"},
            ]
        }

    with patch.object(PageClassifierAgent, "call_json_structured", side_effect=fake_call):
        out = await stage_classify(TEST_PACKAGE_ID, TEST_ORG_ID, db_session, storage)
        await db_session.commit()

    # Both scanned pages must count as "content" (sent to LLM), not "blank"
    assert out["pages"] == 2
    assert out["content_pages"] == 2
    assert out["image_pages"] == 2
    assert out["blank_pages"] == 0

    rows = (await db_session.execute(
        select(LOClassification)
        .where(LOClassification.package_id == TEST_PACKAGE_ID)
        .order_by(LOClassification.page_number)
    )).scalars().all()
    assert [r.predicted_doc_type for r in rows] == ["URLA_1003", "URLA_1003"]
    # The LLM was invoked (not short-circuited)
    assert captured_page_counts, "classifier was not called — image pages were auto-Othered"


@pytest.mark.asyncio
async def test_stage_classify_still_shortcircuits_truly_blank_pages(
    sample_package, db_session: AsyncSession
):
    """content_signal='blank' must continue to skip the LLM and get Others@1.0."""
    from app.micro_apps.loan_onboarding.pipeline.stages import stage_ingest

    storage = get_storage()
    pdf_bytes = _make_pdf(["", ""])  # both pages empty → signal='blank'
    await _upload_file(db_session, storage, TEST_PACKAGE_ID, "empty.pdf", pdf_bytes)

    await stage_ingest(TEST_PACKAGE_ID, TEST_ORG_ID, db_session, storage)
    await db_session.commit()

    # call_json_structured should NOT be invoked at all — assert via side_effect
    async def _boom(**_kwargs):  # pragma: no cover — must not run
        raise AssertionError("LLM called for a truly blank page")

    with patch.object(PageClassifierAgent, "call_json_structured", side_effect=_boom):
        out = await stage_classify(TEST_PACKAGE_ID, TEST_ORG_ID, db_session, storage)
        await db_session.commit()

    assert out == {
        "pages": 2, "content_pages": 0, "image_pages": 0, "blank_pages": 2,
    }
    rows = (await db_session.execute(
        select(LOClassification).where(LOClassification.package_id == TEST_PACKAGE_ID)
    )).scalars().all()
    assert [r.predicted_doc_type for r in rows] == [OTHERS_KEY, OTHERS_KEY]
    assert all(r.confidence == 1.0 for r in rows)
