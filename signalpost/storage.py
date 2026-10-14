"""
Persistence, Idempotent Updates, and Change Detection Storage for SignalPost.
Stores snapshots in SQLite and supports batch exports to JSON/JSONL.
"""

import os
import json
import sqlite3
import logging
from typing import Optional, Dict, Any, List, Tuple
from datetime import datetime, timezone
from signalpost.models import CompanyProfile, ChangeRecord, StatusEnvelope, Explanations, ProvenanceRecord

logger = logging.getLogger("signalpost.storage")

DEFAULT_DB_PATH = os.path.join(os.path.dirname(__file__), "..", "signalpost_data.sqlite")


class Storage:
    def __init__(self, db_path: Optional[str] = None):
        if db_path == ":memory:":
            self.db_path = ":memory:"
            self._is_memory = True
            self._mem_conn = sqlite3.connect(":memory:")
        else:
            self.db_path = os.path.abspath(db_path or DEFAULT_DB_PATH)
            self._is_memory = False
            self._mem_conn = None
            os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        self._init_db()

    def _get_connection(self):
        if self._is_memory and self._mem_conn:
            return self._mem_conn
        return sqlite3.connect(self.db_path)

    def _init_db(self):
        conn = self._get_connection()
        conn.execute("""
            CREATE TABLE IF NOT EXISTS company_profiles (
                organisasjonsnummer TEXT PRIMARY KEY,
                status TEXT NOT NULL,
                last_updated TEXT NOT NULL,
                profile_json TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_status ON company_profiles(status)
        """)
        conn.commit()
        if not self._is_memory:
            conn.close()

    def get_profile(self, orgnr: str) -> Optional[CompanyProfile]:
        """Loads the most recent profile snapshot from SQLite."""
        conn = self._get_connection()
        try:
            cursor = conn.execute(
                "SELECT profile_json FROM company_profiles WHERE organisasjonsnummer = ?",
                (orgnr,)
            )
            row = cursor.fetchone()
            if not row:
                return None
            data = json.loads(row[0])
            return self._dict_to_profile(data)
        finally:
            if not self._is_memory:
                conn.close()

    def save_profile(self, profile: CompanyProfile) -> Tuple[CompanyProfile, List[ChangeRecord]]:
        """
        Saves the profile idempotently. If an older profile exists, computes field diffs,
        appends them to the audit log, and preserves history.
        """
        existing = self.get_profile(profile.organisasjonsnummer)
        new_changes: List[ChangeRecord] = []

        if existing:
            # Detect changes between existing and new
            new_changes = self.calculate_diff(existing.data, profile.data, profile.provenance)
            # Inherit existing audit log and prepend/append new changes
            combined_audit = list(existing.audit_log) + new_changes
            profile.audit_log = combined_audit

        conn = self._get_connection()
        try:
            conn.execute("""
                INSERT INTO company_profiles (organisasjonsnummer, status, last_updated, profile_json)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(organisasjonsnummer) DO UPDATE SET
                    status=excluded.status,
                    last_updated=excluded.last_updated,
                    profile_json=excluded.profile_json
            """, (
                profile.organisasjonsnummer,
                profile.status.value if isinstance(profile.status, StatusEnvelope) else profile.status,
                profile.last_updated,
                json.dumps(profile.to_dict(), ensure_ascii=False)
            ))
            conn.commit()
        finally:
            if not self._is_memory:
                conn.close()

        return profile, new_changes

    def calculate_diff(
        self,
        old_data: Dict[str, Any],
        new_data: Dict[str, Any],
        provenance_list: List[ProvenanceRecord]
    ) -> List[ChangeRecord]:
        """
        Calculates field-level differences between old and new snapshots.
        Idempotent: Identical values produce zero changes.
        """
        changes: List[ChangeRecord] = []
        now_iso = datetime.now(timezone.utc).isoformat()

        # Map provenance field to evidence
        prov_map = {p.field: p for p in provenance_list if hasattr(p, 'field')}

        def compare_keys(prefix: str, d1: Any, d2: Any):
            if isinstance(d1, dict) and isinstance(d2, dict):
                all_keys = set(d1.keys()).union(set(d2.keys()))
                for k in sorted(all_keys):
                    field_name = f"{prefix}.{k}" if prefix else k
                    v1 = d1.get(k)
                    v2 = d2.get(k)
                    compare_keys(field_name, v1, v2)
            elif d1 != d2:
                # Value has changed!
                prov = prov_map.get(prefix)
                changes.append(ChangeRecord(
                    field=prefix,
                    old_value=d1,
                    new_value=d2,
                    changed_at=now_iso,
                    source_url=prov.source_url if prov else None,
                    evidence_snippet=prov.evidence_snippet if prov else None
                ))

        compare_keys("", old_data, new_data)
        return changes

    def list_all(self, limit: Optional[int] = None) -> List[CompanyProfile]:
        query = "SELECT profile_json FROM company_profiles ORDER BY last_updated DESC"
        if limit:
            query += f" LIMIT {int(limit)}"
        
        profiles = []
        conn = self._get_connection()
        try:
            for row in conn.execute(query):
                profiles.append(self._dict_to_profile(json.loads(row[0])))
        finally:
            if not self._is_memory:
                conn.close()
        return profiles

    def count(self) -> int:
        conn = self._get_connection()
        try:
            cursor = conn.execute("SELECT COUNT(*) FROM company_profiles")
            return cursor.fetchone()[0]
        finally:
            if not self._is_memory:
                conn.close()

    def export_json(self, output_file: str, indent: int = 2) -> int:
        profiles = self.list_all()
        data = [p.to_dict() for p in profiles]
        os.makedirs(os.path.dirname(os.path.abspath(output_file)), exist_ok=True)
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=indent)
        return len(data)

    def export_jsonl(self, output_file: str) -> int:
        profiles = self.list_all()
        os.makedirs(os.path.dirname(os.path.abspath(output_file)), exist_ok=True)
        with open(output_file, "w", encoding="utf-8") as f:
            for p in profiles:
                f.write(json.dumps(p.to_dict(), ensure_ascii=False) + "\n")
        return len(profiles)

    def _dict_to_profile(self, d: Dict[str, Any]) -> CompanyProfile:
        prov = [
            ProvenanceRecord(**p) if isinstance(p, dict) else p 
            for p in d.get("provenance", [])
        ]
        audit = [
            ChangeRecord(**c) if isinstance(c, dict) else c 
            for c in d.get("audit_log", [])
        ]
        exp_dict = d.get("explanations", {})
        explanations = Explanations(
            disambiguation_reasoning=exp_dict.get("disambiguation_reasoning", ""),
            status_envelope_reasoning=exp_dict.get("status_envelope_reasoning", ""),
            executive_summary=exp_dict.get("executive_summary", "")
        )
        return CompanyProfile(
            organisasjonsnummer=d.get("organisasjonsnummer", ""),
            status=StatusEnvelope(d.get("status", "available")),
            last_updated=d.get("last_updated", ""),
            data=d.get("data", {}),
            provenance=prov,
            explanations=explanations,
            audit_log=audit
        )
