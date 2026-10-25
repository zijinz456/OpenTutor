"""First-run distribution initialization must never inherit or replace private state."""
import importlib.util
from pathlib import Path
import tempfile
import unittest
from dotenv import dotenv_values

spec=importlib.util.spec_from_file_location("native_init",Path(__file__).resolve().parents[1]/"scripts/native-init.py")
native_init=importlib.util.module_from_spec(spec);spec.loader.exec_module(native_init)

class FirstRunTests(unittest.TestCase):
 def make_root(self,parent,name):
  root=Path(parent)/name;(root/"apps/api").mkdir(parents=True);(root/"apps/api/main.py").touch();return root
 def test_generates_empty_provider_keys_and_paths_for_this_installation(self):
  with tempfile.TemporaryDirectory() as folder:
   root=self.make_root(folder,"教学 空格 ' example")
   self.assertTrue(native_init.initialize(root));values=dotenv_values(root/"native-data/settings.env")
   for name in ("OPENAI_API_KEY","ANTHROPIC_API_KEY","DEEPSEEK_API_KEY","CUSTOM_LLM_API_KEY"):
    self.assertEqual(values[name],"")
   self.assertEqual(values["UPLOAD_DIR"],(root/"native-data/uploads").as_posix())
   self.assertEqual(values["DATABASE_URL"],"sqlite+aiosqlite:///"+(root/"native-data/data/opentutor.db").as_posix())
   self.assertFalse((root/"native-data/data/opentutor.db").exists())
   self.assertEqual(values["CODE_SANDBOX_BACKEND"],"disabled")
   self.assertEqual(values["APP_AUTO_SEED_DEMO"],"false")
 def test_never_replaces_existing_keys_or_settings(self):
  with tempfile.TemporaryDirectory() as folder:
   root=self.make_root(folder,"first");native_init.initialize(root)
   file=root/"native-data/settings.env";original=file.read_bytes()
   self.assertFalse(native_init.initialize(root));self.assertEqual(file.read_bytes(),original)
 def test_installs_have_different_signing_and_encryption_keys(self):
  with tempfile.TemporaryDirectory() as folder:
   one=self.make_root(folder,"one");two=self.make_root(folder,"two")
   native_init.initialize(one);native_init.initialize(two)
   a=dotenv_values(one/"native-data/settings.env");b=dotenv_values(two/"native-data/settings.env")
   for key in ("JWT_SECRET_KEY","ENCRYPTION_KEY"):self.assertNotEqual(a[key],b[key])
 def test_refuses_non_application_directory(self):
  with tempfile.TemporaryDirectory() as folder:
   with self.assertRaises(ValueError):native_init.initialize(Path(folder))
   self.assertFalse((Path(folder)/"native-data").exists())
