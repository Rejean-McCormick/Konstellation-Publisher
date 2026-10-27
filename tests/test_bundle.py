from __future__ import annotations

import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
import zipfile

HERE=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(HERE))
from publisher_bundle import prepare_bundle
from publisher_safety import PublicationBlocked
from deploy_remote import verify_bundle, BundleRejected
from test_safety import base_checkout


class BundleIntegrationTests(unittest.TestCase):
    def test_complete_bundle_roundtrip_verified(self):
        with tempfile.TemporaryDirectory() as td:
            folder=Path(td)
            checkout=base_checkout(folder/'checkout')
            result=prepare_bundle(checkout=checkout,project=HERE,target=folder/'release.zip',
                                  release_id='20261027-080600')
            self.assertEqual(result['schema'],'konstellation-publisher/v2.1')
            extraction=folder/'unpacked'
            extraction.mkdir()
            with zipfile.ZipFile(result['target']) as bundle:
                self.assertIn('publisher_transaction.py',bundle.namelist())
                self.assertIn('runtime/Dockerfile',bundle.namelist())
                bundle.extractall(extraction)
            out=verify_bundle(extraction,'20261027-080600')
            self.assertFalse(out['pack_included'])
            self.assertEqual(out['content_authorization'],'NOT_VERIFIED')
            with self.assertRaises(FileExistsError):
                prepare_bundle(checkout=checkout,project=HERE,target=folder/'release.zip',
                               release_id='20261027-080600')
            (extraction/'runtime'/'Dockerfile').write_text('changed')
            with self.assertRaisesRegex(BundleRejected,'Empreinte'):
                verify_bundle(extraction,'20261027-080600')

    def test_bundle_rejects_unqualified_packs(self):
        with tempfile.TemporaryDirectory() as td:
            folder=Path(td)
            checkout=base_checkout(folder/'checkout')
            with self.assertRaises(PublicationBlocked):
                prepare_bundle(checkout=checkout,project=HERE,target=folder/'release.zip',
                               release_id='20261027-080600',pack_file='private.json')
            self.assertFalse((folder/'release.zip').exists())


if __name__=='__main__':unittest.main()
