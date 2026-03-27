#!/usr/bin/env python3
"""
Scroll all documents from the MultiversX scdeploys index and print each hit (full ES hit, not just _source)
as NDJSON to stdout. No CLI, no drama.
"""

import json
import sys
from typing import Dict, Any, Iterator, List

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

BASE_URL = "https://index.multiversx.com"
INDEX = "scdeploys"
BATCH_SIZE = 1000          # tune me if you like RAM roulette
SCROLL_KEEPALIVE = "1m"    # how long ES should keep the scroll context alive


def _session() -> requests.Session:
    s = requests.Session()
    retries = Retry(
        total=5,
        backoff_factor=0.5,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset(["GET", "POST", "DELETE"])
    )
    s.headers.update({"Content-Type": "application/json"})
    s.mount("http://", HTTPAdapter(max_retries=retries))
    s.mount("https://", HTTPAdapter(max_retries=retries))
    return s


def scroll_hits() -> Iterator[Dict[str, Any]]:
    """
    Yields raw ES hits from the scdeploys index until exhausted.
    """
    session = _session()

    # initial search with scroll param
    search_url = f"{BASE_URL.rstrip('/')}/{INDEX}/_search?scroll={SCROLL_KEEPALIVE}"
    payload = {
        "size": BATCH_SIZE,
        "sort": ["_doc"],          # fastest for scrolling
        "query": {"match_all": {}},
        "track_total_hits": True,  # play nice with 'gte' totals
    }

    resp = session.post(search_url, data=json.dumps(payload), timeout=60)
    resp.raise_for_status()
    data = resp.json()

    scroll_id = data.get("_scroll_id")
    if not scroll_id:
        raise RuntimeError("No _scroll_id returned by initial search. The cluster said 'no' politely.")

    try:
        hits: List[Dict[str, Any]] = data.get("hits", {}).get("hits", [])
        while hits:
            for hit in hits:
                yield hit

            # keep scrolling
            scroll_resp = session.post(
                f"{BASE_URL.rstrip('/')}/_search/scroll",
                data=json.dumps({"scroll": SCROLL_KEEPALIVE, "scroll_id": scroll_id}),
                timeout=60,
            )
            scroll_resp.raise_for_status()
            data = scroll_resp.json()
            scroll_id = data.get("_scroll_id", scroll_id)  # some clusters rotate IDs mid-scroll
            hits = data.get("hits", {}).get("hits", [])
    finally:
        # try to clear the scroll context; ES appreciates manners
        try:
            session.delete(
                f"{BASE_URL.rstrip('/')}/_search/scroll",
                data=json.dumps({"scroll_id": [scroll_id]}),
                timeout=30,
            )
        except Exception:
            pass  # best-effort cleanup; if it fails, the sky remains stubbornly blue


def get_contracts() -> List[str]:
    contracts = []
    for hit in scroll_hits():
        contract_dict = {
            "contract": hit["_id"],
            "owner": hit["_source"]["currentOwner"],
            "deployer": hit["_source"]["deployer"],
            "timestamp": hit["_source"]["timestamp"],
            "tx_hash": hit["_source"]["deployTxHash"],
        }
        contracts.append(contract_dict)
    return contracts

def main() -> None:
    contracts = get_contracts()
    for hit in contracts:
        # print full hit (including _index, _id, _source, etc.) as NDJSON
        sys.stdout.write(json.dumps(hit, separators=(",", ":")) + "\n")
        sys.stdout.flush()

    print(len(contracts))

if __name__ == "__main__":
    main()