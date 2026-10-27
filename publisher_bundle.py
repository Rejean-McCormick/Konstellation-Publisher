"""Deterministic file selection and sealed local v2.1 Publisher bundle creation."""
from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import tarfile
import tempfile
import zipfile

from publisher_safety import build_code_tar, digest_file, assert_no_unqualified_content


def prepare_bundle(*, checkout: Path, project: Path, target: Path, release_id: str,
                   pack_file: str = "", lenses_dir: str = "", semantik_enabled: bool = False) -> dict:
    from publisher_transaction import _validate_release
    _validate_release(release_id)
    assert_no_unqualified_content(pack_file, lenses_dir)
    if target.exists():
        raise FileExistsError("Existing release bundle must not be overwritten")
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="publisher-bundle-") as tmp:
        staging = Path(tmp)
        build_code_tar(checkout, staging/"code.tar.gz")
        with tarfile.open(staging/"content.tar.gz", "w:gz"):
            pass  # intentionally EMPTY; no authorized public corpus available
        runtime = staging/"runtime"
        runtime.mkdir()
        for name in ("Dockerfile", "docker-compose.yml"):
            source = project/"templates"/name
            if not source.is_file() or source.is_symlink():
                raise FileNotFoundError(f"Runtime template missing/unsafe: {name}")
            shutil.copyfile(source, runtime/name)
        for name in ("deploy_remote.py", "publisher_transaction.py"):
            source = project/name
            if not source.is_file() or source.is_symlink():
                raise FileNotFoundError(f"Publisher source missing/unsafe: {name}")
            shutil.copyfile(source, staging/name)
        manifest = {
            "schema": "konstellation-publisher/v2.1",
            "deployment_profile": "public",
            "content_authorization": "NOT_VERIFIED",
            "release_id": release_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "code_sha256": digest_file(staging/"code.tar.gz"),
            "content_sha256": digest_file(staging/"content.tar.gz"),
            "runtime_sha256": {name: digest_file(runtime/name) for name in ("Dockerfile", "docker-compose.yml")},
            "deployer_sha256": digest_file(staging/"deploy_remote.py"),
            "transaction_sha256": digest_file(staging/"publisher_transaction.py"),
            "pack_included": False, "lenses_included": False,
            "semantik_enabled": bool(semantik_enabled),
        }
        (staging/"manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False)+"\n", encoding="utf-8")
        with zipfile.ZipFile(target,"x",compression=zipfile.ZIP_DEFLATED) as bundle:
            for path in sorted(staging.rglob("*")):
                if path.is_file():
                    bundle.write(path,path.relative_to(staging).as_posix())
    return {"target": str(target), "sha256": digest_file(target), "release_id": release_id,
            "schema": "konstellation-publisher/v2.1"}
