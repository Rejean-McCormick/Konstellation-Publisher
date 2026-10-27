from __future__ import annotations

import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import publisher_safety as safety
import deploy_remote as remote


def base_checkout(root: Path, version='1.0.0-rc.2'):
    for r in safety.REQUIRED_FILES:
        path = root/r
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text('x',encoding='utf-8')
    (root/'package.json').write_text(json.dumps({'name':'konstellation','version':version, 'scripts':{'build':'astro build','start':'node server/index.mjs','release:check':'node scripts/release-check.mjs --execute'}}))
    (root/'package-lock.json').write_text(json.dumps({'name':'konstellation','version':version,'packages':{'':{'name':'konstellation','version':version}}}))
    (root/'server'/'safe.mjs').write_text('export default true')
    return root


def make_tgz(path:Path, files:dict[str,bytes]):
    with tarfile.open(path,'w:gz') as tf:
        for name, content in files.items():
            meta=tarfile.TarInfo(name)
            meta.size=len(content)
            tf.addfile(meta,io.BytesIO(content))


class SafetyTests(unittest.TestCase):
    def test_reference_checkout_and_archive(self):
        with tempfile.TemporaryDirectory() as td:
            base = base_checkout(Path(td)/'konstellation')
            info=safety.audit_checkout(base)
            self.assertEqual(info['version'],'1.0.0-rc.2')
            tar=Path(td)/'out.tar.gz'
            summary=safety.build_code_tar(base,tar)
            self.assertGreater(summary['included_files'],5)
            with tarfile.open(tar) as tf:
                names=tf.getnames()
            self.assertIn('src/pages/index.astro',names)
            self.assertIn('package-lock.json',names)
            self.assertNotIn('reports/old.txt',names)

    def test_lockfile_missing_and_mismatch(self):
        with tempfile.TemporaryDirectory() as td:
            base=base_checkout(Path(td))
            (base/'package-lock.json').unlink()
            with self.assertRaises(safety.PublicationBlocked):safety.audit_checkout(base)
            base_checkout(base)
            doc=json.loads((base/'package-lock.json').read_text())
            doc['version']='0.5.0'
            (base/'package-lock.json').write_text(json.dumps(doc))
            with self.assertRaises(safety.PublicationBlocked):safety.audit_checkout(base)
            base_checkout(base,'0.5.0')
            with self.assertRaises(safety.PublicationBlocked):safety.audit_checkout(base)

    def test_sensitive_file_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            base=base_checkout(Path(td))
            (base/'server'/'.env.production').write_text('secret=fake')
            with self.assertRaises(safety.PublicationBlocked):
                safety.build_code_tar(base,Path(td)/'blocked.tgz')
            (base/'server'/'.env.production').unlink()
            (base/'src'/'credentials.local.json').write_text('{}')
            with self.assertRaises(safety.PublicationBlocked):
                safety.build_code_tar(base,Path(td)/'blocked.tgz')

    def test_symlink_source_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            base=base_checkout(Path(td))
            try:(base/'src'/'escape.txt').symlink_to(base/'package.json')
            except (OSError,NotImplementedError):self.skipTest('symlink not permitted on host')
            with self.assertRaises(safety.PublicationBlocked):
                safety.build_code_tar(base,Path(td)/'blocked.tgz')

    def test_unapproved_content_or_live_publish_never_allowed(self):
        for pack, lenses in [('test.json',''),('', 'lenses'),('test.json','lenses')]:
            with self.assertRaises(safety.PublicationBlocked):
                safety.assert_no_unqualified_content(pack,lenses)
        with self.assertRaises(safety.PublicationBlocked):safety.assert_live_deploy_permitted()

    def test_remote_archive_digests_and_refus(self):
        with tempfile.TemporaryDirectory() as td:
            d=Path(td)
            make_tgz(d/'code.tar.gz',{'package.json':b'{}'})
            make_tgz(d/'content.tar.gz',{})
            manifest={'schema':'konstellation-publisher/v2','release_id':'20261027-080600',
                      'deployment_profile':'public','pack_included':False,'lenses_included':False,
                      'code_sha256':remote._digest_file(d/'code.tar.gz'),
                      'content_sha256':remote._digest_file(d/'content.tar.gz')}
            (d/'manifest.json').write_text(json.dumps(manifest))
            result=remote.verify_bundle(d,'20261027-080600')
            self.assertEqual(result['deployment_profile'],'public')
            with patch.object(remote,'run',side_effect=AssertionError('MUST NOT EXECUTE')):
                with patch.object(sys,'stdin',io.StringIO(json.dumps({'bundle_dir':str(d),'release_id':'20261027-080600'}))):
                    with self.assertRaisesRegex(RuntimeError,'PUBLISH_BLOCKED'):
                        remote.main()
            (d/'code.tar.gz').write_bytes(b'tampered')
            with self.assertRaisesRegex(RuntimeError,'Empreinte'):
                remote.verify_bundle(d,'20261027-080600')

    def test_remote_blocks_old_schema_and_unsafe_archive(self):
        with tempfile.TemporaryDirectory() as td:
            d=Path(td)
            make_tgz(d/'code.tar.gz',{'../escape':b'a'})
            make_tgz(d/'content.tar.gz',{})
            manifest={'schema':'konstellation-publisher/v2','release_id':'20261027-080600',
                      'deployment_profile':'public','pack_included':False,'lenses_included':False,
                      'code_sha256':remote._digest_file(d/'code.tar.gz'),
                      'content_sha256':remote._digest_file(d/'content.tar.gz')}
            (d/'manifest.json').write_text(json.dumps(manifest))
            with self.assertRaisesRegex(RuntimeError,'archive interdite'):
                remote.verify_bundle(d,'20261027-080600')
            manifest['schema']='konstellation-publisher/v1'
            (d/'manifest.json').write_text(json.dumps(manifest))
            with self.assertRaisesRegex(RuntimeError,'schema/release'):
                remote.verify_bundle(d,'20261027-080600')

    def test_remote_rejects_nonempty_content_even_with_matching_hash(self):
        with tempfile.TemporaryDirectory() as td:
            d=Path(td)
            make_tgz(d/'code.tar.gz',{'package.json':b'{}'})
            make_tgz(d/'content.tar.gz',{'pack.json':b'{"private":true}'})
            manifest={'schema':'konstellation-publisher/v2','release_id':'20261027-080600',
                      'deployment_profile':'public','pack_included':False,'lenses_included':False,
                      'code_sha256':remote._digest_file(d/'code.tar.gz'),
                      'content_sha256':remote._digest_file(d/'content.tar.gz')}
            (d/'manifest.json').write_text(json.dumps(manifest))
            with self.assertRaisesRegex(RuntimeError,'contenu|Contenu'):
                remote.verify_bundle(d,'20261027-080600')

    def test_templates_enforce_public_and_npm_ci(self):
        docker=(ROOT/'templates'/'Dockerfile').read_text()
        comp=(ROOT/'templates'/'docker-compose.yml').read_text()
        self.assertIn('npm ci',docker)
        self.assertNotIn('npm install',docker)
        self.assertIn('KONSTELLATION_DEPLOYMENT_PROFILE: "public"',comp)
        self.assertIn('/api/ready',comp)
        self.assertNotIn('docker restart',comp)


if __name__=='__main__':unittest.main()
