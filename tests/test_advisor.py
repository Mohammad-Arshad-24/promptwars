import os
import unittest
from unittest.mock import patch
from lablink.advisor import match_project
from lablink.catalog import CATALOG

class AdvisorTests(unittest.TestCase):
    @patch.dict(os.environ, {"VERTEX_MODEL": "test-model"})
    @patch("lablink.advisor.generate")
    def test_only_real_unique_units_reach_student(self, generate):
        generate.return_value = [{"id":"INVALID","reason":"Unknown"},
                                 {"id":"CS-03","reason":"The CUDA GPU suits model training."},
                                 {"id":"CS-03","reason":"Duplicate"}]
        result = match_project("vision model")
        self.assertEqual(result["mode"], "Gemini")
        self.assertEqual([m["id"] for m in result["matches"]], ["CS-03"])
        generate.assert_called_once_with("vision model", "test-model", CATALOG)

    @patch.dict(os.environ, {"VERTEX_MODEL":"test-model"})
    @patch("lablink.advisor.generate", side_effect=TimeoutError)
    def test_unavailable_provider_and_exhausted_global_budget(self, generate):
        for allowed in [True, False]:
            result = match_project("CUDA", allow_model=allowed)
            self.assertIn("fallback", result["mode"])
            self.assertTrue(result["matches"])
        self.assertEqual(generate.call_count, 1)

