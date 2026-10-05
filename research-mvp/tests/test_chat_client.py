import importlib.util
from pathlib import Path
import tempfile
import unittest

class ClientTests(unittest.TestCase):
    def module(self):
        path=Path(__file__).resolve().parents[1]/'scripts/chat_gateway.py'
        spec=importlib.util.spec_from_file_location('chat_client',path)
        mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
        return mod
    def test_token_created_private_stable_and_insecure_token_rejected(self):
        mod=self.module()
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'token';a=mod.local_token(path,create=True)
            self.assertEqual(a,mod.local_token(path));self.assertEqual(path.stat().st_mode&0o777,0o600)
            path.chmod(0o644)
            with self.assertRaises(ValueError):mod.local_token(path)
    def test_json_and_jsonl_import_inputs(self):
        mod=self.module()
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'events.json';path.write_text('[{"scope":"a","event":{}}]')
            self.assertEqual(len(list(mod.load_messages(path))),1)
            path.write_text('{"scope":"a","event":{}}\n{"scope":"b","event":{}}\n')
            self.assertEqual(len(list(mod.load_messages(path))),2)

if __name__=='__main__':unittest.main()
