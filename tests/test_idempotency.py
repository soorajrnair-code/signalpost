"""
Unit tests for idempotency, diff detection, and temporal updates.
"""

import unittest
from signalpost.models import CompanyProfile, StatusEnvelope, ProvenanceRecord
from signalpost.storage import Storage


class TestIdempotency(unittest.TestCase):
    def setUp(self):
        self.storage = Storage(db_path=":memory:")

    def test_idempotent_identical_saves(self):
        p1 = CompanyProfile(
            organisasjonsnummer="923609016",
            status=StatusEnvelope.AVAILABLE,
            data={"company_details": {"name": "EQUINOR ASA", "employees": 21000}},
            provenance=[ProvenanceRecord("company_details.name", "EQUINOR ASA", "https://brreg.no", "name quote")]
        )
        saved1, changes1 = self.storage.save_profile(p1)
        self.assertEqual(len(changes1), 0)

        # Save again with identical data
        p2 = CompanyProfile(
            organisasjonsnummer="923609016",
            status=StatusEnvelope.AVAILABLE,
            data={"company_details": {"name": "EQUINOR ASA", "employees": 21000}},
            provenance=[ProvenanceRecord("company_details.name", "EQUINOR ASA", "https://brreg.no", "name quote")]
        )
        saved2, changes2 = self.storage.save_profile(p2)
        self.assertEqual(len(changes2), 0)
        self.assertEqual(len(saved2.audit_log), 0)

    def test_delta_detection(self):
        p1 = CompanyProfile(
            organisasjonsnummer="923609016",
            status=StatusEnvelope.AVAILABLE,
            data={"company_details": {"name": "EQUINOR ASA", "employees": 21000}},
            provenance=[ProvenanceRecord("company_details.employees", 21000, "https://brreg.no", "21000 emp")]
        )
        self.storage.save_profile(p1)

        # New profile with changed employee count
        p2 = CompanyProfile(
            organisasjonsnummer="923609016",
            status=StatusEnvelope.AVAILABLE,
            data={"company_details": {"name": "EQUINOR ASA", "employees": 21500}},
            provenance=[ProvenanceRecord("company_details.employees", 21500, "https://brreg.no/new", "21500 emp")]
        )
        saved2, changes2 = self.storage.save_profile(p2)
        self.assertEqual(len(changes2), 1)
        self.assertEqual(changes2[0].field, "company_details.employees")
        self.assertEqual(changes2[0].old_value, 21000)
        self.assertEqual(changes2[0].new_value, 21500)
        self.assertEqual(len(saved2.audit_log), 1)


if __name__ == "__main__":
    unittest.main()
