import uuid

from sqlalchemy import ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TenantMixin, TimestampMixin
from app.models.compat import UUID, JSONB


class LODocTypeConfig(Base, TenantMixin, TimestampMixin):
    """Per-package configuration of expected document types.

    `doc_types` is a list of dicts: [{"key": "1003", "label": "URLA", "required": true}, ...]
    Any page classified into a type not in this list falls back to "Others".
    """
    __tablename__ = "lo_doc_type_configs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    package_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("lo_packages.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    doc_types: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)

    package = relationship("LOPackage", back_populates="doc_type_config", lazy="noload")
