import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.micro_apps.title_search.models.document import TADocument
from app.micro_apps.title_search.models.raw_document import TARawDocument
from app.micro_apps.title_search.models.review import TAReview
from app.core.exceptions import NotFoundError


async def list_documents(
    db: AsyncSession,
    org_id: uuid.UUID,
    order_id: uuid.UUID,
    doc_type: str | None = None,
    needs_review: bool | None = None,
) -> list[TADocument]:
    query = select(TADocument).where(
        TADocument.order_id == order_id,
        TADocument.org_id == org_id,
    )
    if doc_type:
        query = query.where(TADocument.doc_type == doc_type)
    if needs_review is not None:
        query = query.where(TADocument.needs_review == needs_review)
    query = query.order_by(TADocument.created_at)
    result = await db.execute(query)
    return list(result.scalars().all())


async def get_document_or_raise(
    db: AsyncSession, org_id: uuid.UUID, order_id: uuid.UUID, doc_id: uuid.UUID
) -> TADocument:
    result = await db.execute(
        select(TADocument).where(
            TADocument.id == doc_id,
            TADocument.order_id == order_id,
            TADocument.org_id == org_id,
        )
    )
    doc = result.scalar_one_or_none()
    if not doc:
        raise NotFoundError("Document", doc_id)
    return doc


async def correct_document(
    db: AsyncSession,
    org_id: uuid.UUID,
    order_id: uuid.UUID,
    doc_id: uuid.UUID,
    reviewer_id: uuid.UUID,
    updates: dict,
) -> TADocument:
    doc = await get_document_or_raise(db, org_id, order_id, doc_id)

    # Capture original values for audit
    original_value = {}
    corrected_value = {}
    for key, value in updates.items():
        if value is not None and hasattr(doc, key):
            original_value[key] = getattr(doc, key)
            corrected_value[key] = value
            setattr(doc, key, value)

    doc.needs_review = False

    # Create review record
    review = TAReview(
        org_id=org_id,
        order_id=order_id,
        document_id=doc_id,
        reviewer_id=reviewer_id,
        decision="correct",
        original_value=original_value,
        corrected_value=corrected_value,
    )
    db.add(review)
    await db.commit()
    await db.refresh(doc)
    return doc


async def create_raw_document(
    db: AsyncSession,
    org_id: uuid.UUID,
    order_id: uuid.UUID,
    source_assignment_id: uuid.UUID,
    storage_path: str,
    content_format: str,
    document_ref: str | None = None,
    raw_content: str | None = None,
) -> TARawDocument:
    raw_doc = TARawDocument(
        org_id=org_id,
        order_id=order_id,
        source_assignment_id=source_assignment_id,
        storage_path=storage_path,
        content_format=content_format,
        document_ref=document_ref,
        raw_content=raw_content,
    )
    db.add(raw_doc)
    await db.commit()
    await db.refresh(raw_doc)
    return raw_doc
