#!/usr/bin/env python3
from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import secrets
import re
import socket
import shlex
import shutil
import subprocess
import sys
import tarfile
import time


def log(msg: str) -> None:
    print(msg, flush=True)


def run(argv, *, cwd=None, check=True, capture=False):
    shown = " ".join(shlex.quote(str(x)) for x in argv)
    log(f"$ {shown}")
    cp = subprocess.run(
        [str(x) for x in argv],
        cwd=str(cwd) if cwd else None,
        check=False,
        text=True,
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.STDOUT if capture else None,
    )
    if capture and cp.stdout:
        print(cp.stdout, end="")
    if check and cp.returncode != 0:
        raise RuntimeError(f"Commande échouée (rc={cp.returncode}) : {shown}")
    return cp


def safe_extract(tar_path: Path, dest: Path) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    with tarfile.open(tar_path, "r:gz") as tf:
        root = dest.resolve()
        for member in tf.getmembers():
            target = (dest / member.name).resolve()
            if root != target and root not in target.parents:
                raise RuntimeError(f"Archive invalide : {member.name}")
        # Python 3.14+ applies safer tar extraction defaults. Be explicit now
        # so deployments remain warning-free and reject unsafe metadata.
        tf.extractall(dest, filter="data")


def write_env(path: Path, values: dict[str, str]) -> None:
    def encode(v: str) -> str:
        # Compose .env supports simple double-quoted values. Escape only what is
        # necessary here; all publisher-generated secrets are URL-safe.
        v = str(v).replace("\\", "\\\\").replace('"', '\\"')
        return f'"{v}"'

    path.write_text("\n".join(f"{k}={encode(v)}" for k, v in values.items()) + "\n", encoding="utf-8")
    os.chmod(path, 0o600)


