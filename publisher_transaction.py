"""Offline, crash-recoverable rollout orchestration for Konstellation Publisher.

This is an infrastructure-independent *candidate* implementation. The included
backend is a SIMULATOR ONLY: it never runs Docker, SSH, Traefik or public HTTP.
No production backend or trustworthy C1/C2/C3 authorization is wired.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import tempfile
from typing import Protocol

RELEASE_PATTERN = re.compile(r"[0-9]{8}-[0-9]{6}\Z")
FINAL = {"COMPLETE", "ROLLED_BACK", "ABORTED"}
ACTIVE = {"CREATED", "STAGED", "CANDIDATE_READY", "CUTOVER_INTENT", "CUTOVER_DONE", "VERIFYING", "ROLLBACK_INTENT", "RECOVERY_REQUIRED"}


class RolloutError(RuntimeError):
    pass


class RecoveryRequired(RolloutError):
    pass


def _validate_release(value: str) -> str:
    if not isinstance(value, str) or not RELEASE_PATTERN.fullmatch(value):
        raise RolloutError("Invalid release ID")
    return value


def _atomic_json(path: Path, value: dict) -> None:
    tmp = path.with_name(path.name + ".tmp")
    if tmp.is_symlink() or path.is_symlink():
        raise RolloutError("Symlink in journal path")
    try:
        with tmp.open("x", encoding="utf-8") as output:
            json.dump(value, output, sort_keys=True, ensure_ascii=False, indent=2)
            output.write("\n")
            output.flush()
            os.fsync(output.fileno())
        os.replace(tmp, path)
        if os.name != "nt":
            fd = os.open(str(path.parent), os.O_RDONLY)
            try: os.fsync(fd)
            finally: os.close(fd)
    finally:
        if tmp.exists(): tmp.unlink()


@contextmanager
def _lock(folder: Path):
    """Exclusive operation lock. A crash leaves a lock needing operator review."""
    lock = folder / "writer.lock"
    if lock.is_symlink():
        raise RecoveryRequired("Unsafe lock path")
    try:
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError as exc:
        raise RecoveryRequired("Writer lock exists; review live writers before manual removal") from exc
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as output:
            output.write("publisher-transaction-v1\n")
            output.flush()
            os.fsync(output.fileno())
        yield
    finally:
        lock.unlink(missing_ok=True)


class Backend(Protocol):
    def active_release(self) -> str | None: ...
    def stage(self, release: str) -> None: ...
    def candidate_ready(self, release: str) -> bool: ...
    def switch(self, release: str) -> None: ...
    def public_ready(self, release: str) -> bool: ...
    def restore(self, previous_release: str | None) -> None: ...
    def restored(self, previous_release: str | None) -> bool: ...


class TransactionEngine:
    """Persist intent BEFORE touching the active route; restore on uncertainty.

    This class does not grant any publication rights. A trusted C1/C2/C3 gate
    must be placed *outside* it before a real backend can ever be used.
    """
    def __init__(self, folder: Path, backend: Backend):
        self.folder = Path(folder)
        self.backend = backend
        if self.folder.is_symlink():
            raise RolloutError("Journal folder may not be a symlink")
        self.folder.mkdir(parents=True, exist_ok=True)
        self.journal_file = self.folder / "transaction.json"

    def read(self) -> dict | None:
        if self.journal_file.is_symlink():
            raise RolloutError("Journal symlink prohibited")
        if not self.journal_file.exists():
            return None
        doc = json.loads(self.journal_file.read_text(encoding="utf-8"))
        if doc.get("schema") != "publisher.rollback-journal/1.0" or doc.get("phase") not in (ACTIVE | FINAL):
            raise RecoveryRequired("Unknown/corrupted journal")
        _validate_release(doc.get("release"))
        if doc.get("previous") is not None and not isinstance(doc.get("previous"), str):
            raise RecoveryRequired("Invalid prior release")
        return doc

    def _save(self, doc: dict, phase: str, reason: str = "") -> None:
        doc["phase"] = phase
        doc["updated_utc"] = datetime.now(timezone.utc).isoformat()
        doc.setdefault("events", []).append({"phase": phase, "reason": reason})
        _atomic_json(self.journal_file, doc)

    def _archive_previous(self, previous: dict) -> None:
        """Retain all completed journal evidence before starting another release."""
        history = self.folder / "history"
        if history.is_symlink():
            raise RolloutError("History path cannot be symlink")
        history.mkdir(exist_ok=True)
        archive = history / f"{previous['release']}-{previous['phase']}.json"
        if archive.exists() or archive.is_symlink():
            raise RecoveryRequired("History archive already exists: refusing overwrite")
        _atomic_json(archive, previous)

    def deploy(self, release: str) -> dict:
        _validate_release(release)
        with _lock(self.folder):
            prior = self.read()
            if prior is not None and prior["phase"] not in FINAL:
                raise RecoveryRequired("Previous transaction unfinished; recover first")
            if prior is not None and prior["release"] == release:
                raise RolloutError("Release identifier already used; immutable history required")
            previous = self.backend.active_release()
            if previous == release:
                raise RolloutError("Release is already active; refusing same-ID re-deployment")
            if prior is not None:
                self._archive_previous(prior)
            doc = {"schema": "publisher.rollback-journal/1.0", "release": release,
                   "previous": previous, "phase": "CREATED", "events": []}
            self._save(doc, "CREATED")
            try:
                self.backend.stage(release)  # must not change active traffic
                if self.backend.active_release() != previous:
                    raise RolloutError("Staging changed active traffic")
                self._save(doc, "STAGED")
                if not self.backend.candidate_ready(release):
                    raise RolloutError("Candidate readiness rejected")
                if self.backend.active_release() != previous:
                    raise RolloutError("Candidate probing changed active traffic")
                self._save(doc, "CANDIDATE_READY")
                self._save(doc, "CUTOVER_INTENT")  # recovery must rollback from here
                self.backend.switch(release)
                self._save(doc, "CUTOVER_DONE")
                self._save(doc, "VERIFYING")
                if not self.backend.public_ready(release):
                    raise RolloutError("Post-cutover public readiness rejected")
                if self.backend.active_release() != release:
                    raise RolloutError("Active release drift after cutover")
                self._save(doc, "COMPLETE")
                return doc
            except Exception as exc:
                if doc["phase"] in ("CREATED", "STAGED", "CANDIDATE_READY") and self.backend.active_release() == previous:
                    self._save(doc, "ABORTED", str(exc))
                else:
                    self._restore(doc, str(exc))
                raise

    def _restore(self, doc: dict, reason: str) -> None:
        previous = doc["previous"]
        self._save(doc, "ROLLBACK_INTENT", reason)
        try:
            self.backend.restore(previous)
            if not self.backend.restored(previous) or self.backend.active_release() != previous:
                raise RolloutError("Restored route/readiness cannot be verified")
            self._save(doc, "ROLLED_BACK", reason)
        except Exception as exc:
            self._save(doc, "RECOVERY_REQUIRED", str(exc))
            raise RecoveryRequired("Rollback unverified; manual intervention REQUIRED") from exc

    def recover(self) -> dict:
        with _lock(self.folder):
            doc = self.read()
            if doc is None:
                raise RolloutError("No transaction journal")
            if doc["phase"] in FINAL:
                return doc
            # Every interrupted phase, including uncertain cutover, rolls back.
            if doc["phase"] in ("CREATED", "STAGED", "CANDIDATE_READY") and self.backend.active_release() == doc["previous"]:
                self._save(doc, "ABORTED", "recovered before cutover")
            else:
                self._restore(doc, "recovered after ambiguous interruption")
            return doc


class SandboxBackend:
    """Atomic route-file simulator; requires an explicit marker in its sandbox."""
    def __init__(self, folder: Path, *, fail_step: str = ""):
        self.folder = Path(folder)
        if not (self.folder / ".publisher-rehearsal-only").is_file():
            raise RolloutError("Simulator marker absent")
        self.fail_step = fail_step
        self.route = self.folder / "route.json"
        self.stage_dir = self.folder / "staged"
        self.stage_dir.mkdir(exist_ok=True)
        if not self.route.exists():
            _atomic_json(self.route, {"active": "previous-release"})

    def _fail(self, step: str):
        if self.fail_step == step:
            raise RolloutError(f"Injected failure: {step}")

    def active_release(self) -> str | None:
        return json.loads(self.route.read_text(encoding="utf-8"))["active"]

    def stage(self, release: str) -> None:
        self._fail("stage")
        (self.stage_dir / release).mkdir(exist_ok=True)
        (self.stage_dir / release / "ready.json").write_text('{"candidate":true}\n')

    def candidate_ready(self, release: str) -> bool:
        self._fail("candidate")
        return (self.stage_dir / release / "ready.json").is_file()

    def switch(self, release: str) -> None:
        self._fail("switch_before")
        _atomic_json(self.route, {"active": release})
        self._fail("switch_after")

    def public_ready(self, release: str) -> bool:
        self._fail("public")
        return self.active_release() == release

    def restore(self, previous_release: str | None) -> None:
        self._fail("restore")
        _atomic_json(self.route, {"active": previous_release})

    def restored(self, previous_release: str | None) -> bool:
        self._fail("restore_probe")
        return self.active_release() == previous_release


def rehearsal(fail_step: str = "") -> dict:
    with tempfile.TemporaryDirectory(prefix="publisher-rehearsal-") as tmp:
        folder = Path(tmp)
        (folder / ".publisher-rehearsal-only").write_text("no docker/ssh/traefik\n", encoding="utf-8")
        backend = SandboxBackend(folder, fail_step=fail_step)
        engine = TransactionEngine(folder / "journal", backend)
        error = ""
        try:
            engine.deploy("20261027-080600")
        except (RolloutError, RecoveryRequired) as exc:
            error = str(exc)
        doc = engine.read()
        return {"mode": "SANDBOX_ONLY", "failure_injected": fail_step or None,
                "phase": doc["phase"], "active": backend.active_release(),
                "previous": doc["previous"], "error": error,
                "events": [x["phase"] for x in doc["events"]]}


def main() -> int:
    parser = argparse.ArgumentParser(description="Offline transaction rehearsal; NO remote operations")
    parser.add_argument("--simulate", action="store_true", help="Required: uses a new temporary sandbox")
    parser.add_argument("--fail", choices=["", "stage", "candidate", "switch_before", "switch_after", "public", "restore", "restore_probe"], default="")
    args = parser.parse_args()
    if not args.simulate:
        parser.error("No deployment operation available; --simulate is mandatory")
    print(json.dumps(rehearsal(args.fail), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
