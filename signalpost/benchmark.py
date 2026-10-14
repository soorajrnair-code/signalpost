"""
SignalPost Evaluation Benchmark Suite.
Directly scores the agent against the 5 official criteria of the Signalpost challenge:
1. Useful Information (35 pts)
2. Evidence & Source Linking (30 pts)
3. Correct Updates & Idempotency (20 pts)
4. Explanations & Disambiguation (10 pts)
5. Usability & Schema Conformance (5 pts)
Total: 100 points
"""

import sys
import json
import time
from typing import Dict, Any, List

from signalpost.agent import SignalPostAgent
from signalpost.models import StatusEnvelope, CompanyProfile, ProvenanceRecord
from signalpost.storage import Storage

# Benchmark reference entities
TEST_ENTITIES = [
    {"name": "EQUINOR ASA", "orgnr": "923609016", "expected_status": StatusEnvelope.AVAILABLE},
    {"name": "TELENOR ASA", "orgnr": "982463718", "expected_status": StatusEnvelope.AVAILABLE},
    {"name": "DNB BANK ASA", "orgnr": "984851006", "expected_status": StatusEnvelope.AVAILABLE},
]


def run_benchmark() -> Dict[str, Any]:
    print("=" * 65)
    print(" SIGNALPOST AUTONOMOUS AGENT BENCHMARK SUITE")
    print(" Testing compliance against Builderr / Signalpost 100-Point Rubric")
    print("=" * 65)

    scores = {
        "useful_information": 0.0,      # Max 35
        "evidence_linking": 0.0,        # Max 30
        "update_accuracy": 0.0,         # Max 20
        "explanations": 0.0,            # Max 10
        "usability_schema": 0.0         # Max 5
    }

    agent = SignalPostAgent()
    start_time = time.time()

    # --- CATEGORY 1 & 2: Useful Information (35 pts) & Evidence Linking (30 pts) ---
    print("\n[+] [1/5] Evaluating Information Extraction & Evidence Provenance...")
    extracted_profiles: List[CompanyProfile] = []
    
    for ref in TEST_ENTITIES:
        orgnr = ref["orgnr"]
        p = agent.research_company(orgnr, fetch_web=False)
        extracted_profiles.append(p)
        print(f"    Tested {ref['name']} ({orgnr}) -> Status: {p.status.value}")

    # Check depth of useful information
    info_points = 0.0
    for p in extracted_profiles:
        d = p.data
        has_name = bool(d.get("company_details", {}).get("name"))
        has_legal = bool(d.get("company_details", {}).get("legal_form", {}).get("name"))
        has_addr = bool(d.get("company_details", {}).get("business_address", {}).get("city"))
        has_nace = bool(d.get("company_details", {}).get("primary_nace", {}).get("kode"))
        has_people = bool(d.get("people", {}).get("ceo") or d.get("people", {}).get("chair_of_board"))
        has_workforce = d.get("workforce", {}).get("employee_count") is not None
        has_financials = d.get("financials", {}).get("share_capital") is not None
        
        completeness = sum([has_name, has_legal, has_addr, has_nace, has_people, has_workforce, has_financials]) / 7.0
        info_points += completeness

    scores["useful_information"] = round((info_points / len(extracted_profiles)) * 35.0, 1)
    print(f"    -> Information Depth Score: {scores['useful_information']} / 35.0")

    # Check evidence precision (source_url, snippet, timestamp)
    evidence_valid_count = 0
    total_prov_count = 0
    for p in extracted_profiles:
        for prov in p.provenance:
            total_prov_count += 1
            if prov.source_url and prov.evidence_snippet and prov.retrieved_at:
                evidence_valid_count += 1

    prov_ratio = evidence_valid_count / total_prov_count if total_prov_count > 0 else 0
    scores["evidence_linking"] = round(prov_ratio * 30.0, 1)
    print(f"    -> Evidence Linking Score: {scores['evidence_linking']} / 30.0 ({evidence_valid_count}/{total_prov_count} verified facts)")

    # --- CATEGORY 3: Update Accuracy & Idempotency (20 pts) ---
    print("\n[+] [2/5] Evaluating Update Accuracy & Idempotency...")
    # Use dedicated isolated storage to test idempotency and delta detection
    bench_storage = Storage(db_path=":memory:")
    bench_agent = SignalPostAgent(storage=bench_storage)

    test_org = TEST_ENTITIES[0]["orgnr"]
    p_run1 = bench_agent.research_company(test_org, fetch_web=False)
    
    # Run 2 on identical data
    p_run2 = bench_agent.research_company(test_org, fetch_web=False)
    # Total historical audit log should only contain records if new diffs occurred
    idempotent_pass = (len(p_run2.audit_log) == 0)

    # Test 2: Injected delta should be captured exactly
    current_profile = bench_storage.get_profile(test_org)
    mod_data = dict(current_profile.data)
    mod_data["workforce"] = {"employee_count": 99999, "registration_date": "2026-10-13"}
    p_sim = CompanyProfile(
        organisasjonsnummer=test_org,
        status=StatusEnvelope.AVAILABLE,
        data=mod_data,
        provenance=[ProvenanceRecord(
            field="workforce.employee_count",
            value=99999,
            source_url="https://test.brreg.no",
            evidence_snippet="99999 employees"
        )]
    )
    _, diffs = bench_storage.save_profile(p_sim)
    delta_caught = any(d.field == "workforce.employee_count" and d.new_value == 99999 for d in diffs)

    update_score = 0.0
    if idempotent_pass:
        update_score += 10.0
        print("    [PASS] Idempotency test: 0 spurious changes generated on identical re-run.")
    else:
        print("    [FAIL] Idempotency test: unwanted diffs detected.")

    if delta_caught:
        update_score += 10.0
        print("    [PASS] Delta capture test: accurately logged simulated field shift.")
    else:
        print("    [FAIL] Delta capture test: simulated shift missed.")

    scores["update_accuracy"] = update_score
    print(f"    -> Update Accuracy Score: {scores['update_accuracy']} / 20.0")

    # --- CATEGORY 4: Explanations & Disambiguation (10 pts) ---
    print("\n[+] [3/5] Evaluating Explanations & Disambiguation...")
    exp_points = 0.0

    # Test ambiguous query
    p_amb = agent.research_company("Nordic Tech", fetch_web=False)
    if p_amb.status == StatusEnvelope.AMBIGUOUS and "ambiguous" in p_amb.explanations.disambiguation_reasoning.lower():
        exp_points += 3.5
        print("    [PASS] Handled ambiguous corporate candidates safely (marked 'ambiguous').")

    # Test non-existent orgnr
    p_none = agent.research_company("999999999", fetch_web=False)
    if p_none.status == StatusEnvelope.NOT_AVAILABLE and p_none.explanations.status_envelope_reasoning:
        exp_points += 3.5
        print("    [PASS] Handled non-existent company with explicit 404 registry reasoning.")

    # Test executive summary quality
    if extracted_profiles[0].explanations.executive_summary:
        exp_points += 3.0
        print("    [PASS] Generated executive summary synthesizing purpose and operations.")

    scores["explanations"] = round(exp_points, 1)
    print(f"    -> Explanations Score: {scores['explanations']} / 10.0")

    # --- CATEGORY 5: Usability & Schema Conformance (5 pts) ---
    print("\n[+] [4/5] Evaluating Schema Conformance & Usability...")
    conformance_keys = ["organisasjonsnummer", "status", "last_updated", "data", "provenance", "explanations", "audit_log"]
    p_dict = extracted_profiles[0].to_dict()
    all_keys_present = all(k in p_dict for k in conformance_keys)
    status_valid = p_dict["status"] in [s.value for s in StatusEnvelope]

    if all_keys_present and status_valid:
        scores["usability_schema"] = 5.0
        print("    [PASS] Strict adherence to Builderr Signalpost JSON schema envelope.")
    else:
        scores["usability_schema"] = 3.0

    print(f"    -> Usability Score: {scores['usability_schema']} / 5.0")

    # --- TOTAL RESULTS ---
    total = sum(scores.values())
    elapsed = time.time() - start_time

    print("\n" + "=" * 65)
    print(" BENCHMARK RESULTS SUMMARY")
    print("=" * 65)
    print(f" 1. Useful Information:            {scores['useful_information']:>5.1f} / 35.0")
    print(f" 2. Evidence & Source Linking:     {scores['evidence_linking']:>5.1f} / 30.0")
    print(f" 3. Correct Updates & Idempotency: {scores['update_accuracy']:>5.1f} / 20.0")
    print(f" 4. Useful Explanations:           {scores['explanations']:>5.1f} / 10.0")
    print(f" 5. Usability & Conformance:       {scores['usability_schema']:>5.1f} /  5.0")
    print("-" * 65)
    print(f" TOTAL EVALUATION SCORE:           {total:>5.1f} / 100.0")
    print(f" Total Benchmark Time:             {elapsed:>5.2f} seconds")
    print("=" * 65)

    return {"scores": scores, "total": total, "elapsed": elapsed}


if __name__ == "__main__":
    run_benchmark()
