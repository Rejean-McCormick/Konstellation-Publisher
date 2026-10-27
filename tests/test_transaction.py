from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import publisher_transaction as tx
import deploy_remote as remote


class TransactionTests(unittest.TestCase):
    def test_success_only_after_postcutover_readiness(self):
        result = tx.rehearsal()
        self.assertEqual(result['phase'], 'COMPLETE')
        self.assertEqual(result['active'], '20261027-080600')
        self.assertEqual(result['events'][-2:], ['VERIFYING','COMPLETE'])

    def test_failures_roll_back_or_abort_without_traffic_loss(self):
        expectations = {'stage':'ABORTED', 'candidate':'ABORTED',
                        'switch_before':'ROLLED_BACK', 'switch_after':'ROLLED_BACK',
                        'public':'ROLLED_BACK'}
        for step, final in expectations.items():
            with self.subTest(step=step):
                result = tx.rehearsal(step)
                self.assertEqual(result['phase'], final)
                self.assertEqual(result['active'], 'previous-release')
                self.assertEqual(result['previous'], 'previous-release')
                self.assertTrue(result['error'])

    def setup_backend(self, directory: Path):
        directory.mkdir(parents=True, exist_ok=True)
        (directory/'.publisher-rehearsal-only').write_text('yes')
        return tx.SandboxBackend(directory)

    def test_postcutover_interrupt_and_recover(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            backend = self.setup_backend(root)
            engine = tx.TransactionEngine(root/'journal', backend)
            original_switch = backend.switch
            def interrupt_after_cutover(release):
                original_switch(release)
                raise KeyboardInterrupt('simulated power interruption')
            backend.switch = interrupt_after_cutover
            with self.assertRaises(KeyboardInterrupt):
                engine.deploy('20261027-080600')
            self.assertEqual(engine.read()['phase'], 'CUTOVER_INTENT')
            self.assertEqual(backend.active_release(), '20261027-080600')
            backend.switch = original_switch
            after_restart = tx.TransactionEngine(root/'journal', backend)
            result = after_restart.recover()
            self.assertEqual(result['phase'], 'ROLLED_BACK')
            self.assertEqual(backend.active_release(), 'previous-release')
            self.assertEqual(after_restart.recover()['phase'], 'ROLLED_BACK')

    def test_no_second_deploy_when_recovery_needed(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            backend = self.setup_backend(root)
            backend.fail_step = 'restore'
            engine = tx.TransactionEngine(root/'journal', backend)
            # Failure during postcutover verification then during restoration.
            backend.public_ready = lambda _: False
            with self.assertRaises(tx.RecoveryRequired):
                engine.deploy('20261027-080600')
            self.assertEqual(engine.read()['phase'], 'RECOVERY_REQUIRED')
            with self.assertRaises(tx.RecoveryRequired):
                engine.deploy('20261028-080600')
            backend.fail_step = ''
            self.assertEqual(engine.recover()['phase'], 'ROLLED_BACK')

    def test_completed_journal_archived_not_overwritten(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            backend = self.setup_backend(root)
            engine = tx.TransactionEngine(root/'journal', backend)
            result = engine.deploy('20261027-080600')
            self.assertEqual(result['phase'], 'COMPLETE')
            result2 = engine.deploy('20261028-080600')
            self.assertEqual(result2['phase'], 'COMPLETE')
            archived = root/'journal'/'history'/'20261027-080600-COMPLETE.json'
            self.assertTrue(archived.is_file())
            self.assertEqual(json.loads(archived.read_text())['previous'], 'previous-release')
            with self.assertRaises(tx.RolloutError):
                engine.deploy('20261028-080600')

    def test_rollback_failed_probe_requires_recovery(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            backend = self.setup_backend(root)
            backend.fail_step = 'restore_probe'
            engine = tx.TransactionEngine(root/'journal', backend)
            backend.public_ready = lambda _: False
            with self.assertRaises(tx.RecoveryRequired):
                engine.deploy('20261027-080600')
            self.assertEqual(engine.read()['phase'], 'RECOVERY_REQUIRED')
            backend.fail_step = ''
            self.assertEqual(engine.recover()['phase'], 'ROLLED_BACK')

    def test_missing_readiness_blocks_before_cutover(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            backend = self.setup_backend(root)
            backend.candidate_ready = lambda _: False
            engine=tx.TransactionEngine(root/'journal',backend)
            with self.assertRaisesRegex(tx.RolloutError, 'readiness'):
                engine.deploy('20261027-080600')
            self.assertEqual(backend.active_release(), 'previous-release')
            self.assertEqual(engine.read()['phase'], 'ABORTED')

    def test_simulation_requires_marker_no_ssh(self):
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(tx.RolloutError):
                tx.SandboxBackend(Path(td))
        run = subprocess.run([sys.executable, str(ROOT/'publisher_transaction.py'),'--simulate','--fail','public'],
                             capture_output=True, text=True, timeout=15)
        self.assertEqual(run.returncode, 0, run.stderr)
        doc=json.loads(run.stdout)
        self.assertEqual(doc['phase'], 'ROLLED_BACK')
        self.assertEqual(doc['mode'], 'SANDBOX_ONLY')

    def test_journal_lock_fail_closed(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            backend=self.setup_backend(root)
            engine=tx.TransactionEngine(root/'journal',backend)
            (root/'journal'/'writer.lock').write_text('orphan')
            with self.assertRaises(tx.RecoveryRequired):
                engine.deploy('20261027-080600')
            self.assertEqual(backend.active_release(), 'previous-release')

    def test_live_remote_script_hard_blocked(self):
        # No deploy function or subprocess runner exists anymore in remote entry.
        self.assertFalse(hasattr(remote,'patch_traefik'))
        self.assertFalse(hasattr(remote,'compose'))
        self.assertFalse(hasattr(remote,'run'))
        self.assertIn('PUBLISH_BLOCKED', (ROOT/'deploy_remote.py').read_text())


if __name__ == '__main__':
    unittest.main()
