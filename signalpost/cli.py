"""
Command Line Interface for SignalPost Agent.
Provides single-command execution for lookups, batch processing, benchmarking, and harvesting.
"""

import os
import sys
import json
import argparse
import logging
from typing import Optional

from signalpost.agent import SignalPostAgent
from signalpost.benchmark import run_benchmark
from signalpost.harvest import harvest_profiles
from signalpost.storage import Storage
from signalpost.smoke_test import run_smoke_test

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")



def print_profile_summary(profile):
    d = profile.data
    cd = d.get("company_details", {})
    pp = d.get("people", {})
    wf = d.get("workforce", {})
    fin = d.get("financials", {})

    print("\n" + "=" * 65)
    print(f" SIGNALPOST COMPANY PROFILE: {cd.get('name', 'N/A')}")
    print("=" * 65)
    print(f" Organisasjonsnummer:  {profile.organisasjonsnummer}")
    print(f" Result Status:        {profile.status.value.upper()}")
    print(f" Legal Form:           {cd.get('legal_form', {}).get('name', 'N/A')} ({cd.get('legal_form', {}).get('code', '')})")
    print(f" Primary Industry:     {cd.get('primary_nace', {}).get('kode', 'N/A')} - {cd.get('primary_nace', {}).get('beskrivelse', 'N/A')}")
    print(f" Registered Office:    {cd.get('business_address', {}).get('city', 'N/A')}, {cd.get('business_address', {}).get('country', 'Norge')}")
    print(f" Active Status:        {'ACTIVE' if cd.get('is_active') else 'INACTIVE / DISSOLVED'}")
    if cd.get('is_bankrupt'):
        print(f" Bankruptcy Flag:      YES (Konkurs)")
    if cd.get('in_liquidation'):
        print(f" Liquidation Flag:     YES (Under avvikling)")

    ceo = pp.get("ceo")
    if ceo:
        print(f" Managing Director:    {ceo.get('name')} (Appointed: {ceo.get('appointed_date', 'N/A')})")
    chair = pp.get("chair_of_board")
    if chair:
        print(f" Board Chairman:       {chair.get('name')}")
    
    emp = wf.get("employee_count")
    if emp is not None:
        print(f" Workforce Size:       {emp:,} registered personnel")
    
    cap = fin.get("share_capital")
    if cap is not None:
        print(f" Share Capital:        {cap:,.2f} {fin.get('currency', 'NOK')}")

    print("\n--- EXECUTIVE SUMMARY ---")
    print(profile.explanations.executive_summary)

    print("\n--- DISAMBIGUATION & STATUS REASONING ---")
    print(profile.explanations.disambiguation_reasoning)
    print(profile.explanations.status_envelope_reasoning)

    print("\n--- EVIDENCE PROVENANCE TRAIL ---")
    print(f" Total verified evidence links: {len(profile.provenance)}")
    for i, prov in enumerate(profile.provenance[:5], 1):
        print(f"  [{i}] {prov.field}: {prov.evidence_snippet[:80]}...")
        print(f"      Source: {prov.source_url}")
    if len(profile.provenance) > 5:
        print(f"      (... and {len(profile.provenance) - 5} more verified field linkages)")

    print("=" * 65 + "\n")


def main():
    parser = argparse.ArgumentParser(
        description="SignalPost: Autonomous Norwegian Company Intelligence Agent",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  py run.py --orgnr 923609016
  py run.py --query "Equinor"
  py run.py --batch input.json --output profiles.json
  py run.py --harvest 1000 --output dataset/profiles_1000.json
  py run.py --benchmark
  py run.py --smoke-test 100
  py run.py --serve --port 8080
        """
    )
    parser.add_argument("--orgnr", type=str, help="9-digit Norwegian organization number")
    parser.add_argument("--query", type=str, help="Company name or search query for disambiguation")
    parser.add_argument("--batch", type=str, help="Path to input JSON/JSONL/TXT file containing org numbers/names")
    parser.add_argument("--output", type=str, default="output_profile.json", help="Path to save output JSON/JSONL profile(s)")
    parser.add_argument("--format", type=str, choices=["profile", "canonical"], default="profile", help="Envelope format: 'profile' (rich) or 'canonical' (Builderr contract)")
    parser.add_argument("--harvest", type=int, nargs="?", const=1000, help="Harvest N real Norwegian company profiles (default 1000)")
    parser.add_argument("--smoke-test", type=int, nargs="?", const=100, help="Run official 100-company smoke test and generate verification report")
    parser.add_argument("--benchmark", action="store_true", help="Run 100-point benchmark evaluation suite")
    parser.add_argument("--serve", action="store_true", help="Launch interactive Web Dashboard & JBOX companion UI")
    parser.add_argument("--port", type=int, default=8080, help="Web server port (default 8080)")
    parser.add_argument("--web", action="store_true", help="Fetch live website presence (default: False for fast CLI)")

    args = parser.parse_args()

    if args.benchmark:
        run_benchmark()
        return

    if args.smoke_test is not None:
        count = args.smoke_test
        run_smoke_test(count=count)
        return

    if args.harvest:
        count = args.harvest
        out_file = args.output if args.output != "output_profile.json" else "dataset/profiles_1000.json"
        harvest_profiles(target_count=count, output_file=out_file, fetch_web=args.web)
        return

    if args.serve:
        from signalpost.web.app import run_server
        run_server(port=args.port)
        return

    target = args.orgnr or args.query

    if args.batch:
        if not os.path.exists(args.batch):
            print(f"[!] Error: Batch input file '{args.batch}' not found.")
            sys.exit(1)
        
        batch_inputs = []
        with open(args.batch, "r", encoding="utf-8") as f:
            content = f.read().strip()
            if args.batch.endswith(".jsonl"):
                for line in content.splitlines():
                    if line.strip():
                        batch_inputs.append(json.loads(line))
            elif args.batch.endswith(".json"):
                loaded = json.loads(content)
                batch_inputs = loaded if isinstance(loaded, list) else loaded.get("organisation_numbers", [loaded])
            else:
                for line in content.splitlines():
                    if line.strip():
                        batch_inputs.append(line.strip())
        
        agent = SignalPostAgent()
        results = []
        print(f"[*] Processing batch of {len(batch_inputs)} entities...")
        for item in batch_inputs:
            q = item.get("organisation_number") or item.get("organisasjonsnummer") or item.get("query") if isinstance(item, dict) else str(item)
            p = agent.research_company(q, fetch_web=args.web)
            if args.format == "canonical":
                results.append(p.to_canonical_envelope())
            else:
                results.append(p.to_dict())
        
        if args.output.endswith(".jsonl"):
            with open(args.output, "w", encoding="utf-8") as f:
                for res in results:
                    f.write(json.dumps(res, ensure_ascii=False) + "\n")
        else:
            with open(args.output, "w", encoding="utf-8") as f:
                json.dump(results, f, indent=2, ensure_ascii=False)
        print(f"[+] Finished processing batch! Results ({len(results)} envelopes) saved to '{args.output}'.")
        return

    if target:
        agent = SignalPostAgent()
        profile = agent.research_company(target, fetch_web=args.web)
        print_profile_summary(profile)

        # Save to output file
        with open(args.output, "w", encoding="utf-8") as f:
            if args.format == "canonical":
                json.dump(profile.to_canonical_envelope(), f, indent=2, ensure_ascii=False)
            else:
                json.dump(profile.to_dict(), f, indent=2, ensure_ascii=False)
        print(f"[+] Full structured JSON envelope written to: {os.path.abspath(args.output)}")
        return

    parser.print_help()


if __name__ == "__main__":
    main()

