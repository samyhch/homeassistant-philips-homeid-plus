"""Release artifacts preserve licenses and reject inconsistent version tags."""

import importlib.util
from pathlib import Path
import tempfile
import unittest
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("build_release", ROOT / "scripts" / "build_release.py")
release = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release)


class ReleaseTests(unittest.TestCase):
    def test_wrong_tag_does_not_create_archive(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "integration.zip"
            with self.assertRaises(ValueError):
                release.build_release("v999.0.0", target)
            self.assertFalse(target.exists())

    def test_archive_has_manifest_sources_and_required_notices(self):
        import json

        version = json.loads((release.COMPONENT / "manifest.json").read_text())["version"]
        with tempfile.TemporaryDirectory() as directory:
            target = release.build_release(f"v{version}", Path(directory) / "integration.zip")
            with ZipFile(target) as archive:
                names = archive.namelist()
                for name in ("manifest.json", "__init__.py", "LICENSE", "NOTICE.md"):
                    self.assertIn(name, names)
                self.assertFalse(any("__pycache__" in name or name.endswith(".pyc") for name in names))
                self.assertEqual(archive.read("NOTICE.md"), (ROOT / "NOTICE.md").read_bytes())
