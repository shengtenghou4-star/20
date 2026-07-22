from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "probe_lamost_search_form.py"
SPEC = importlib.util.spec_from_file_location("probe_lamost_search_form", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class LAMOSTSearchFormParserTests(unittest.TestCase):
    def test_parser_discovers_obsid_and_redacts_hidden_values(self) -> None:
        html = """
        <html><body>
          <form action="/dr8/v1.0/search/query" method="post">
            <input type="hidden" name="csrf_token" value="top-secret-token">
            <textarea name="obsid_list">677502003</textarea>
            <select name="output_format">
              <option value="html">HTML</option>
              <option value="csv" selected>CSV</option>
            </select>
            <input type="checkbox" name="columns" value="rv" checked>
            <button type="submit" name="submit" value="search">Search</button>
          </form>
        </body></html>
        """
        parser = MODULE.SearchFormParser("https://www.lamost.org/dr8/v1.0/search")
        parser.feed(html)
        parser.close()
        self.assertEqual(len(parser.forms), 1)
        form = parser.forms[0]
        self.assertEqual(
            form["action"], "https://www.lamost.org/dr8/v1.0/search/query"
        )
        hidden = form["controls"][0]
        self.assertIsNone(hidden["safe_value"])
        self.assertNotIn("top-secret-token", str(form))
        textarea = form["controls"][1]
        self.assertEqual(textarea["default_length"], len("677502003"))
        self.assertNotIn("677502003", str(form))
        output = form["controls"][2]
        self.assertEqual(output["options"][1]["safe_value"], "csv")

    def test_safe_literal_rejects_free_text_and_sensitive_names(self) -> None:
        safe = MODULE.SearchFormParser._safe_literal
        self.assertEqual(safe("rv", name="columns"), "rv")
        self.assertIsNone(safe("a value with spaces", name="columns"))
        self.assertIsNone(safe("abc123", name="session_token"))


if __name__ == "__main__":
    unittest.main()
