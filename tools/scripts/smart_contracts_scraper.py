#!/usr/bin/env python3
"""
Smart Contract Scraper for MultiversX Mainnet

This script fetches smart contracts from MultiversX mainnet, retrieves their WASM bytecode,
converts to WAT format, and searches for specific function names.
"""

import requests
import base64
import subprocess
import json
import os
import tempfile
import re
from typing import List, Dict, Set, Optional, Any, Tuple
from pathlib import Path
from tools.scripts.es_scroller import get_contracts

# Configuration
API_BASE_URL = "https://api.multiversx.com"
APPLICATIONS_ENDPOINT = f"{API_BASE_URL}/applications"
ACCOUNTS_ENDPOINT = f"{API_BASE_URL}/accounts"

# Maximum number of contracts to process
MAX_CONTRACTS = 20000

# Pagination size for API requests
PAGE_SIZE = 100

# Function names to search for in WAT files
SEARCH_FUNCTIONS = [
    "updateAndGetTokensForGivenPositionWithSafePrice",
    "updateAndGetSafePrice",
    "getLpTokensSafePriceByDefaultOffset",
    "getLpTokensSafePriceByRoundOffset",
    "getLpTokensSafePriceByTimestampOffset",
    "getLpTokensSafePrice",
    "getSafePriceByDefaultOffset",
    "getSafePriceByRoundOffset",
    "getSafePriceByTimestampOffset"
    "getSafePrice",
    "getPriceObservation",
    "getSafePriceCurrentIndex"
]

# Output file path
OUTPUT_FILE = Path(__file__).parent / "contract_scan_results.json"


def fetch_contract_bytecode(contract_address: str) -> Tuple[Optional[bytes], Optional[str]]:
    """
    Fetch WASM bytecode for a specific contract address.
    
    Args:
        contract_address: The smart contract address
        
    Returns:
        Tuple of (bytecode bytes, code_hash) or (None, None) if not found
    """
    try:
        url = f"{ACCOUNTS_ENDPOINT}/{contract_address}"
        response = requests.get(url, timeout=30)
        response.raise_for_status()
        
        data = response.json()
        
        # Check if contract has code
        if "code" not in data or not data["code"]:
            return None, None
        
        # Decode hex bytecode
        bytecode = bytes.fromhex(data["code"])
        code_hash = data.get("codeHash", "")
        
        return bytecode, code_hash
        
    except requests.RequestException as e:
        print(f"  Error fetching bytecode for {contract_address}: {e}")
        return None, None
    except Exception as e:
        print(f"  Error decoding bytecode for {contract_address}: {e}")
        return None, None


def convert_wasm_to_wat(wasm_bytecode: bytes) -> Optional[str]:
    """
    Convert WASM bytecode to WAT (WebAssembly Text) format using wasm2wat.
    
    Args:
        wasm_bytecode: The WASM bytecode as bytes
        
    Returns:
        WAT text content or None if conversion fails
    """
    # Create temporary files for WASM and WAT
    with tempfile.NamedTemporaryFile(suffix=".wasm", delete=False) as wasm_file:
        wasm_file.write(wasm_bytecode)
        wasm_path = wasm_file.name
    
    wat_path = wasm_path.replace(".wasm", ".wat")
    
    try:
        # Run wasm2wat command
        result = subprocess.run(
            ["wasm2wat", wasm_path, "-o", wat_path],
            capture_output=True,
            text=True,
            timeout=30
        )
        
        if result.returncode != 0:
            print(f"  wasm2wat conversion failed: {result.stderr}")
            return None
        
        # Read WAT file content
        with open(wat_path, "r", encoding="utf-8") as wat_file:
            wat_content = wat_file.read()
        
        return wat_content
        
    except subprocess.TimeoutExpired:
        print("  wasm2wat conversion timed out")
        return None
    except FileNotFoundError:
        print("  Error: wasm2wat tool not found. Please install WABT (WebAssembly Binary Toolkit)")
        return None
    except Exception as e:
        print(f"  Error during WASM to WAT conversion: {e}")
        return None
    finally:
        # Cleanup temporary files
        if os.path.exists(wasm_path):
            os.remove(wasm_path)
        if os.path.exists(wat_path):
            os.remove(wat_path)


