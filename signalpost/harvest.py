"""
Batch Harvester to generate 1,000+ verified Norwegian company profiles.
Fulfills the mandatory submission requirement: 'At least 1,000 structured company profiles'.
Queries BRREG's paginated entity index and processes them concurrently with rate limiting.
"""

import os
import sys
import time
import json
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Optional

import requests
from signalpost.agent import SignalPostAgent
from signalpost.storage import Storage

logger = logging.getLogger("signalpost.harvest")


def fetch_norwegian_orgnrs(target_count: int = 1000, page_size: int = 100) -> List[str]:
    """
    Fetches active Norwegian organization numbers directly from BRREG.
    """
    orgnrs = []
    base_url = "https://data.brreg.no/enhetsregisteret/api/enheter"
    page = 0
    headers = {"Accept": "application/json", "User-Agent": "SignalPost-Agent/1.0"}

    print(f"[*] Discovering {target_count} active Norwegian companies from Enhetsregisteret...")
    while len(orgnrs) < target_count:
        params = {"size": page_size, "page": page}
        try:
            resp = requests.get(base_url, params=params, headers=headers, timeout=15)
            if resp.status_code == 200:
                data = resp.json()
                entities = data.get("_embedded", {}).get("enheter", [])
                if not entities:
                    break
                for e in entities:
                    num = e.get("organisasjonsnummer")
                    if num:
                        orgnrs.append(num)
                        if len(orgnrs) >= target_count:
                            break
                page += 1
                print(f"    Discovered {len(orgnrs)} / {target_count} organization numbers...")
            else:
                print(f"[!] Warning: HTTP {resp.status_code} on page {page}")
                break
        except Exception as e:
            print(f"[!] Network error on discovery page {page}: {e}")
            break
        time.sleep(0.1)

    return orgnrs[:target_count]


def harvest_profiles(
    target_count: int = 1000,
    output_file: str = "dataset/profiles_1000.json",
    concurrency: int = 8,
    fetch_web: bool = False
) -> int:
    """
    Harvests full profiles for target_count companies and saves to output_file.
    Set fetch_web=False for high-speed bulk ingestion (avoids 1,000 external HTTP web scrapes).
    """
    storage = Storage()
    agent = SignalPostAgent(storage=storage)

    orgnrs = fetch_norwegian_orgnrs(target_count=target_count)
    if not orgnrs:
        print("[!] Failed to collect organization numbers.")
        return 0

    print(f"[*] Beginning concurrent research for {len(orgnrs)} companies (workers: {concurrency})...")
    start_time = time.time()
    completed = 0
    failed = 0

    def process_one(num: str):
        try:
            return agent.research_company(num, fetch_web=fetch_web)
        except Exception as e:
            return None

    with ThreadPoolExecutor(max_workers=concurrency) as executor:
        futures = {executor.submit(process_one, num): num for num in orgnrs}
        for fut in as_completed(futures):
            res = fut.result()
            if res:
                completed += 1
            else:
                failed += 1
            if completed % 50 == 0 or completed == len(orgnrs):
                elapsed = time.time() - start_time
                rate = completed / elapsed if elapsed > 0 else 0
                print(f"    Processed {completed}/{len(orgnrs)} profiles ({rate:.1f} profiles/sec)...")

    # Export to JSON
    out_path = os.path.abspath(output_file)
    exported_count = storage.export_json(out_path)
    total_time = time.time() - start_time
    print(f"\n[+] Successfully harvested and exported {exported_count} profiles to:")
    print(f"    {out_path}")
    print(f"    Total elapsed time: {total_time:.2f} seconds ({total_time/60:.1f} minutes).")
    return exported_count


if __name__ == "__main__":
    count = int(sys.argv[1]) if len(sys.argv) > 1 else 1000
    harvest_profiles(target_count=count)
