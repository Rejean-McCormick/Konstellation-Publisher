# -*- coding: utf-8 -*-
from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tarfile
import tempfile
import threading
import urllib.request
import zipfile
from publisher_bundle import prepare_bundle
from publisher_safety import (audit_checkout, build_code_tar as build_safe_code_tar,
    assert_no_unqualified_content, assert_live_deploy_permitted, PublicationBlocked)

try:
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk
except Exception as exc:
    raise SystemExit(f"Tkinter indisponible: {exc}")

APP_DIR = Path(__file__).resolve().parent
CONFIG_PATH = APP_DIR / "konstellation_publisher.config.json"
REPORTS_DIR = APP_DIR / "reports"
PACKAGES_DIR = APP_DIR / "packages"
TEMPLATES_DIR = APP_DIR / "templates"
REMOTE_SCRIPT = APP_DIR / "deploy_remote.py"
TRANSACTION_SCRIPT = APP_DIR / "publisher_transaction.py"


def load_config():
    source = CONFIG_PATH if CONFIG_PATH.is_file() else APP_DIR / 'konstellation_publisher.config.example.json'
    return json.loads(source.read_text(encoding='utf-8'))


def save_config(data):
    CONFIG_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def sha256(path: Path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def run_process(argv, timeout=120, input_text=None):
    return subprocess.run(
        [str(x) for x in argv],
        input=input_text,
        text=True,
        capture_output=True,
        timeout=timeout,
        creationflags=(subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0),
    )


def ssh_base(cfg):
    s = cfg["server"]
    return [
        "ssh", "-T", "-p", str(s["ssh_port"]), "-i", s["ssh_key"],
        "-o", "BatchMode=yes",
        "-o", "PreferredAuthentications=publickey",
        "-o", "PasswordAuthentication=no",
        "-o", "KbdInteractiveAuthentication=no",
        "-o", "StrictHostKeyChecking=accept-new",
        "-o", "ConnectTimeout=12",
        f'{s["user"]}@{s["host"]}',
    ]


def scp_base(cfg):
    s = cfg["server"]
    return [
        "scp", "-P", str(s["ssh_port"]), "-i", s["ssh_key"],
        "-o", "BatchMode=yes",
        "-o", "PreferredAuthentications=publickey",
        "-o", "PasswordAuthentication=no",
        "-o", "KbdInteractiveAuthentication=no",
        "-o", "StrictHostKeyChecking=accept-new",
        "-o", "ConnectTimeout=12",
    ]


def build_code_tar(root: Path, target: Path):
    return build_safe_code_tar(root, target)


def build_content_tar(pack_file: Path | None, lenses_dir: Path | None, target: Path):
    with tarfile.open(target, "w:gz") as tf:
        if pack_file and pack_file.is_file():
            tf.add(pack_file, arcname="pack.json")
        if lenses_dir and lenses_dir.is_dir():
            for p in sorted(lenses_dir.glob("*.json"), key=lambda x: x.name.lower()):
                tf.add(p, arcname=f"lenses/{p.name}")


def parse_languages(text: str):
    langs = [x.strip() for x in text.split(",") if x.strip()]
    return langs or ["fr"]


class PublisherApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Konstellation Publisher")
        self.geometry("1160x820")
        self.minsize(1020, 720)
        self.cfg = load_config()
        self.last_package = None
        self._make_style()
        self._build_ui()
        self._load_values()

    def _make_style(self):
        style = ttk.Style(self)
        try:
            style.theme_use("vista")
        except Exception:
            pass
        style.configure("Title.TLabel", font=("Segoe UI", 18, "bold"))
        style.configure("Sub.TLabel", font=("Segoe UI", 10))
        style.configure("Action.TButton", padding=(10, 8))

    def _build_ui(self):
        outer = ttk.Frame(self, padding=16)
        outer.pack(fill="both", expand=True)
        ttk.Label(outer, text="Konstellation Publisher", style="Title.TLabel").pack(anchor="w")
        ttk.Label(
            outer,
            text="Publication Docker de Konstellation sur le VPS Netcup existant, derrière le Traefik Konnaxion.",
            style="Sub.TLabel",
        ).pack(anchor="w", pady=(0, 10))

        form = ttk.LabelFrame(outer, text="Configuration", padding=10)
        form.pack(fill="x")
        self.vars = {}
        fields = [
            ("konstellation_root", "Code Konstellation", 0, True),
            ("pack_file", "Pack JSON (optionnel)", 1, True),
            ("lenses_dir", "Dossier Lens (optionnel)", 2, True),
            ("host", "VPS Netcup", 3, False),
            ("user", "Utilisateur SSH", 4, False),
            ("ssh_key", "Clé SSH", 5, True),
            ("domain", "Domaine Konstellation (préconfiguré)", 6, False),
            ("aliases", "Alias DNS (séparés par virgule)", 7, False),
            ("remote_root", "Racine serveur", 8, False),
            ("konnaxion_instance", "Instance Konnaxion", 9, False),
            ("roles", "Rôles Konstellation", 10, False),
            ("semantik_url", "URL SemantiK", 11, False),
            ("runtime_set_id", "RuntimeSet SemantiK", 12, False),
            ("capability_profile", "Profil SemantiK", 13, False),
            ("languages", "Langues SA", 14, False),
        ]
        for key, label, row, picker in fields:
            ttk.Label(form, text=label).grid(row=row, column=0, sticky="w", padx=(0, 8), pady=2)
            var = tk.StringVar()
            self.vars[key] = var
            ttk.Entry(form, textvariable=var, width=94).grid(row=row, column=1, sticky="ew", pady=2)
            if picker:
                ttk.Button(form, text="…", width=3, command=lambda k=key: self.pick_path(k)).grid(
                    row=row, column=2, padx=(6, 0)
                )
        self.semantik_enabled = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            form,
            text="Activer l'intégration SemantiK (le service SemantiK doit déjà être joignable depuis Docker)",
            variable=self.semantik_enabled,
        ).grid(row=15, column=1, sticky="w", pady=(5, 1))
        form.columnconfigure(1, weight=1)

        actions = ttk.Frame(outer)
        actions.pack(fill="x", pady=10)
        buttons = [
            ("1. Vérifier Konstellation", self.local_check),
            ("2. Vérifier le VPS", self.server_check),
            ("3. Préparer le paquet", self.prepare_package),
            ("Simulation rollback (locale)", self.simulate_rollback),
            ("4. Publier (bloqué — alpha)", self.publish),
            ("5. Vérifier en ligne", self.verify_online),
        ]
        for i, (label, cmd) in enumerate(buttons):
            ttk.Button(actions, text=label, style="Action.TButton", command=cmd).grid(
                row=0, column=i, sticky="ew", padx=(0 if i == 0 else 4, 0)
            )
            actions.columnconfigure(i, weight=1)

        small = ttk.Frame(outer)
        small.pack(fill="x", pady=(0, 7))
        ttk.Button(small, text="Enregistrer la configuration", command=self.save_values).pack(side="left")
        ttk.Button(small, text="Ouvrir les rapports", command=self.open_reports).pack(side="left", padx=8)
        self.status = tk.StringVar(value="Prêt.")
        ttk.Label(small, textvariable=self.status).pack(side="right")

        logframe = ttk.LabelFrame(outer, text="Journal", padding=8)
        logframe.pack(fill="both", expand=True)
        self.logbox = tk.Text(logframe, wrap="word", font=("Consolas", 9), state="disabled")
        self.logbox.pack(side="left", fill="both", expand=True)
        scroll = ttk.Scrollbar(logframe, command=self.logbox.yview)
        scroll.pack(side="right", fill="y")
        self.logbox.configure(yscrollcommand=scroll.set)

    def _load_values(self):
        l, s, r = self.cfg["local"], self.cfg["server"], self.cfg["runtime"]
        for key in ("konstellation_root", "pack_file", "lenses_dir"):
            self.vars[key].set(l.get(key, ""))
        for key in ("host", "user", "ssh_key", "domain", "aliases", "remote_root", "konnaxion_instance"):
            self.vars[key].set(s.get(key, ""))
        for key in ("roles", "semantik_url", "runtime_set_id", "capability_profile"):
            self.vars[key].set(r.get(key, ""))
        self.vars["languages"].set(",".join(r.get("languages", ["fr"])))
        self.semantik_enabled.set(bool(r.get("semantik_enabled", False)))

    def save_values(self):
        for key in ("konstellation_root", "pack_file", "lenses_dir"):
            self.cfg["local"][key] = self.vars[key].get().strip()
        for key in ("host", "user", "ssh_key", "domain", "aliases", "remote_root", "konnaxion_instance"):
            self.cfg["server"][key] = self.vars[key].get().strip()
        instance = self.cfg["server"]["konnaxion_instance"]
        self.cfg["server"]["edge_network"] = f"kx-{instance}-public"
        for key in ("roles", "semantik_url", "runtime_set_id", "capability_profile"):
            self.cfg["runtime"][key] = self.vars[key].get().strip()
        self.cfg["runtime"]["languages"] = parse_languages(self.vars["languages"].get())
        self.cfg["runtime"]["semantik_enabled"] = bool(self.semantik_enabled.get())
        save_config(self.cfg)
        self.log("Configuration enregistrée.")

    def pick_path(self, key):
        if key in {"ssh_key", "pack_file"}:
            p = filedialog.askopenfilename(title="Choisir le fichier")
        else:
            p = filedialog.askdirectory(title="Choisir le dossier")
        if p:
            self.vars[key].set(p)

    def log(self, text):
        def write():
            self.logbox.configure(state="normal")
            self.logbox.insert("end", str(text).rstrip() + "\n")
            self.logbox.see("end")
            self.logbox.configure(state="disabled")
        self.after(0, write)

    def set_status(self, text):
        self.after(0, lambda: self.status.set(text))

    def run_bg(self, label, fn):
        self.save_values()
        def worker():
            self.set_status(label)
            try:
                fn()
            except Exception as exc:
                self.log(f"ÉCHEC — {exc}")
                self.after(0, lambda: messagebox.showerror("Konstellation Publisher", str(exc)))
            finally:
                self.set_status("Prêt.")
        threading.Thread(target=worker, daemon=True).start()

    def local_check(self):
        self.run_bg("Vérification locale…", self._local_check)

    def _local_check(self):
        root = Path(self.cfg["local"]["konstellation_root"])
        required = [
            root / "package.json", root / "server" / "index.mjs", root / "server" / "pack.mjs",
            root / "src", root / "contracts", root / "astro.config.mjs",
        ]
        missing = [str(p) for p in required if not p.exists()]
        if missing:
            raise RuntimeError("Éléments Konstellation manquants:\n" + "\n".join(missing))
        pkg = json.loads((root / "package.json").read_text(encoding="utf-8"))
        version = pkg.get("version", "?")
        engine = pkg.get("engines", {}).get("node", "")
        self.log(f"Konstellation : {root}")
        self.log(f"Version : {version} — Node requis : {engine}")
        detail = audit_checkout(root)
        self.log(f"Lockfile SHA-256: {detail['package_lock_sha256']}")
        self.log("Statut publication C1/C2/C3: NON VÉRIFIÉ (blocage volontaire)")

        pack_text = self.cfg["local"].get("pack_file", "").strip()
        assert_no_unqualified_content(pack_text, self.cfg["local"].get("lenses_dir", "").strip())
        if pack_text:
            pack = Path(pack_text)
            if not pack.is_file():
                raise RuntimeError(f"Pack JSON introuvable : {pack}")
            obj = json.loads(pack.read_text(encoding="utf-8-sig"))
            if obj.get("schemaVersion") != "0.3":
                raise RuntimeError(f"Pack non supporté: schemaVersion={obj.get('schemaVersion')!r}, attendu '0.3'.")
            self.log(
                f"Pack : {pack.name} — {len(obj.get('entities', []))} entités, "
                f"{len(obj.get('assertions', []))} assertions"
            )

        lenses_text = self.cfg["local"].get("lenses_dir", "").strip()
        if lenses_text:
            lenses = Path(lenses_text)
            if not lenses.is_dir():
                raise RuntimeError(f"Dossier Lens introuvable : {lenses}")
            lens_files = list(lenses.glob("*.json"))
            if not lens_files:
                raise RuntimeError("Aucune Lens JSON dans le dossier configuré.")
            for p in lens_files:
                json.loads(p.read_text(encoding="utf-8-sig"))
            self.log(f"Lens : {len(lens_files)} fichier(s) JSON")

        if self.cfg["runtime"].get("semantik_enabled"):
            r = self.cfg["runtime"]
            if not r.get("semantik_url") or not r.get("runtime_set_id") or not r.get("capability_profile"):
                raise RuntimeError("Intégration SemantiK activée mais configuration incomplète.")
            self.log("SemantiK : intégration activée (le Publisher ne déploie pas le serveur SemantiK lui-même).")
        else:
            self.log("SemantiK : intégration désactivée pour cette publication.")
        self.log("OK — prévol local Konstellation réussi.")

    def server_check(self):
        self.run_bg("Vérification VPS…", self._server_check)

    def _server_check(self):
        s = self.cfg["server"]
        if not s.get("domain"):
            raise RuntimeError("Renseigne le domaine Konstellation avant la vérification VPS.")
        key = Path(s["ssh_key"])
        if not key.is_file():
            raise RuntimeError(f"Clé SSH introuvable : {key}")
        if shutil.which("ssh") is None:
            raise RuntimeError("ssh.exe est introuvable dans PATH.")
        dynamic = f'{s["konnaxion_root"]}/instances/{s["konnaxion_instance"]}/state/traefik-dynamic.yml'
        cmd = (
            "set -e; printf 'SSH_OK\\n'; id; sudo -n true; printf 'SUDO_OK\\n'; "
            "sudo -n docker --version; sudo -n docker compose version; "
            f"sudo -n docker network inspect {s['edge_network']} >/dev/null; printf 'EDGE_NETWORK_OK\\n'; "
            f"sudo -n test -f {dynamic}; printf 'TRAEFIK_DYNAMIC_OK\\n'; "
            "df -h /; sudo -n docker ps --format '{{.Names}} | {{.Status}}' | head -n 30"
        )
        cp = run_process(ssh_base(self.cfg) + [cmd], timeout=70)
        if cp.stdout:
            self.log(cp.stdout)
        if cp.stderr:
            self.log(cp.stderr)
        if cp.returncode != 0:
            raise RuntimeError(f"Vérification VPS échouée (rc={cp.returncode}).")
        try:
            resolved = socket.gethostbyname(s["domain"])
            self.log(f"DNS {s['domain']} -> {resolved}")
            if resolved != s["host"]:
                self.log(f"AVERTISSEMENT — le domaine ne pointe pas encore vers le VPS {s['host']}.")
        except Exception as exc:
            self.log(f"AVERTISSEMENT DNS — {exc}")
        self.log("OK — VPS compatible avec Konstellation Publisher.")

    def prepare_package(self):
        self.run_bg("Préparation du paquet…", self._prepare_package)

    def _prepare_package(self):
        self._local_check()
        PACKAGES_DIR.mkdir(parents=True, exist_ok=True)
        stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
        bundle = PACKAGES_DIR / f"konstellation-publish-{stamp}.zip"
        result = prepare_bundle(
            checkout=Path(self.cfg["local"]["konstellation_root"]),
            project=APP_DIR, target=bundle, release_id=stamp,
            pack_file=self.cfg["local"].get("pack_file", "").strip(),
            lenses_dir=self.cfg["local"].get("lenses_dir", "").strip(),
            semantik_enabled=bool(self.cfg["runtime"].get("semantik_enabled")),
        )
        self.last_package = bundle
        self.log(f"Paquet prêt : {bundle}")
        self.log(f"SHA256 : {result['sha256']}")
        self._write_report("prepare", "Réussi", [f"Paquet: {bundle}", f"SHA256: {result['sha256']}"])

    def simulate_rollback(self):
        """Entirely local, temporary route-file simulation; never connects to VPS."""
        def simulate():
            cp = run_process([sys.executable, str(TRANSACTION_SCRIPT), "--simulate", "--fail", "public"], timeout=30)
            if cp.returncode != 0:
                raise RuntimeError(f"Simulation échouée: {cp.stderr}")
            result = json.loads(cp.stdout)
            if result.get("phase") != "ROLLED_BACK" or result.get("active") != "previous-release":
                raise RuntimeError("Simulation n'a pas confirmé la restauration du trafic précédent")
            self.log("SIMULATION OK — panne après bascule, ancien service restauré.")
            self.log("Aucun SSH/Docker/Traefik contacté.")
        self.run_bg("Simulation locale du rollback…", simulate)

    def publish(self):
        # Block before configuration, prompts, SSH or Docker calls.
        try:
            assert_live_deploy_permitted()
        except PublicationBlocked as exc:
            messagebox.showerror('Publication désactivée', str(exc))
            self.log(f'REFUS: {exc}')
            return
        self.save_values()
        s = self.cfg["server"]
        if not s.get("domain"):
            messagebox.showerror("Konstellation Publisher", "Renseigne le domaine Konstellation avant de publier.")
            return
        if not messagebox.askyesno(
            "Confirmer la publication",
            f"Cette action modifie le VPS {s['host']} et publie Konstellation sur "
            f"https://{s['domain']}.\n\nContinuer ?",
        ):
            self.log("Annulé — aucune modification serveur lancée.")
            return
        self.run_bg("Publication Konstellation…", self._publish)

    def _publish(self):
        assert_live_deploy_permitted()
        self._server_check()
        # Never reuse a stale archive or deploy from a stale snapshot.
        self._prepare_package()
        bundle_zip = self.last_package
        stamp = bundle_zip.stem.replace("konstellation-publish-", "")
        extract = Path(tempfile.mkdtemp(prefix="konstellation-upload-"))
        tar_bundle = PACKAGES_DIR / f"konstellation-publish-{stamp}.tar.gz"
        try:
            with zipfile.ZipFile(bundle_zip, "r") as zf:
                zf.extractall(extract)
            with tarfile.open(tar_bundle, "w:gz") as tf:
                for p in extract.rglob("*"):
                    if p.is_file():
                        tf.add(p, arcname=p.relative_to(extract).as_posix())
            s, r = self.cfg["server"], self.cfg["runtime"]
            remote_tmp = f"/tmp/konstellation-publisher-{stamp}.tar.gz"
            self.log(f"Envoi vers {s['user']}@{s['host']}…")
            cp = run_process(scp_base(self.cfg) + [str(tar_bundle), f'{s["user"]}@{s["host"]}:{remote_tmp}'], timeout=900)
            if cp.stdout:
                self.log(cp.stdout)
            if cp.stderr:
                self.log(cp.stderr)
            if cp.returncode != 0:
                raise RuntimeError(f"Upload SCP échoué (rc={cp.returncode}).")
            remote_stage = f"/tmp/konstellation-publisher-{stamp}"
            unpack_cmd = (
                f"rm -rf {remote_stage} && mkdir -p {remote_stage} && "
                f"tar -xzf {remote_tmp} -C {remote_stage} && rm -f {remote_tmp}"
            )
            cp = run_process(ssh_base(self.cfg) + [unpack_cmd], timeout=180)
            if cp.returncode != 0:
                raise RuntimeError("Extraction distante du paquet échouée.")
            payload = {
                "bundle_dir": remote_stage,
                "release_id": stamp,
                "remote_root": s["remote_root"],
                "domain": s["domain"],
                "aliases": s.get("aliases", ""),
                "konnaxion_root": s["konnaxion_root"],
                "konnaxion_instance": s["konnaxion_instance"],
                "edge_network": s["edge_network"],
                "server_host": s.get("host", ""),
                "roles": r.get("roles", "public"),
                "semantik_enabled": bool(r.get("semantik_enabled")),
                "semantik_url": r.get("semantik_url", ""),
                "runtime_set_id": r.get("runtime_set_id", ""),
                "capability_profile": r.get("capability_profile", "konstellation-explorer-2"),
                "languages": r.get("languages", ["fr"]),
                "sa_gf_contract_version": r.get("sa_gf_contract_version", "1.0"),
                "timeout_ms": r.get("timeout_ms", 10000),
                "max_assertions": r.get("max_assertions", 200),
            }
            remote_cmd = f"sudo -n python3 {remote_stage}/deploy_remote.py"
            cp = run_process(
                ssh_base(self.cfg) + [remote_cmd], timeout=3600,
                input_text=json.dumps(payload, ensure_ascii=False),
            )
            if cp.stdout:
                self.log(cp.stdout)
            if cp.stderr:
                self.log(cp.stderr)
            if cp.returncode != 0 or "KONSTELLATION_PUBLISH_RESULT=OK" not in (cp.stdout or ""):
                raise RuntimeError(f"Publication distante échouée (rc={cp.returncode}).")
            self.log("OK — Konstellation a été publié sur le VPS.")
            self.log(f"URL : https://{s['domain']}")
            self._write_report("publish", "Réussi", [f"Release: {stamp}", f"URL: https://{s['domain']}", f"VPS: {s['host']}"])
        finally:
            shutil.rmtree(extract, ignore_errors=True)

    def verify_online(self):
        self.run_bg("Vérification en ligne…", self._verify_online)

    def _verify_online(self):
        domain = self.cfg["server"].get("domain", "").strip()
        if not domain:
            raise RuntimeError("Domaine Konstellation non configuré.")
        base = f"https://{domain}"
        urls = [base + "/", base + "/api/health", base + "/api/bootstrap", base + "/api/capabilities"]
        errors = []
        for url in urls:
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "Konstellation-Publisher/0.2.0-alpha.2"})
                with urllib.request.urlopen(req, timeout=30) as resp:
                    code = resp.getcode()
                    body = resp.read(8192)
                self.log(f"HTTP {code} — {url} — {len(body)} octets lus")
                if not (200 <= code < 400):
                    errors.append(f"{url}: HTTP {code}")
            except Exception as exc:
                errors.append(f"{url}: {exc}")
                self.log(f"ÉCHEC — {url} — {exc}")
        if errors:
            self._write_report("verify", "Échoué", errors)
            raise RuntimeError("Une ou plusieurs routes Konstellation ne répondent pas correctement.")
        self.log("OK — Konstellation répond en HTTPS et l'API est saine.")
        self._write_report("verify", "Réussi", urls)

    def _write_report(self, action, status, lines):
        REPORTS_DIR.mkdir(parents=True, exist_ok=True)
        stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
        path = REPORTS_DIR / f"{stamp}_{action}.md"
        text = [
            "# Konstellation Publisher — rapport", "",
            f"- Action : {action}", f"- Statut : {status}", f"- Date : {dt.datetime.now().isoformat()}",
            "", "## Détails", "",
        ] + [f"- {line}" for line in lines]
        path.write_text("\n".join(text) + "\n", encoding="utf-8")
        self.log(f"Rapport : {path}")

    def open_reports(self):
        REPORTS_DIR.mkdir(parents=True, exist_ok=True)
        if os.name == "nt":
            os.startfile(REPORTS_DIR)
        else:
            subprocess.Popen(["xdg-open", str(REPORTS_DIR)])


def self_test():
    required = [
        APP_DIR / "konstellation_publisher.config.example.json", REMOTE_SCRIPT,
        TEMPLATES_DIR / "Dockerfile", TEMPLATES_DIR / "docker-compose.yml", TRANSACTION_SCRIPT, APP_DIR / "publisher_bundle.py",
    ]
    missing = [str(p) for p in required if not p.exists()]
    if missing:
        print("MISSING")
        print("\n".join(missing))
        return 2
    cfg = load_config()
    assert 'server' in cfg and 'runtime' in cfg and 'local' in cfg
    assert cfg['runtime']['roles'] == 'public'
    assert (APP_DIR / 'publisher_safety.py').is_file()
    print("SELF_TEST_OK")
    return 0


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        raise SystemExit(self_test())
    PublisherApp().mainloop()
