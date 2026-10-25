"""Cache cleanup must preserve source, runtime and private learning records."""
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec=importlib.util.spec_from_file_location("native_cleanup",Path(__file__).resolve().parents[1]/"scripts/native-cleanup.py")
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)

class CleanupTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        self.protected=["apps/api/main.py","apps/web/package.json","apps/web/.next/BUILD_ID","apps/web/.next/server/page.js",
            "apps/web/node_modules/next/index.js","native-data/data/opentutor.db","native-data/settings.env","native-data/logs/api.log",
            "local-backups/safe.sqlite3",".runtime/node/node.exe","scripts/windows/Launcher.cs"]
        for name in self.protected:
            p=self.root/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(b"preserve")
        for name in module.CACHE_PATHS:
            p=self.root/name;p.mkdir(parents=True,exist_ok=True);(p/"cache.bin").write_bytes(b"cache")
    def test_preview_does_not_delete_and_apply_keeps_essential_files_byte_identical(self):
        preview=module.cleanup(self.root)
        self.assertFalse(preview["applied"]);self.assertEqual(preview["bytes"],len(module.CACHE_PATHS)*5)
        self.assertTrue((self.root/module.CACHE_PATHS[0]/"cache.bin").exists())
        result=module.cleanup(self.root,apply=True);self.assertTrue(result["ok"])
        for name in self.protected:self.assertEqual((self.root/name).read_bytes(),b"preserve")
        for name in module.CACHE_PATHS:self.assertFalse((self.root/name).exists())
        self.assertEqual(module.cleanup(self.root,apply=True)["bytes"],0)
    def test_filesystem_links_are_rejected_before_recursion(self):
        cache=self.root/module.CACHE_PATHS[0]
        with patch.object(module,"redirected",side_effect=lambda p: p==cache):
            result=module.cleanup(self.root,apply=True)
        self.assertFalse(result["ok"]);self.assertTrue((cache/"cache.bin").exists())
        self.assertEqual((self.root/"native-data/data/opentutor.db").read_bytes(),b"preserve")
    def test_unrecognized_project_and_unapproved_targets_are_rejected(self):
        with self.assertRaises(ValueError):module.cleanup(self.root/"native-data",apply=True)
        with self.assertRaises(ValueError):module.inspect_cache(self.root,"native-data")
        with self.assertRaises(ValueError):module.inspect_cache(self.root,"../outside")

if __name__=="__main__":unittest.main()
