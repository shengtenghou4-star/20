from __future__ import annotations

import csv
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from hou_compact import lamost_gaia_form_rv_v2 as module
from hou_compact.lamost_gaia_form_rv import LamostGaiaFormError


class GaiaFormSessionTests(unittest.TestCase):
    def bridge(self, directory: Path, count: int = 6) -> Path:
        path = directory / "bridge.csv"
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(
                handle,
                fieldnames=["source_id", "dr2_source_id", "dr2_bridge_status"],
            )
            writer.writeheader()
            for index in range(count):
                writer.writerow(
                    {
                        "source_id": str(1000000000000000000 + index),
                        "dr2_source_id": str(2000000000000000000 + index),
                        "dr2_bridge_status": "accepted_unique_or_separated_nearest",
                    }
                )
        return path

    @staticmethod
    def fake_base_factory(*, duplicate_obsid: bool = False):
        calls: list[int] = []

        def fake_base(**kwargs):
            bridge_path = kwargs["bridge_input"]
            with bridge_path.open("r", encoding="utf-8", newline="") as handle:
                bridge_rows = list(csv.DictReader(handle))
            calls.append(len(bridge_rows))
            rows_path = kwargs["rows_output"]
            overlap_path = kwargs["overlap_output"]
            rows_path.parent.mkdir(parents=True, exist_ok=True)
            with rows_path.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(
                    handle,
                    fieldnames=[
                        "obsid",
                        "lmjd",
                        "rv",
                        "rv_err",
                        "fibermask",
                        "gaia_source_id",
                        "hou_compact_dr2_source_id",
                        "hou_compact_dr3_source_id",
                    ],
                )
                writer.writeheader()
                for index, row in enumerate(bridge_rows):
                    obsid = "9001" if duplicate_obsid else str(int(row["dr2_source_id"][-6:]) + 1000)
                    writer.writerow(
                        {
                            "obsid": obsid,
                            "lmjd": str(59000 + index),
                            "rv": "10",
                            "rv_err": "1",
                            "fibermask": "0",
                            "gaia_source_id": row["dr2_source_id"],
                            "hou_compact_dr2_source_id": row["dr2_source_id"],
                            "hou_compact_dr3_source_id": row["source_id"],
                        }
                    )
            with overlap_path.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(
                    handle,
                    fieldnames=[
                        "obsid",
                        "lmjd",
                        "hou_compact_dr2_source_id",
                        "hou_compact_dr3_source_id",
                    ],
                )
                writer.writeheader()
                for index, row in enumerate(bridge_rows):
                    obsid = "9001" if duplicate_obsid else str(int(row["dr2_source_id"][-6:]) + 1000)
                    writer.writerow(
                        {
                            "obsid": obsid,
                            "lmjd": str(59000 + index),
                            "hou_compact_dr2_source_id": row["dr2_source_id"],
                            "hou_compact_dr3_source_id": row["source_id"],
                        }
                    )
            private = {
                "status": "success",
                "accepted_bridge_sources": len(bridge_rows),
            }
            safe = {
                "status": "success",
                "candidate_safe": True,
                "accepted_bridge_sources": len(bridge_rows),
                "returned_spectrum_rows": len(bridge_rows),
            }
            kwargs["private_manifest_path"].write_text(json.dumps(private), encoding="utf-8")
            kwargs["safe_summary_path"].write_text(json.dumps(safe), encoding="utf-8")
            return safe

        return calls, fake_base

    def test_five_batch_session_limit_is_enforced_and_outputs_merge(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            calls, fake_base = self.fake_base_factory()
            rows = directory / "rows.csv"
            overlap = directory / "overlap.csv"
            private = directory / "private.json"
            safe = directory / "safe.json"
            with patch.object(module, "acquire_gaia_form_rv", side_effect=fake_base):
                summary = module.acquire_gaia_form_rv_sessioned(
                    bridge_input=self.bridge(directory),
                    rows_output=rows,
                    overlap_output=overlap,
                    private_manifest_path=private,
                    safe_summary_path=safe,
                    batch_size=2,
                    batches_per_session=2,
                )
            self.assertEqual(calls, [4, 2])
            self.assertEqual(summary["session_count"], 2)
            self.assertEqual(summary["returned_spectrum_rows"], 6)
            self.assertEqual(len(list(csv.DictReader(rows.open(encoding="utf-8")))), 6)
            self.assertEqual(len(list(csv.DictReader(overlap.open(encoding="utf-8")))), 6)
            safe_text = safe.read_text(encoding="utf-8")
            self.assertNotIn("2000000000000000000", safe_text)

    def test_duplicate_obsid_across_fresh_sessions_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            _calls, fake_base = self.fake_base_factory(duplicate_obsid=True)
            with patch.object(module, "acquire_gaia_form_rv", side_effect=fake_base):
                with self.assertRaisesRegex(LamostGaiaFormError, "repeats across"):
                    module.acquire_gaia_form_rv_sessioned(
                        bridge_input=self.bridge(directory, count=2),
                        rows_output=directory / "rows.csv",
                        overlap_output=directory / "overlap.csv",
                        private_manifest_path=directory / "private.json",
                        safe_summary_path=directory / "safe.json",
                        batch_size=1,
                        batches_per_session=1,
                    )
            self.assertFalse((directory / "rows.csv").exists())
            self.assertFalse((directory / "overlap.csv").exists())


if __name__ == "__main__":
    unittest.main()
