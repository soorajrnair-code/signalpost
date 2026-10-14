"""
End-to-end unit tests for SignalPostAgent.
"""

import unittest
from signalpost.agent import SignalPostAgent
from signalpost.models import StatusEnvelope
from signalpost.storage import Storage


class TestAgent(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.storage = Storage(db_path=":memory:")
        cls.agent = SignalPostAgent(storage=cls.storage)

    def test_lookup_available_entity(self):
        profile = self.agent.research_company("923609016", fetch_web=False)
        self.assertEqual(profile.status, StatusEnvelope.AVAILABLE)
        self.assertEqual(profile.data["company_details"]["name"], "EQUINOR ASA")
        self.assertTrue(len(profile.provenance) > 10)
        self.assertIsNotNone(profile.explanations.executive_summary)

        # Test Builderr minimal output contract compliance
        canonical = profile.to_canonical_envelope(run_id="test-run-001", requests=4, runtime_ms=120)
        self.assertEqual(canonical["organisation_number"], "923609016")
        self.assertEqual(canonical["run"]["terminal_status"], "completed")
        self.assertTrue(len(canonical["claims"]) > 10)
        self.assertTrue(len(canonical["evidence"]) > 10)
        self.assertEqual(canonical["operations"]["requests"], 4)
        self.assertEqual(canonical["operations"]["third_party_cost_usd"], 0.0)


    def test_lookup_nonexistent_entity(self):
        profile = self.agent.research_company("999999999", fetch_web=False)
        self.assertEqual(profile.status, StatusEnvelope.NOT_AVAILABLE)
        self.assertIn("not_available", profile.explanations.status_envelope_reasoning)

    def test_lookup_ambiguous_name(self):
        profile = self.agent.research_company("Nordic Tech", fetch_web=False)
        self.assertEqual(profile.status, StatusEnvelope.AMBIGUOUS)
        self.assertIn("ambiguous", profile.explanations.disambiguation_reasoning.lower())

    def test_lookup_empty_query(self):
        profile = self.agent.research_company("", fetch_web=False)
        self.assertEqual(profile.status, StatusEnvelope.FAILED)


if __name__ == "__main__":
    unittest.main()