def read_env(path: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    if not path.exists():
        return result
    for raw in path.read_text(encoding="utf-8").splitlines():
        s = raw.strip()
        if not s or s.startswith("#") or "=" not in s:
            continue
        k, v = s.split("=", 1)
        v = v.strip()
        if len(v) >= 2 and v[0] == v[-1] == '"':
            v = v[1:-1].replace('\\"', '"').replace('\\\\', '\\')
        result[k.strip()] = v
    return result


def compose(runtime: Path, *args, check=True, capture=False):
    return run(
        ["docker", "compose", "--project-name", "konstellation", "-f", str(runtime / "docker-compose.yml"), *args],
        cwd=runtime,
        check=check,
        capture=capture,
    )


def wait_healthy(runtime: Path, timeout: int = 180) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        cp = compose(runtime, "ps", "--format", "json", check=False, capture=True)
        text = cp.stdout or ""
        if cp.returncode == 0 and '"Health":"healthy"' in text.replace(" ", ""):
            return
        # Compose versions differ in JSON formatting. A direct request from the
        # app container is the authoritative fallback.
        cp = compose(
            runtime,
            "exec", "-T", "app", "node", "-e",
            "fetch('http://127.0.0.1:4321/api/health').then(r=>process.exit(r.ok?0:1)).catch(()=>process.exit(1))",
            check=False,
            capture=True,
        )
        if cp.returncode == 0:
            return
        time.sleep(4)
    # Surface the last container logs/status: this turns a generic timeout into
    # actionable deployment output if a future application error occurs.
    compose(runtime, "ps", check=False, capture=True)
    compose(runtime, "logs", "--tail", "120", "app", check=False, capture=True)
    raise RuntimeError("Konstellation n'est pas devenu sain dans le délai prévu.")


def create_backup(root: Path) -> None:
    current = root / "current"
    current_content = root / "current-content"
    runtime = root / "runtime"
    if not current.exists() and not current.is_symlink() and not runtime.exists():
        return
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = root / "backups" / stamp
    backup.mkdir(parents=True, exist_ok=True)
    state = {}
    if current.is_symlink():
        state["current"] = os.readlink(current)
    if current_content.is_symlink():
        state["current_content"] = os.readlink(current_content)
    if (root / "publisher-state.json").is_file():
        shutil.copy2(root / "publisher-state.json", backup / "publisher-state.json")
    if (runtime / ".env").is_file():
        shutil.copy2(runtime / ".env", backup / "runtime.env")
    if (runtime / "semantik.json").is_file():
        shutil.copy2(runtime / "semantik.json", backup / "semantik.json")
    (backup / "links.json").write_text(json.dumps(state, indent=2), encoding="utf-8")
    old = sorted([p for p in (root / "backups").iterdir() if p.is_dir()])
    for p in old[:-3]:
        shutil.rmtree(p, ignore_errors=True)


def replace_symlink(link: Path, target: Path) -> None:
    if link.is_symlink() or link.exists():
        if link.is_symlink() or link.is_file():
            link.unlink()
        else:
            shutil.rmtree(link)
    link.symlink_to(target, target_is_directory=True)


def patch_traefik(payload: dict, root: Path) -> None:
    kx_root = Path(payload["konnaxion_root"])
    instance = payload["konnaxion_instance"]
    dynamic = kx_root / "instances" / instance / "state" / "traefik-dynamic.yml"
    if not dynamic.is_file():
        raise RuntimeError(f"Configuration Traefik Konnaxion introuvable : {dynamic}")

    venv_python = kx_root / "manager" / ".venv" / "bin" / "python"
    if not venv_python.is_file():
        raise RuntimeError(f"Python Konnaxion introuvable : {venv_python}")

    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = root / "backups" / f"traefik-dynamic.{stamp}.yml"
    shutil.copy2(dynamic, backup)

    aliases = [x.strip() for x in payload.get("aliases", "").split(",") if x.strip()]
    helper = r'''
import json, os, sys
from pathlib import Path
import yaml

path = Path(sys.argv[1])
domain = sys.argv[2]
aliases = json.loads(sys.argv[3])
data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
http = data.setdefault("http", {})
routers = http.setdefault("routers", {})
services = http.setdefault("services", {})
middlewares = http.setdefault("middlewares", {})

hosts = [domain] + [x for x in aliases if x and x != domain]
host_rule = " || ".join("Host(`%s`)" % h for h in hosts)
resolver = "letsencrypt"
for candidate in routers.values():
    tls = candidate.get("tls") if isinstance(candidate, dict) else None
    if isinstance(tls, dict) and tls.get("certResolver"):
        resolver = str(tls["certResolver"])
        break

router = {
    "rule": host_rule + " && PathPrefix(`/`)",
    "entryPoints": ["websecure"],
    "service": "konstellation-site",
    "tls": {"certResolver": resolver},
    "priority": 50,
}
if "secure-headers" in middlewares:
    router["middlewares"] = ["secure-headers"]
routers["konstellation-site"] = router
services["konstellation-site"] = {
    "loadBalancer": {"servers": [{"url": "http://konstellation-app:4321"}]}
}

st = path.stat()
rendered = yaml.safe_dump(data, sort_keys=False, allow_unicode=True)
tmp = path.with_suffix(path.suffix + ".konstellation.tmp")
tmp.write_text(rendered, encoding="utf-8")
yaml.safe_load(tmp.read_text(encoding="utf-8"))
# Preserve the inode because the running Traefik container may bind-mount this
# exact file, as in the existing Konnaxion/UCKK deployment.
path.write_text(rendered, encoding="utf-8")
tmp.unlink(missing_ok=True)
os.chown(path, st.st_uid, st.st_gid)
os.chmod(path, st.st_mode & 0o777)
'''
    run([str(venv_python), "-c", helper, str(dynamic), payload["domain"], json.dumps(aliases)])
    run([
        str(venv_python), "-c",
        "import yaml,sys; yaml.safe_load(open(sys.argv[1],encoding='utf-8')); print('Traefik YAML OK')",
        str(dynamic),
    ])
    log(f"Route Traefik Konstellation ajoutée. Backup : {backup}")


def _traefik_container(instance: str) -> str | None:
    expected = f"kx-{instance}-traefik"
    cp = run(["docker", "ps", "--format", "{{.Names}}"], check=False, capture=True)
    names = [line.strip() for line in (cp.stdout or "").splitlines() if line.strip()]
    if expected in names:
        return expected
    matches = [name for name in names if instance in name and name.endswith("-traefik")]
    return matches[0] if len(matches) == 1 else None


def _domain_ipv4(domain: str) -> set[str]:
    try:
        return {
            info[4][0]
            for info in socket.getaddrinfo(domain, 443, socket.AF_INET, socket.SOCK_STREAM)
            if info and info[4]
        }
    except OSError:
        return set()


def _public_tls_ok(domain: str) -> bool:
    # --resolve exercises Traefik locally while still validating the public
    # certificate for the real SNI/Host name. A default self-signed Traefik
    # certificate therefore fails exactly as a browser would.
    cp = run(
        [
            "curl", "--silent", "--show-error", "--fail", "--max-time", "8",
            "--resolve", f"{domain}:443:127.0.0.1",
            f"https://{domain}/api/health",
        ],
        check=False,
        capture=True,
    )
    return cp.returncode == 0


def ensure_public_tls(payload: dict) -> None:
    domain = str(payload.get("domain", "")).strip()
    expected_ip = str(payload.get("server_host", "")).strip()
    if not domain:
        return
    if _public_tls_ok(domain):
        log(f"TLS public déjà valide pour {domain}.")
        return

    resolved = _domain_ipv4(domain)
    if not resolved:
        log(f"AVERTISSEMENT TLS — DNS {domain} pas encore résolu; certificat public différé.")
        return
    if expected_ip and expected_ip not in resolved:
        log(
            f"AVERTISSEMENT TLS — {domain} résout vers {', '.join(sorted(resolved))}, "
            f"pas vers le VPS attendu {expected_ip}; redémarrage Traefik ignoré."
        )
        return

    container = _traefik_container(str(payload.get("konnaxion_instance", "")))
    if not container:
        log("AVERTISSEMENT TLS — conteneur Traefik Konnaxion non identifié automatiquement.")
        return

    log(
        f"Certificat public pas encore chargé pour {domain}; "
        f"redémarrage contrôlé de {container} pour relancer ACME…"
    )
    run(["docker", "restart", container])
    deadline = time.time() + 90
    while time.time() < deadline:
        time.sleep(5)
        if _public_tls_ok(domain):
            log(f"TLS_OK — certificat public valide pour {domain}.")
            return
    log(
        f"AVERTISSEMENT TLS — Traefik répond, mais le certificat public de {domain} "
        "n'est pas encore validé. Relancer Vérifier en ligne après propagation/ACME."
    )


def _digest_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def verify_bundle(bundle_dir: Path, expected_release_id: str) -> dict:
    """Check exact manifest and archives before any remote side effect."""
    if not isinstance(expected_release_id, str) or not re.fullmatch(r'[0-9]{8}-[0-9]{6}', expected_release_id):
        raise RuntimeError('Identifiant release invalide')
    mpath = bundle_dir / 'manifest.json'
    if mpath.is_symlink() or not mpath.is_file():
        raise RuntimeError('Manifeste absent ou symlink interdit')
    manifest = json.loads(mpath.read_text(encoding='utf-8'))
    if manifest.get('schema') != 'konstellation-publisher/v2' or manifest.get('release_id') != expected_release_id:
        raise RuntimeError('Manifeste schema/release incompatible')
    if manifest.get('deployment_profile') != 'public':
        raise RuntimeError('Le profil public doit etre explicite')
    if manifest.get('pack_included') or manifest.get('lenses_included'):
        raise RuntimeError('Paquet de donnees non qualifie interdit')
    for name, key in [('code.tar.gz','code_sha256'),('content.tar.gz','content_sha256')]:
        item = bundle_dir / name
        digest = manifest.get(key)
        if not isinstance(digest,str) or len(digest) != 64 or item.is_symlink() or not item.is_file():
            raise RuntimeError(f'Empreinte absente ou chemin invalide pour {name}')
        if item.stat().st_size > 500 * 1024 * 1024:
            raise RuntimeError(f'Archive trop volumineuse: {name}')
        if _digest_file(item) != digest:
            raise RuntimeError(f'Empreinte non conforme: {name}')
        with tarfile.open(item,'r:gz') as tf:
            for m in tf:
                if name == 'content.tar.gz' and m.isfile():
                    raise RuntimeError('Contenu de publication non autorisé dans content.tar.gz')
                p = Path(m.name)
                if p.is_absolute() or '..' in p.parts or '\\' in m.name or not (m.isfile() or m.isdir()):
                    raise RuntimeError(f'Entree archive interdite: {m.name}')
    return manifest


def main() -> int:
    payload = json.load(sys.stdin)
    # Explicitly blocked until trustworthy C1/C2/C3 receipts and a tested
    # transactional rollout + rollback exist. Verification is read-only.
    verify_bundle(Path(payload['bundle_dir']), payload['release_id'])
    raise RuntimeError('PUBLISH_BLOCKED: live rollout/rollback and public publication authorization not qualified')

    bundle_dir = Path(payload["bundle_dir"])
    root = Path(payload["remote_root"])
    stamp = payload["release_id"]
    release = root / "releases" / stamp
    content_release = root / "content" / stamp
    current = root / "current"
    current_content = root / "current-content"
    runtime = root / "runtime"

    for p in [root, root / "releases", root / "content", root / "backups", runtime]:
        p.mkdir(parents=True, exist_ok=True)

    if not shutil.which("docker"):
        raise RuntimeError("Docker n'est pas installé sur le VPS.")
    run(["docker", "compose", "version"])

    edge = payload["edge_network"]
    cp = run(["docker", "network", "inspect", edge], check=False, capture=True)
    if cp.returncode != 0:
        raise RuntimeError(f"Réseau Docker partagé introuvable : {edge}")

    create_backup(root)

    if release.exists():
        shutil.rmtree(release)
    if content_release.exists():
        shutil.rmtree(content_release)
    safe_extract(bundle_dir / "code.tar.gz", release)
    safe_extract(bundle_dir / "content.tar.gz", content_release)

    shutil.copy2(bundle_dir / "runtime" / "Dockerfile", runtime / "Dockerfile")
    shutil.copy2(bundle_dir / "runtime" / "docker-compose.yml", runtime / "docker-compose.yml")

    aliases = [x.strip() for x in payload.get("aliases", "").split(",") if x.strip()]
    # Public requests arrive with the configured domain, while Docker health
    # probes are intentionally performed inside the container through loopback.
    # Konstellation validates the Host header before serving /api/health, so the
    # loopback hostnames must be explicitly trusted as well.
    allowed_host_items = [payload["domain"], *aliases, "localhost", "127.0.0.1", "[::1]"]
    allowed_hosts = ",".join(dict.fromkeys(x for x in allowed_host_items if x))
    old_env = read_env(runtime / ".env")
    cursor_secret = old_env.get("KONSTELLATION_CURSOR_SECRET", secrets.token_urlsafe(48))
    image = f"konstellation:{stamp}"

    pack_path = content_release / "pack.json"
    lenses_path = content_release / "lenses"
    semantik_enabled = bool(payload.get("semantik_enabled"))
    semantik_cfg = {
        "baseUrl": payload.get("semantik_url", ""),
        "runtimeSetId": payload.get("runtime_set_id", ""),
        "capabilityProfile": payload.get("capability_profile", "konstellation-explorer-2"),
        "languages": payload.get("languages", ["fr"]),
        "saGfContractVersion": payload.get("sa_gf_contract_version", "1.0"),
        "timeoutMs": int(payload.get("timeout_ms", 10000)),
        "maxAssertions": int(payload.get("max_assertions", 200)),
    }
    (runtime / "semantik.json").write_text(json.dumps(semantik_cfg, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.chmod(runtime / "semantik.json", 0o600)

    env_values = {
        "KONSTELLATION_IMAGE": image,
        "KONSTELLATION_CONTENT": str(current_content),
        "KONSTELLATION_EDGE_NETWORK": edge,
        "KONSTELLATION_ALLOWED_HOSTS": allowed_hosts,
        "KONSTELLATION_ROLES": payload.get("roles", "public"),
        "KONSTELLATION_CURSOR_SECRET": cursor_secret,
        "KONSTELLATION_PACK": "/content/pack.json" if pack_path.is_file() else "",
        "KONSTELLATION_LENSES": "/content/lenses" if lenses_path.is_dir() else "",
        "KONSTELLATION_SA_CONFIG": "/runtime/semantik.json" if semantik_enabled else "",
    }
    write_env(runtime / ".env", env_values)

    log(f"Construction image {image}…")
    run(["docker", "build", "--pull", "-t", image, "-f", str(runtime / "Dockerfile"), str(release)])

    replace_symlink(current, release)
    replace_symlink(current_content, content_release)

    compose(runtime, "up", "-d", "--force-recreate", "app")
    wait_healthy(runtime)
    patch_traefik(payload, root)
    ensure_public_tls(payload)

    # Validate both the internal application and the public-facing route when
    # DNS is already active. Public DNS/TLS is verified again by the desktop app.
    cp = compose(runtime, "exec", "-T", "app", "node", "-e",
                 "fetch('http://127.0.0.1:4321/api/health').then(async r=>{console.log(await r.text());process.exit(r.ok?0:1)}).catch(e=>{console.error(e);process.exit(1)})",
                 check=False, capture=True)
    if cp.returncode != 0:
        raise RuntimeError("Le healthcheck interne Konstellation a échoué après publication.")

    state = {
        "release_id": stamp,
        "image": image,
        "domain": payload["domain"],
        "aliases": payload.get("aliases", ""),
        "remote_root": str(root),
        "edge_network": edge,
        "pack": pack_path.is_file(),
        "lenses": lenses_path.is_dir(),
        "semantik_enabled": semantik_enabled,
        "published_at": dt.datetime.now(dt.timezone.utc).isoformat(),
    }
    (root / "publisher-state.json").write_text(json.dumps(state, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    compose(runtime, "ps", capture=True)

    # Keep only the three newest source/content releases. Images are retained so
    # rollback remains possible from the backups/state without an automatic prune.
    for base in [root / "releases", root / "content"]:
        old = sorted([p for p in base.iterdir() if p.is_dir()])
        for p in old[:-3]:
            shutil.rmtree(p, ignore_errors=True)

    log("")
    log("KONSTELLATION_PUBLISH_RESULT=OK")
    log(f"KONSTELLATION_URL=https://{payload['domain']}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print("KONSTELLATION_PUBLISH_RESULT=ERROR", file=sys.stderr, flush=True)
        print(f"ERROR={exc}", file=sys.stderr, flush=True)
        raise
