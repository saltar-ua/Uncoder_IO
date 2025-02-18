import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from app.translator.core.custom_types.meta_info import SeverityType
from app.translator.core.mapping import DEFAULT_MAPPING_NAME
from app.translator.core.models.functions.base import ParsedFunctions


class MetaInfoContainer:
    def __init__(
        self,
        *,
        id_: Optional[str] = None,
        title: Optional[str] = None,
        description: Optional[str] = None,
        author: Optional[str] = None,
        date: Optional[str] = None,
        license_: Optional[str] = None,
        severity: Optional[str] = None,
        references: Optional[list[str]] = None,
        tags: Optional[list[str]] = None,
        mitre_attack: Optional[dict[str, list]] = None,
        status: Optional[str] = None,
        false_positives: Optional[list[str]] = None,
        source_mapping_ids: Optional[list[str]] = None,
    ) -> None:
        self.id = id_ or str(uuid.uuid4())
        self.title = title or ""
        self.description = description or ""
        self.author = author or ""
        self.date = date or datetime.now().date().strftime("%Y-%m-%d")
        self.license = license_ or "DRL 1.1"
        self.severity = severity or SeverityType.low
        self.references = references or []
        self.tags = tags or []
        self.mitre_attack = mitre_attack or {}
        self.status = status or "stable"
        self.false_positives = false_positives or []
        self.source_mapping_ids = source_mapping_ids or [DEFAULT_MAPPING_NAME]


@dataclass
class SiemContainer:
    query: list
    meta_info: MetaInfoContainer
    functions: ParsedFunctions = field(default_factory=ParsedFunctions)
