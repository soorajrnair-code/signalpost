"""
Tests for Norwegian Organization Number Modulo 11 Validator.
"""

import unittest
from signalpost.validator import (
    validate_orgnr,
    normalize_orgnr,
    calculate_mod11_checksum,
    is_likely_orgnr
)


class TestValidator(unittest.TestCase):
    def test_valid_orgnr(self):
        # Known real Norwegian enterprises
        valid_numbers = [
            "923609016",  # Equinor ASA
            "982463718",  # Telenor ASA
            "984851006",  # DNB Bank ASA
            "971032081",  # Norsk Hydro ASA
            "973861883"   # Equinor CCB Sotra
        ]
        for num in valid_numbers:
            is_valid, msg = validate_orgnr(num)
            self.assertTrue(is_valid, f"Failed for {num}: {msg}")

    def test_normalization(self):
        self.assertEqual(normalize_orgnr("NO 923 609 016 MVA"), "923609016")
        self.assertEqual(normalize_orgnr("923.609.016"), "923609016")
        self.assertEqual(normalize_orgnr("NO-982463718"), "982463718")

    def test_invalid_checksum(self):
        # Last digit changed
        is_valid, msg = validate_orgnr("923609017")
        self.assertFalse(is_valid)
        self.assertIn("Checksum mismatch", msg)

    def test_invalid_length(self):
        is_valid, msg = validate_orgnr("12345678")
        self.assertFalse(is_valid)
        self.assertIn("Invalid length", msg)

    def test_name_query(self):
        is_valid, msg = validate_orgnr("Equinor ASA")
        self.assertFalse(is_valid)
        self.assertIn("non-numeric", msg)


if __name__ == "__main__":
    unittest.main()
