import hashlib
import importlib.util
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
class PrepareTests(unittest.TestCase):
    def module(self):
        path=Path(__file__).resolve().parents[1]/'scripts/prepare_read_models.py'
        spec=importlib.util.spec_from_file_location('prepare_models',path);mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod);return mod
    def test_fixed_resource_download_and_reuse_without_network(self):
        mod=self.module();sha=hashlib.sha256(b'synthetic').hexdigest();seen=[]
        def fetch(url,timeout):seen.append(url);return io.BytesIO(b'synthetic')
        with tempfile.TemporaryDirectory() as tmp,patch.object(mod,'HASHES',{'embedding':{'model.onnx':sha},'reranker':{'model_fp32.onnx':sha}}):
            mod.prepare(tmp,fetch);self.assertEqual(len(seen),2)
            self.assertIn('/75c43b069aac4d136ba6bc1122f995fedcfd2781/onnx/model_quantized.onnx',seen[0])
            mod.prepare(tmp,lambda *a,**k:self.fail('unexpected network'))
            self.assertTrue((Path(tmp)/'manifest.json').exists())
    def test_bad_download_kept_partial_without_manifest(self):
        mod=self.module()
        with tempfile.TemporaryDirectory() as tmp,patch.object(mod,'HASHES',{'embedding':{'model.onnx':'0'*64}}):
            with self.assertRaises(ValueError):mod.prepare(tmp,lambda *a,**k:io.BytesIO(b'bad'))
            self.assertFalse((Path(tmp)/'manifest.json').exists());self.assertFalse((Path(tmp)/'embedding/model.onnx').exists())
