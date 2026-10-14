"""
Data models and schemas conforming to Builderr.ai / Signalpost specification.
"""

from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import List, Dict, Any, Optional
from datetime import datetime, timezone


class StatusEnvelope(str, Enum):
    """Canonical terminal result envelopes required by Builderr / Signalpost."""
    AVAILABLE = "available"
    NOT_AVAILABLE = "not_available"
    BLOCKED = "blocked"
    NOT_APPLICABLE = "not_applicable"
    AMBIGUOUS = "ambiguous"
    FAILED = "failed"


class SourceType(str, Enum):
    OFFICIAL_REGISTRY = "OFFICIAL_REGISTRY"
    FIRST_PARTY_WEBSITE = "FIRST_PARTY_WEBSITE"
    INFERRED_WEB = "INFERRED_WEB"


@dataclass
class ProvenanceRecord:
    """Verifiable evidence linkage for an extracted fact."""
    field: str
    value: Any
    source_url: str
    evidence_snippet: str
    retrieved_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    source_type: SourceType = SourceType.OFFICIAL_REGISTRY
    confidence: float = 1.0

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d['source_type'] = self.source_type.value if isinstance(self.source_type, SourceType) else self.source_type
        return d


@dataclass
class ChangeRecord:
    """Tracks temporal updates and field diffs across runs."""
    field: str
    old_value: Any
    new_value: Any
    changed_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    source_url: Optional[str] = None
    evidence_snippet: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class AddressInfo:
    address_lines: List[str] = field(default_factory=list)
    postal_code: str = ""
    city: str = ""
    municipality: str = ""
    municipality_number: str = ""
    country: str = "Norge"
    country_code: str = "NO"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def formatted(self) -> str:
        lines = list(self.address_lines)
        if self.postal_code or self.city:
            lines.append(f"{self.postal_code} {self.city}".strip())
        if self.country and self.country != "Norge":
            lines.append(self.country)
        return ", ".join([l for l in lines if l])


@dataclass
class PersonRole:
    name: str
    role_code: str
    role_description: str
    is_deceased: bool = False
    appointed_date: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class Explanations:
    disambiguation_reasoning: str = ""
    status_envelope_reasoning: str = ""
    executive_summary: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class CompanyProfile:
    """
    Complete structured profile conforming to the Signalpost company intelligence schema.
    """
    organisasjonsnummer: str
    status: StatusEnvelope
    last_updated: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    data: Dict[str, Any] = field(default_factory=dict)
    provenance: List[ProvenanceRecord] = field(default_factory=list)
    explanations: Explanations = field(default_factory=Explanations)
    audit_log: List[ChangeRecord] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "organisasjonsnummer": self.organisasjonsnummer,
            "status": self.status.value if isinstance(self.status, StatusEnvelope) else self.status,
            "last_updated": self.last_updated,
            "data": self.data,
            "provenance": [p.to_dict() if hasattr(p, "to_dict") else p for p in self.provenance],
            "explanations": self.explanations.to_dict() if hasattr(self.explanations, "to_dict") else self.explanations,
            "audit_log": [c.to_dict() if hasattr(c, "to_dict") else c for c in self.audit_log]
        }

    def to_canonical_envelope(self, run_id: str = "signalpost-run", requests: int = 4, runtime_ms: int = 150) -> Dict[str, Any]:
        """
        Formats profile strictly according to the Builderr minimal output contract.
        """
        import hashlib
        evidence_list = []
        claims_list = []
        for i, prov in enumerate(self.provenance, 1):
            ev_id = f"ev-{i}"
            snippet = prov.evidence_snippet or ""
            c_hash = hashlib.sha256(snippet.encode('utf-8')).hexdigest()
            source_cls = "official_registry" if "brreg.no" in str(prov.source_url) else "company_owned"
            evidence_list.append({
                "id": ev_id,
                "source_url": prov.source_url,
                "source_class": source_cls,
                "retrieved_at": prov.retrieved_at,
                "content_sha256": c_hash,
                "claim_span": snippet
            })
            claims_list.append({
                "field": prov.field,
                "value": prov.value,
                "availability": self.status.value if isinstance(self.status, StatusEnvelope) else str(self.status),
                "confidence": prov.confidence,
                "evidence_ids": [ev_id]
            })
        status_str = self.status.value if isinstance(self.status, StatusEnvelope) else str(self.status)
        return {
            "organisation_number": self.organisasjonsnummer,
            "run": {
                "run_id": run_id,
                "started_at": self.last_updated,
                "completed_at": self.last_updated,
                "terminal_status": "completed" if self.status == StatusEnvelope.AVAILABLE else status_str
            },
            "claims": claims_list,
            "evidence": evidence_list,
            "changes": [c.to_dict() if hasattr(c, "to_dict") else c for c in self.audit_log],
            "errors": [],
            "operations": {
                "requests": requests,
                "runtime_ms": runtime_ms,
                "third_party_cost_usd": 0.0
            }
        }

