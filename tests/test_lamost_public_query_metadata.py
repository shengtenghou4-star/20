from __future__ import annotations

import importlib.util
from pathlib import Path


_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "probe_lamost_public_query_metadata.py"
_SPEC = importlib.util.spec_from_file_location("probe_lamost_public_query_metadata", _SCRIPT)
assert _SPEC is not None and _SPEC.loader is not None
_MODULE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)

extract_openapi_contract = _MODULE.extract_openapi_contract
extract_search_contract = _MODULE.extract_search_contract


def test_extract_openapi_query_and_schema_blocks() -> None:
    text = """openapi: 3.0.0
paths:
  /openapi/{dr_version}/{sub_version}/query/{table_name}:
    post:
      requestBody:
        content:
          application/json:
            schema:
              $ref: '#/components/schemas/TableQuery'
  /openapi/other:
    get: {}
components:
  schemas:
    TableQuery:
      type: object
      properties:
        constraints:
          type: array
    ColumnConstraint:
      type: object
      properties:
        column:
          type: string
    PositionConstraint:
      oneOf:
        - $ref: '#/components/schemas/ConePosition'
    ConePosition:
      type: object
      properties:
        ra:
          type: number
    HTTPError:
      type: object
"""
    contract = extract_openapi_contract(text)
    assert contract["query_table_path_found"] is True
    path_text = "\n".join(contract["query_table_path_block"])
    assert "requestBody" in path_text
    assert "TableQuery" in path_text
    schemas = contract["schemas"]
    assert "constraints" in "\n".join(schemas["TableQuery"])
    assert "column" in "\n".join(schemas["ColumnConstraint"])
    assert "ConePosition" in "\n".join(schemas["PositionConstraint"])
    assert contract["schema_blocks_found"]["RectanglePosition"] is False


def test_extract_search_form_fields_and_same_origin_endpoints() -> None:
    html = """<!doctype html>
<html><body>
<form id="search" method="post" action="/dr8/v2.0/search/submit">
  <input name="gaia_source_id" type="text">
  <input name="rv" type="checkbox">
  <select name="output_format"><option>csv</option></select>
  <button name="submit" type="submit">Go</button>
</form>
<script src="/static/search.js"></script>
<script>
fetch('/dr8/v2.0/search/result');
const external = 'https://other.example/api';
</script>
</body></html>"""
    contract = extract_search_contract(
        html,
        "https://www.lamost.org/dr8/v2.0/search",
    )
    assert contract["form_count"] == 1
    form = contract["forms"][0]
    assert form["method"] == "post"
    assert form["action"] == "https://www.lamost.org/dr8/v2.0/search/submit"
    names = {field["name"] for field in form["fields"]}
    assert names == {"gaia_source_id", "rv", "output_format", "submit"}
    assert "https://www.lamost.org/static/search.js" in contract["script_urls"]
    assert "https://www.lamost.org/dr8/v2.0/search/result" in contract[
        "endpoint_candidates"
    ]
    assert all("other.example" not in item for item in contract["endpoint_candidates"])


def test_metadata_contract_contains_no_catalogue_values() -> None:
    html = "<form action='/search'><input name='gaia_source_id'></form>"
    contract = extract_search_contract(html, "https://www.lamost.org/dr8/v2.0/search")
    serialized = str(contract)
    assert "2676113965163724160" not in serialized
    assert "rv_err" not in serialized
