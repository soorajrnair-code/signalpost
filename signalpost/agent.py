"""
SignalPost Autonomous Research Agent.
Main coordinator orchestrating validation, registry lookup, web intelligence,
evidence attribution, change diffing, and schema formatting.
"""

import json
import logging
from typing import Dict, Any, List, Optional
from datetime import datetime, timezone

from signalpost.models import (
    CompanyProfile,
    StatusEnvelope,
    SourceType,
    ProvenanceRecord,
    Explanations,
    AddressInfo
)
from signalpost.validator import (
    normalize_orgnr,
    validate_orgnr,
    is_likely_orgnr
)
from signalpost.registry_client import BRREGClient
from signalpost.web_researcher import WebResearcher
from signalpost.synthesizer import Synthesizer
from signalpost.storage import Storage

logger = logging.getLogger("signalpost.agent")


class SignalPostAgent:
    def __init__(
        self,
        storage: Optional[Storage] = None,
        registry_client: Optional[BRREGClient] = None,
        web_researcher: Optional[WebResearcher] = None,
        synthesizer: Optional[Synthesizer] = None
    ):
        self.storage = storage or Storage()
        self.registry = registry_client or BRREGClient()
        self.web = web_researcher or WebResearcher()
        self.synth = synthesizer or Synthesizer()

    def research_company(self, query: str, fetch_web: bool = True) -> CompanyProfile:
        """
        Main entry point for autonomous company research.
        Accepts 9-digit Norwegian organization number or company name string.
        """
        raw_query = str(query).strip()
        normalized = normalize_orgnr(raw_query)
        now_iso = datetime.now(timezone.utc).isoformat()

        # Step 1: Input Analysis and Routing
        if not normalized:
            explanations = self.synth.generate_explanations(
                raw_query, StatusEnvelope.FAILED, error_msg="Empty query provided."
            )
            return CompanyProfile(
                organisasjonsnummer="",
                status=StatusEnvelope.FAILED,
                last_updated=now_iso,
                data={},
                provenance=[],
                explanations=explanations
            )

        target_orgnr = normalized
        candidates = None

        if not normalized.isdigit():
            # Query is a name string -> Perform registry search & disambiguation
            search_results = self.registry.search_by_name(normalized, size=5)
            if not search_results:
                explanations = self.synth.generate_explanations(
                    raw_query, StatusEnvelope.NOT_AVAILABLE
                )
                return CompanyProfile(
                    organisasjonsnummer="",
                    status=StatusEnvelope.NOT_AVAILABLE,
                    last_updated=now_iso,
                    data={},
                    provenance=[],
                    explanations=explanations
                )
            elif len(search_results) == 1:
                target_orgnr = search_results[0].get("organisasjonsnummer")
            else:
                # Multiple candidates found -> strict safety: AMBIGUOUS
                candidates = search_results
                explanations = self.synth.generate_explanations(
                    raw_query, StatusEnvelope.AMBIGUOUS, candidates=candidates
                )
                return CompanyProfile(
                    organisasjonsnummer=candidates[0].get("organisasjonsnummer", ""),
                    status=StatusEnvelope.AMBIGUOUS,
                    last_updated=now_iso,
                    data={"candidates": [
                        {"navn": c.get("navn"), "organisasjonsnummer": c.get("organisasjonsnummer")}
                        for c in candidates
                    ]},
                    provenance=[],
                    explanations=explanations
                )
        else:
            # Query is digits -> Verify Modulo 11 checksum
            is_valid, validation_msg = validate_orgnr(normalized)
            if not is_valid:
                explanations = self.synth.generate_explanations(
                    raw_query, StatusEnvelope.NOT_AVAILABLE, error_msg=validation_msg
                )
                return CompanyProfile(
                    organisasjonsnummer=normalized,
                    status=StatusEnvelope.NOT_AVAILABLE,
                    last_updated=now_iso,
                    data={"validation_error": validation_msg},
                    provenance=[],
                    explanations=explanations
                )

        # Step 2: Query Norwegian Central Coordinating Register (BRREG)
        try:
            entity_raw = self.registry.get_enhet(target_orgnr)
        except Exception as e:
            explanations = self.synth.generate_explanations(
                target_orgnr, StatusEnvelope.FAILED, error_msg=str(e)
            )
            return CompanyProfile(
                organisasjonsnummer=target_orgnr,
                status=StatusEnvelope.FAILED,
                last_updated=now_iso,
                data={},
                provenance=[],
                explanations=explanations
            )

        if not entity_raw:
            explanations = self.synth.generate_explanations(
                target_orgnr, StatusEnvelope.NOT_AVAILABLE
            )
            return CompanyProfile(
                organisasjonsnummer=target_orgnr,
                status=StatusEnvelope.NOT_AVAILABLE,
                last_updated=now_iso,
                data={},
                provenance=[],
                explanations=explanations
            )

        # Step 3: Query Roles and Sub-Entities
        roles_raw = self.registry.get_roller(target_orgnr)
        underenheter_raw = self.registry.get_underenheter(target_orgnr, size=15)

        # Step 4: Web Research & First-Party Presence
        web_info: Dict[str, Any] = {}
        website_url = entity_raw.get("hjemmeside")
        if fetch_web and website_url:
            web_info = self.web.fetch_company_web_presence(website_url)

        # Step 5: Data Extraction & Evidence-First Provenance Mapping
        profile_data, provenance_records = self._extract_and_prove(
            target_orgnr, entity_raw, roles_raw, underenheter_raw, web_info, now_iso
        )

        # Step 6: Explanations & Synthesis
        explanations = self.synth.generate_explanations(
            query=raw_query,
            status=StatusEnvelope.AVAILABLE,
            entity_raw=entity_raw,
            roles_raw=roles_raw,
            web_info=web_info
        )

        # Step 7: Build Profile Envelope
        profile = CompanyProfile(
            organisasjonsnummer=target_orgnr,
            status=StatusEnvelope.AVAILABLE,
            last_updated=now_iso,
            data=profile_data,
            provenance=provenance_records,
            explanations=explanations,
            audit_log=[]
        )

        # Step 8: Idempotent Storage & Change Detection
        saved_profile, changes = self.storage.save_profile(profile)
        return saved_profile

    def _extract_and_prove(
        self,
        orgnr: str,
        entity: Dict[str, Any],
        roles: Optional[Dict[str, Any]],
        underenheter: List[Dict[str, Any]],
        web_info: Dict[str, Any],
        now_iso: str
    ) -> tuple[Dict[str, Any], List[ProvenanceRecord]]:
        provenance: List[ProvenanceRecord] = []
        reg_url = f"https://data.brreg.no/enhetsregisteret/api/enheter/{orgnr}"
        roles_url = f"https://data.brreg.no/enhetsregisteret/api/enheter/{orgnr}/roller"

        def add_prov(field_path: str, value: Any, url: str, snippet: str, stype=SourceType.OFFICIAL_REGISTRY, conf=1.0):
            provenance.append(ProvenanceRecord(
                field=field_path,
                value=value,
                source_url=url,
                evidence_snippet=snippet,
                retrieved_at=now_iso,
                source_type=stype,
                confidence=conf
            ))

        # --- Company Details ---
        name = entity.get("navn", "")
        add_prov("company_details.name", name, reg_url, f'"navn": "{name}"')

        org_form = entity.get("organisasjonsform", {})
        org_form_code = org_form.get("kode", "")
        org_form_desc = org_form.get("beskrivelse", "")
        add_prov("company_details.legal_form", {"kode": org_form_code, "beskrivelse": org_form_desc}, reg_url, json.dumps(org_form))

        reg_date = entity.get("registreringsdatoEnhetsregisteret", "")
        if reg_date:
            add_prov("company_details.registration_date", reg_date, reg_url, f'"registreringsdatoEnhetsregisteret": "{reg_date}"')

        founding_date = entity.get("stiftelsesdato", "")
        if founding_date:
            add_prov("company_details.founding_date", founding_date, reg_url, f'"stiftelsesdato": "{founding_date}"')

        # Status flags
        konkurs = bool(entity.get("konkurs", False))
        under_avvik = bool(entity.get("underAvvikling", False))
        tvang = bool(entity.get("underTvangsavviklingEllerTvangsopplosning", False))
        is_active = not (konkurs or under_avvik or tvang)

        add_prov("company_details.is_active", is_active, reg_url, f'"konkurs": {str(konkurs).lower()}, "underAvvikling": {str(under_avvik).lower()}')
        add_prov("company_details.is_bankrupt", konkurs, reg_url, f'"konkurs": {str(konkurs).lower()}')
        add_prov("company_details.in_liquidation", under_avvik, reg_url, f'"underAvvikling": {str(under_avvik).lower()}')

        # Addresses
        forr_addr = entity.get("forretningsadresse") or {}
        post_addr = entity.get("postadresse") or {}

        def parse_addr(a: Dict[str, Any]) -> Dict[str, Any]:
            lines = a.get("adresse", [])
            return {
                "address_lines": lines if isinstance(lines, list) else [str(lines)],
                "postal_code": a.get("postnummer", ""),
                "city": a.get("poststed", ""),
                "municipality": a.get("kommune", ""),
                "municipality_number": a.get("kommunenummer", ""),
                "country": a.get("land", "Norge"),
                "country_code": a.get("landkode", "NO")
            }

        addr_details = parse_addr(forr_addr)
        add_prov("company_details.business_address", addr_details, reg_url, json.dumps(forr_addr))

        # Industry NACE
        nace1 = entity.get("naeringskode1", {})
        add_prov("company_details.primary_nace", nace1, reg_url, json.dumps(nace1))

        # Capital & Financials
        kapital = entity.get("kapital", {})
        share_capital = kapital.get("belop")
        currency = kapital.get("valuta", "NOK")
        shares = kapital.get("antallAksjer")
        annual_accounts_year = entity.get("sisteInnsendteAarsregnskap")

        if share_capital is not None:
            add_prov("financials.share_capital", share_capital, reg_url, json.dumps(kapital))
        if annual_accounts_year:
            add_prov("financials.last_submitted_annual_accounts_year", annual_accounts_year, reg_url, f'"sisteInnsendteAarsregnskap": "{annual_accounts_year}"')

        # Workforce
        employees = entity.get("antallAnsatte")
        emp_reg_date = entity.get("registreringsdatoAntallAnsatteEnhetsregisteret")
        if employees is not None:
            add_prov("workforce.employee_count", employees, reg_url, f'"antallAnsatte": {employees}')

        # Statutory Purpose
        purpose = entity.get("vedtektsfestetFormaal") or []
        add_prov("company_details.statutory_purpose", purpose, reg_url, json.dumps(purpose))

        # --- Roles & People ---
        ceo_info = None
        chair_info = None
        board_members = []
        auditor_info = None

        if roles and "rollegrupper" in roles:
            for group in roles.get("rollegrupper", []):
                g_type = group.get("type", {}).get("kode", "")
                r_list = group.get("roller", [])

                if g_type == "DAGL":  # Daglig leder / CEO
                    for r in r_list:
                        p = r.get("person", {})
                        p_name = p.get("navn", {})
                        full_name = f"{p_name.get('fornavn', '')} {p_name.get('etternavn', '')}".strip()
                        ceo_info = {
                            "name": full_name,
                            "role": r.get("type", {}).get("beskrivelse", "Daglig leder"),
                            "appointed_date": group.get("sistEndret")
                        }
                        add_prov("people.ceo", ceo_info, roles_url, json.dumps(r))
                        break

                elif g_type == "STYR":  # Styre / Board
                    for r in r_list:
                        p = r.get("person", {})
                        p_name = p.get("navn", {})
                        full_name = f"{p_name.get('fornavn', '')} {p_name.get('etternavn', '')}".strip()
                        role_desc = r.get("type", {}).get("beskrivelse", "")
                        role_code = r.get("type", {}).get("kode", "")
                        
                        member_obj = {
                            "name": full_name,
                            "role": role_desc,
                            "role_code": role_code
                        }
                        if role_code == "LEDE":  # Styreleder
                            chair_info = member_obj
                            add_prov("people.chair_of_board", chair_info, roles_url, json.dumps(r))
                        else:
                            board_members.append(member_obj)

                    if board_members:
                        add_prov("people.board_members", board_members, roles_url, f"Total board members: {len(board_members)}")

                elif g_type == "REVI":  # Auditor
                    for r in r_list:
                        enh = r.get("enhet", {})
                        auditor_info = {
                            "name": enh.get("navn"),
                            "organisasjonsnummer": enh.get("organisasjonsnummer"),
                            "status": enh.get("godkjenningsstatus")
                        }
                        add_prov("people.auditor", auditor_info, roles_url, json.dumps(r))
                        break

        # --- Web & Contact ---
        website_url_clean = entity.get("hjemmeside")
        phone = entity.get("telefon")
        emails = web_info.get("contact_emails", [])
        social_links = web_info.get("social_links", {})
        meta_desc = web_info.get("meta_description", "")

        if website_url_clean:
            add_prov("web_and_contact.website_url", website_url_clean, reg_url, f'"hjemmeside": "{website_url_clean}"')
        if phone:
            add_prov("web_and_contact.phone", phone, reg_url, f'"telefon": "{phone}"')
        if meta_desc and web_info.get("source_url"):
            add_prov("web_and_contact.meta_description", meta_desc, web_info["source_url"], f"Meta snippet: {meta_desc[:250]}", SourceType.FIRST_PARTY_WEBSITE, 0.95)
        if social_links and web_info.get("source_url"):
            add_prov("web_and_contact.social_links", social_links, web_info["source_url"], json.dumps(social_links), SourceType.FIRST_PARTY_WEBSITE, 0.90)

        # Sub-entities
        sub_list = [
            {
                "navn": u.get("navn"),
                "organisasjonsnummer": u.get("organisasjonsnummer"),
                "antallAnsatte": u.get("antallAnsatte")
            }
            for u in underenheter
        ]
        if sub_list:
            add_prov("sub_entities", sub_list, f"https://data.brreg.no/enhetsregisteret/api/underenheter?overordnetEnhet={orgnr}", f"Sub-entities count: {len(sub_list)}")

        data: Dict[str, Any] = {
            "company_details": {
                "name": name,
                "organisasjonsnummer": orgnr,
                "legal_form": {"code": org_form_code, "name": org_form_desc},
                "is_active": is_active,
                "is_bankrupt": konkurs,
                "in_liquidation": under_avvik,
                "registration_date": reg_date,
                "founding_date": founding_date,
                "business_address": addr_details,
                "postal_address": parse_addr(post_addr),
                "primary_nace": nace1,
                "statutory_purpose": purpose,
                "historical_names": entity.get("historiskeNavn", [])
            },
            "people": {
                "ceo": ceo_info,
                "chair_of_board": chair_info,
                "board_members": board_members,
                "auditor": auditor_info
            },
            "workforce": {
                "employee_count": employees,
                "registration_date": emp_reg_date
            },
            "financials": {
                "share_capital": share_capital,
                "currency": currency,
                "number_of_shares": shares,
                "last_submitted_annual_accounts_year": annual_accounts_year
            },
            "web_and_contact": {
                "website_url": website_url_clean,
                "phone": phone,
                "contact_emails": emails,
                "social_links": social_links,
                "meta_description": meta_desc
            },
            "sub_entities": sub_list
        }

        return data, provenance
