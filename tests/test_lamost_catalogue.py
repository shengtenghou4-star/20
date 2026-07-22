from __future__ import annotations

from io import BytesIO

from hou_compact.lamost_catalogue import (
    discover_catalogue_links,
    extract_catalogue_link_candidates,
)


class FakeResponse:
    status = 200

    def __init__(self, text: str) -> None:
        self._body = text.encode("utf-8")

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self, size: int = -1) -> bytes:
        return BytesIO(self._body).read(size)


def _document() -> str:
    return """
    <html><body>
      <h2>Low Resolution Catalog</h2>
      <span>LAMOST LRS Multiple Epoch Catalog</span>
      <a href="/dr8/v1.0/catalogue/lrs_epoch.csv">CSV</a>
      <button data-url="/download?name=lrs_multiple_epoch">Download</button>
      <a href="/help">Help</a>
    </body></html>
    """


def test_extracts_and_resolves_candidate_links() -> None:
    candidates = extract_catalogue_link_candidates(
        _document(),
        page_url="https://example.org/dr8/v1.0/catalogue",
    )
    values = {row["value"] for row in candidates}
    assert "https://example.org/dr8/v1.0/catalogue/lrs_epoch.csv" in values
    assert "https://example.org/download?name=lrs_multiple_epoch" in values
    assert "https://example.org/help" not in values


def test_live_contract_wrapper_emits_page_receipt() -> None:
    def opener(*args: object, **kwargs: object) -> FakeResponse:
        return FakeResponse(_document())

    result = discover_catalogue_links(
        "https://example.org/dr8/v1.0/catalogue",
        opener=opener,
    )
    assert result["status"] == "pass"
    assert result["candidate_attribute_count"] == 2
    assert result["receipt"]["status"] == 200
    assert len(result["receipt"]["sha256"]) == 64
