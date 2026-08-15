"""Declarative document blueprints.

A blueprint describes one document type as data: its sections, how the two sides are labelled,
whether it claims money, which procedural checks apply and which interview questions collect the
facts. The drafting engine, Final Legal QA, the Word exporter and the Telegram interview all read
the same blueprint, so supporting a new category of case means adding a blueprint entry rather than
adding branches across the pipeline.
"""

from korgan_legal_ai.blueprints.interview import FIELDS, FieldKind, InterviewField, field_by_id
from korgan_legal_ai.blueprints.models import (
    AddresseeKind,
    DocumentBlueprint,
    PartyPresentation,
    Section,
    SectionKind,
)
from korgan_legal_ai.blueprints.registry import (
    BLUEPRINTS,
    CLAIM_DEBT_RECOVERY,
    blueprint_by_key,
    resolve_blueprint,
    supported_document_types,
)

__all__ = [
    "BLUEPRINTS",
    "CLAIM_DEBT_RECOVERY",
    "FIELDS",
    "AddresseeKind",
    "DocumentBlueprint",
    "FieldKind",
    "InterviewField",
    "PartyPresentation",
    "Section",
    "SectionKind",
    "blueprint_by_key",
    "field_by_id",
    "resolve_blueprint",
    "supported_document_types",
]