def search_functions_in_wat(wat_content: str, function_names: List[str]) -> Set[str]:
    """
    Search for function names in WAT content, particularly in data sections.
    
    Args:
        wat_content: The WAT text content
        function_names: List of function names to search for
        
    Returns:
        Set of matched function names
    """
    matched_functions = set()
    
    for function_name in function_names:
        # Search for function name in the WAT content
        # Look for it in data sections, export names, or function names
        pattern = re.escape(function_name)
        
        if re.search(pattern, wat_content, re.IGNORECASE):
            matched_functions.add(function_name)
    
    return matched_functions


def process_contract(contract_data: Dict[str, Any], function_names: List[str]) -> Optional[Dict[str, Any]]:
    """
    Process a single contract: fetch bytecode, convert to WAT, and search for functions.
    
    Args:
        contract_data: Contract information from API
        function_names: List of function names to search for
        
    Returns:
        Dictionary with contract address and matched functions, or None if no matches
    """
    contract_address = contract_data.get("contract", "")
    
    if not contract_address:
        return None
    
    # Fetch bytecode
    bytecode, code_hash = fetch_contract_bytecode(contract_address)
    
    if not bytecode:
        return None
    
    # Convert to WAT
    wat_content = convert_wasm_to_wat(bytecode)
    
    if not wat_content:
        return None
    
    # Search for functions
    matched_functions = search_functions_in_wat(wat_content, function_names)
    
    if matched_functions:
        return {
            "address": contract_address,
            "matched_functions": sorted(list(matched_functions)),
            "code_hash": code_hash,
            "owner": contract_data.get("owner", ""),
            "deployer": contract_data.get("deployer", "")
        }
    
    return None


def main():
    """
    Main execution function.
    """
    print("=" * 70)
    print("Smart Contract Scraper for MultiversX Mainnet")
    print("=" * 70)
    print(f"Searching for functions: {', '.join(SEARCH_FUNCTIONS)}")
    print("=" * 70)
    
    # Step 1: Fetch all contract addresses
    contracts = get_contracts()
    
    if not contracts:
        print("No contracts found. Exiting.")
        return
    
    # Step 2: Process each contract
    print(f"\nProcessing {len(contracts)} contracts...")
    matched_contracts = []
    total_scanned = 0
    
    for i, contract_data in enumerate(contracts, 1):
        contract_address = contract_data.get("contract", "unknown")
        print(f"\n[{i}/{len(contracts)}] Processing {contract_address}...")
        
        result = process_contract(contract_data, SEARCH_FUNCTIONS)
        total_scanned += 1
        
        if result:
            matched_contracts.append(result)
            print(f"  ✓ Match found! Functions: {', '.join(result['matched_functions'])}")
        else:
            print(f"  - No matches or unable to process")
    
    # Step 3: Save results
    print("\n" + "=" * 70)
    print("Saving results...")
    
    output_data = {
        "search_functions": SEARCH_FUNCTIONS,
        "contracts": matched_contracts,
        "total_scanned": total_scanned,
        "total_matched": len(matched_contracts)
    }
    
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(output_data, f, indent=2)
    
    print(f"Results saved to: {OUTPUT_FILE}")
    print("=" * 70)
    print(f"Summary:")
    print(f"  Total contracts scanned: {total_scanned}")
    print(f"  Contracts with matches: {len(matched_contracts)}")
    print(f"  Match rate: {len(matched_contracts)/total_scanned*100:.2f}%")
    print("=" * 70)


if __name__ == "__main__":
    main()

