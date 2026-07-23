from __future__ import annotations

import importlib.util
from pathlib import Path


_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "probe_lamost_search_form_contract.py"
_SPEC = importlib.util.spec_from_file_location("probe_lamost_search_form_contract", _SCRIPT)
assert _SPEC is not None and _SPEC.loader is not None
_MODULE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)

extract_form_contract = _MODULE.extract_form_contract
extract_keyword_snippets = _MODULE.extract_keyword_snippets


def test_form_contract_retains_relevant_defaults() -> None:
    html = """<!doctype html><html><body>
<form id="search" method="post" action="/dr8/v2.0/q" enctype="multipart/form-data">
  <input type="hidden" name="sForm" value="search">
  <input type="radio" name="pos.type" value="proximity" checked>
  <textarea name="pos.radecTextarea">10,20,2</textarea>
  <select name="output.fmt">
    <option value="html" selected>HTML</option>
    <option value="csv">CSV</option>
  </select>
  <input type="checkbox" name="output.combined.obsid" value="obsid" checked>
  <input type="checkbox" name="output.combined.rv" value="rv">
  <input type="submit" name="sBtn" value="Search">
</form>
<script src="/dr8/v2.0/u/js/combined-search3.js?2"></script>
</body></html>"""
    contract = extract_form_contract(html, "https://www.lamost.org/dr8/v2.0/search")
    assert contract["form_count"] == 1
    form = contract["forms"][0]
    assert form["action"] == "https://www.lamost.org/dr8/v2.0/q"
    assert form["method"] == "post"
    controls = {control["name"]: control for control in form["controls"]}
    assert controls["sForm"]["value"] == "search"
    assert controls["pos.type"]["checked"] is True
    assert controls["pos.radecTextarea"]["value"] == "10,20,2"
    assert controls["output.fmt"]["selected_options"] == [
        {"value": "html", "selected": True, "disabled": False, "text": "HTML"}
    ]
    assert controls["output.combined.obsid"]["checked"] is True
    assert controls["output.combined.rv"]["checked"] is False
    assert contract["script_urls"] == [
        "https://www.lamost.org/dr8/v2.0/u/js/combined-search3.js?2"
    ]


def test_keyword_snippets_are_bounded_and_deduplicated() -> None:
    javascript = """
function submitSearch(){
  const body = new FormData(document.getElementById('sForm'));
  return $.ajax({url:'/dr8/v2.0/q', method:'POST', data:body});
}
"""
    snippets = extract_keyword_snippets(javascript, radius=40, maximum_snippets=20)
    assert snippets
    assert len(snippets) <= 20
    assert any(item["keyword"] == "formdata" for item in snippets)
    assert any("/dr8/v2.0/q" in item["snippet"] for item in snippets)
    assert all(len(item["snippet"]) <= 2 * 40 + 32 for item in snippets)


def test_irrelevant_unchecked_fields_are_not_persisted() -> None:
    html = """<form action='/q'>
<input type='text' name='stellar.teff_min' value='3500'>
<input type='checkbox' name='output.combined.rv' value='rv'>
<input type='checkbox' name='output.combined.obsid' value='obsid' checked>
</form>"""
    contract = extract_form_contract(html, "https://www.lamost.org/dr8/v2.0/search")
    names = {control["name"] for control in contract["forms"][0]["controls"]}
    assert "stellar.teff_min" not in names
    assert "output.combined.rv" in names
    assert "output.combined.obsid" in names
