import hashlib
import importlib.util
import json
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest.mock import patch


class PackageTests(unittest.TestCase):
    def test_source_bundle_keeps_checks_services_and_demo(self):
        root=Path(__file__).resolve().parents[1]
        spec=importlib.util.spec_from_file_location('alpha_source_package',root/'scripts/package-alpha.py')
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as temporary:
            archive=Path(temporary)/'source.tar.gz'
            manifest=module.package(root,archive,version='0.1.0-alpha.3')
            required={'tests/test_engineering.py','tests/test_control.py','tests/lead_gateway.test.mjs',
                      'tests/fixtures/published-demo/receipt.json','scripts/validate-poc.py',
                      '.github/workflows/product-validation.yml','controller/autonomous-development.timer'}
            self.assertTrue(required.issubset(manifest['files']))
            with tarfile.open(archive) as bundle:
                for name,digest in manifest['files'].items():
                    self.assertEqual(hashlib.sha256(bundle.extractfile('autonomous-development-alpha/'+name).read()).hexdigest(),digest)

    def test_archive_is_reproducible_and_excludes_unlisted_files(self):
        spec = importlib.util.spec_from_file_location('alpha_package', Path(__file__).parents[1] / 'scripts/package-alpha.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            controller, worker = root / 'controller', root / 'worker'
            for directory, names in ((controller, module.CONTROLLER), (worker, module.WORKER)):
                for name in names:
                    path = directory / name
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text(name + '\n')
                (directory / 'auth.json').write_text('must never ship')
            a, b = root / 'a.tar.gz', root / 'b.tar.gz'
            with patch.object(module, 'ROOT', controller), patch.object(module, 'source_revision', return_value={'commit': 'a' * 40, 'dirty': False}):
                manifest = module.package(worker, a)
                module.package(worker, b)
                with self.assertRaises(ValueError):
                    module.package(worker, b, 'latest')
            self.assertEqual(a.read_bytes(), b.read_bytes())
            with tarfile.open(a) as archive:
                prefix = 'autonomous-development-alpha/'
                self.assertEqual(set(archive.getnames()), {prefix + name for name in manifest['files']} | {prefix + 'MANIFEST.json'})
                saved = json.load(archive.extractfile(prefix + 'MANIFEST.json'))
                self.assertEqual(saved, manifest)
                for name, digest in manifest['files'].items():
                    self.assertEqual(hashlib.sha256(archive.extractfile(prefix + name).read()).hexdigest(), digest)
                self.assertEqual(archive.extractfile(prefix + 'README.md').read(), b'README.md\n')
