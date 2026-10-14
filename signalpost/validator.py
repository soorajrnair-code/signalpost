"""
Norwegian Organization Number (organisasjonsnummer) Validation & Normalization.

Norwegian organization numbers consist of 9 digits where the last digit is a
control digit calculated using the Modulo 11 algorithm with weights [3, 2, 7, 6, 5, 4, 3, 2].
"""

import re
from typing import Optional, Tuple

WEIGHTS = [3, 2, 7, 6, 5, 4, 3, 2]


def normalize_orgnr(raw_input: str) -> str:
    """
    Normalizes a raw company input by stripping prefix 'NO', spaces, dots, hyphens, and 'MVA'.
    Example: 'NO 923.609.016 MVA' -> '923609016'
    """
    if not raw_input:
        return ""
    cleaned = raw_input.strip()
    # Remove leading 'NO' or 'NO-'
    cleaned = re.sub(r'^(NO\s*[-:]?\s*)', '', cleaned, flags=re.IGNORECASE)
    # Remove trailing 'MVA'
    cleaned = re.sub(r'\s*MVA$', '', cleaned, flags=re.IGNORECASE)
    # Remove non-alphanumeric except keep text if it's a name
    digits_only = re.sub(r'[\s\.\-_]', '', cleaned)
    if digits_only.isdigit() and len(digits_only) == 9:
        return digits_only
    return cleaned.strip()


def calculate_mod11_checksum(first_8_digits: str) -> Optional[int]:
    """
    Calculates the 9th control digit for the first 8 digits using Modulo 11.
    Returns:
        int (0-9) if valid control digit can be formed,
        None if remainder is 1 (in which case no valid control digit exists).
    """
    if len(first_8_digits) != 8 or not first_8_digits.isdigit():
        return None
    
    total = sum(int(digit) * weight for digit, weight in zip(first_8_digits, WEIGHTS))
    remainder = total % 11
    
    if remainder == 0:
        return 0
    elif remainder == 1:
        # A control digit of 10 is impossible in a single digit base-10 number
        return None
    else:
        return 11 - remainder


def validate_orgnr(orgnr: str) -> Tuple[bool, str]:
    """
    Validates a Norwegian organization number.
    Returns:
        (is_valid: bool, reason: str)
    """
    normalized = normalize_orgnr(orgnr)
    
    if not normalized:
        return False, "Input is empty."
    
    if not normalized.isdigit():
        return False, f"Input contains non-numeric characters: '{normalized}'. Treat as company name query."
    
    if len(normalized) != 9:
        return False, f"Invalid length: Expected exactly 9 digits, got {len(normalized)}."
    
    expected_control = calculate_mod11_checksum(normalized[:8])
    if expected_control is None:
        return False, "Invalid number: Modulo 11 remainder yielded 1 (no valid control digit)."
    
    actual_control = int(normalized[8])
    if actual_control != expected_control:
        return False, f"Checksum mismatch: Expected control digit {expected_control}, but found {actual_control}."
    
    return True, "Valid Norwegian organization number (Modulo 11 verified)."


def is_likely_orgnr(query: str) -> bool:
    """
    Quick check to see if an input looks like an organization number rather than a company name.
    """
    normalized = normalize_orgnr(query)
    return normalized.isdigit() and len(normalized) == 9
