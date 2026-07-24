from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


class SitecustomizeHookLifecycleTests(unittest.TestCase):
    def test_vetting_dependencies_are_ready_before_atexit_shutdown(self) -> None:
        root = Path(__file__).resolve().parents[1]
        capsule = root / "capsules" / "hou_compact_final" / "hou_compact"
        self.assertTrue((capsule / "sitecustomize.py").is_file())

        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            script = directory / "phase_followup_pipeline.py"
            script.write_text("pass\n", encoding="utf-8")
            candidate = directory / "candidate_gaia.csv"
            summary = directory / "candidate_summary.json"
            missing_gaia = directory / "missing_gaia.ecsv"

            environment = os.environ.copy()
            python_path = [str(capsule), str(root / "src")]
            inherited = environment.get("PYTHONPATH")
            if inherited:
                python_path.append(inherited)
            environment["PYTHONPATH"] = os.pathsep.join(python_path)

            completed = subprocess.run(
                [
                    sys.executable,
                    str(script),
                    "prepare",
                    "--gaia-ecsv",
                    str(missing_gaia),
                    "--candidate-gaia",
                    str(candidate),
                    "--summary",
                    str(summary),
                ],
                cwd=root,
                env=environment,
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )

            self.assertNotEqual(completed.returncode, 0)
            self.assertNotIn("can't register atexit after shutdown", completed.stderr)
            receipt_path = directory / "gaia_vetting_safe_error.json"
            self.assertTrue(receipt_path.is_file(), completed.stderr)
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            self.assertEqual(
                receipt["stage"],
                "candidate_quality_error_geometry_enrichment",
            )
            self.assertNotEqual(receipt["stage"], "prepare_hook_initialization")
            self.assertTrue(receipt["candidate_safe"])


if __name__ == "__main__":
    unittest.main()
