#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
model_fetcher.py - Optional GGUF model downloader for qidong (stdlib only).

Helps new users download GGUF models directly into `models/` without needing
huggingface-cli or git-lfs. Supports:
  * Official Hugging Face (Global) and hf-mirror.com (Mainland China)
  * Dynamic live file listing via /api/models/<repo>/tree/main (never stale)
  * Automatic multi-part split GGUF download (downloads all shards together)
  * Direct .gguf URL download (Hugging Face, ModelScope, custom mirrors)
  * Resumable downloads (.part + HTTP Range), curl.exe fallback & SHA-256 check
"""

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_MODELS_DIR = os.path.join(BASE_DIR, "models")
USER_AGENT = "qidong-model-fetcher/1.0"
CREATE_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0

ENDPOINTS = {
    "global": "https://huggingface.co",
    "cn": "https://hf-mirror.com",
}

CURATED_REPOS = [
    ("Qwen/Qwen2.5-3B-Instruct-GGUF", "Qwen 2.5 3B Instruct (Lightweight, 4GB+ VRAM or CPU)"),
    ("Qwen/Qwen2.5-7B-Instruct-GGUF", "Qwen 2.5 7B Instruct (Balanced, 6-8GB VRAM)"),
    ("bartowski/Llama-3.2-3B-Instruct-GGUF", "Llama 3.2 3B Instruct (Fast English/Multilingual)"),
    ("bartowski/Meta-Llama-3.1-8B-Instruct-GGUF", "Llama 3.1 8B Instruct (All-round 8B, 6-8GB VRAM)"),
    ("bartowski/gemma-2-2b-it-GGUF", "Gemma 2 2B IT (Ultra-lightweight, runs anywhere)"),
]

SPLIT_RE = re.compile(r"^(?P<base>.+)-(?P<part>\d{5})-of-(?P<total>\d{5})\.gguf$", re.IGNORECASE)

EXIT_OK, EXIT_ERROR, EXIT_CANCEL = 0, 1, 2
_ASSUME_YES = False


def out(msg=""):
    try:
        print(msg, flush=True)
    except UnicodeEncodeError:
        print(msg.encode("ascii", "replace").decode("ascii"), flush=True)


def human_size(n):
    n = float(n or 0)
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return ("%.0f %s" % (n, unit)) if unit == "B" else ("%.2f %s" % (n, unit))
        n /= 1024.0


def confirm(question, default=True):
    if _ASSUME_YES:
        return True
    suffix = " [Y/n]: " if default else " [y/N]: "
    try:
        ans = input(question + suffix).strip().lower()
    except (EOFError, KeyboardInterrupt):
        out("")
        return False
    if not ans:
        return default
    return ans in ("y", "yes")


def resolve_endpoint(mirror_opt=None):
    env_ep = (os.environ.get("HF_ENDPOINT") or "").strip().rstrip("/")
    if not mirror_opt:
        return env_ep or ENDPOINTS["global"]
    low = mirror_opt.strip().lower()
    if low in ENDPOINTS:
        return ENDPOINTS[low]
    if low.startswith(("http://", "https://")):
        return mirror_opt.strip().rstrip("/")
    return ENDPOINTS["global"]


def _request_headers(extra=None):
    headers = {"User-Agent": USER_AGENT}
    token = os.environ.get("HF_TOKEN") or os.environ.get("HUGGINGFACE_HUB_TOKEN")
    if token:
        headers["Authorization"] = "Bearer " + token.strip()
    if extra:
        headers.update(extra)
    return headers


def list_repo_ggufs(repo_id, endpoint):
    """Query Hugging Face tree API recursively (depth 2) and return GGUF entries."""
    repo_clean = repo_id.strip().strip("/")
    url = "%s/api/models/%s/tree/main?recursive=true" % (endpoint.rstrip("/"), repo_clean)
    last_err = None
    data = None
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, headers=_request_headers({"Accept": "application/json"}))
            with urllib.request.urlopen(req, timeout=25) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            break
        except urllib.error.HTTPError as e:
            last_err = e
            if e.code in (401, 403, 404):
                break
        except Exception as e:
            last_err = e
        time.sleep(1.2 * (attempt + 1))

    if data is None:
        raise RuntimeError(
            "Failed to query %s (%s). Check network/repo name or try --mirror cn / --mirror global."
            % (url, last_err)
        )

    files = []
    for item in data:
        if item.get("type") != "file":
            continue
        path = item.get("path", "")
        if not path.lower().endswith(".gguf"):
            continue
        lfs = item.get("lfs") or {}
        size = int(lfs.get("size") or item.get("size") or 0)
        sha256 = lfs.get("oid") or None
        files.append({
            "path": path,
            "name": os.path.basename(path),
            "size": size,
            "sha256": sha256,
            "url": "%s/%s/resolve/main/%s" % (
                endpoint.rstrip("/"),
                repo_clean,
                urllib.parse.quote(path, safe="/"),
            ),
        })
    files.sort(key=lambda x: x["path"].lower())
    return files


def group_gguf_entries(files):
    """Collapse multi-part split GGUFs into single selectable bundles."""
    by_name = {f["name"]: f for f in files}
    bundles = []
    consumed = set()
    for f in files:
        if f["name"] in consumed:
            continue
        m = SPLIT_RE.match(f["name"])
        if m:
            base = m.group("base")
            total = int(m.group("total"))
            shards = []
            for other in files:
                om = SPLIT_RE.match(other["name"])
                if om and om.group("base").lower() == base.lower() and int(om.group("total")) == total:
                    shards.append((int(om.group("part")), other))
            shards.sort(key=lambda x: x[0])
            shard_files = [s[1] for s in shards]
            for sf in shard_files:
                consumed.add(sf["name"])
            bundles.append({
                "label": "%s (%d-part split)" % (shard_files[0]["name"], len(shard_files)),
                "primary_name": shard_files[0]["name"],
                "total_size": sum(sf["size"] for sf in shard_files),
                "files": shard_files,
                "is_mmproj": "mmproj" in base.lower(),
            })
        else:
            consumed.add(f["name"])
            bundles.append({
                "label": f["name"],
                "primary_name": f["name"],
                "total_size": f["size"],
                "files": [f],
                "is_mmproj": "mmproj" in f["name"].lower(),
            })
    return bundles


def _sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as fp:
        while True:
            chunk = fp.read(1024 * 1024)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest().lower()


def _download_with_curl(url, part_path):
    curl = shutil.which("curl.exe") or shutil.which("curl")
    if not curl:
        return False
    cmd = [curl, "-fL", "-C", "-", "--progress-bar", "-o", part_path, "-A", USER_AGENT]
    token = os.environ.get("HF_TOKEN") or os.environ.get("HUGGINGFACE_HUB_TOKEN")
    if token:
        cmd += ["-H", "Authorization: Bearer " + token.strip()]
    cmd.append(url)
    try:
        res = subprocess.run(cmd)
        return res.returncode == 0 and os.path.exists(part_path) and os.path.getsize(part_path) > 0
    except Exception:
        return False


def download_file(url, dest_path, expected_size=0, expected_sha256=None):
    os.makedirs(os.path.dirname(os.path.abspath(dest_path)), exist_ok=True)
    if os.path.exists(dest_path) and (not expected_size or os.path.getsize(dest_path) == expected_size):
        out("  Already exists: %s (%s)" % (os.path.basename(dest_path), human_size(os.path.getsize(dest_path))))
        return True

    part_path = dest_path + ".part"
    out("  Downloading: %s" % os.path.basename(dest_path))
    out("  URL        : %s" % url)

    success = False
    last_err = None
    for attempt in range(3):
        existing = os.path.getsize(part_path) if os.path.exists(part_path) else 0
        extra = {"Range": "bytes=%d-" % existing} if existing > 0 else {}
        req = urllib.request.Request(url, headers=_request_headers(extra))
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                status = getattr(resp, "status", 200)
                if existing > 0 and status != 206:
                    existing = 0
                cl = resp.headers.get("Content-Length")
                total = (existing + int(cl)) if (cl and cl.isdigit()) else expected_size
                mode = "ab" if existing > 0 else "wb"
                done = existing
                t0 = time.time()
                last_print = 0.0
                with open(part_path, mode) as fp:
                    while True:
                        chunk = resp.read(256 * 1024)
                        if not chunk:
                            break
                        fp.write(chunk)
                        done += len(chunk)
                        now = time.time()
                        if now - last_print >= 0.4 or (total and done >= total):
                            elapsed = max(0.001, now - t0)
                            speed = (done - existing) / elapsed
                            if total:
                                pct = min(100.0, done * 100.0 / total)
                                sys.stdout.write("\r  Progress: %5.1f%%  %s / %s  (%s/s)   " % (
                                    pct, human_size(done), human_size(total), human_size(speed)
                                ))
                            else:
                                sys.stdout.write("\r  Downloaded: %s  (%s/s)   " % (
                                    human_size(done), human_size(speed)
                                ))
                            sys.stdout.flush()
                            last_print = now
                sys.stdout.write("\n")
                sys.stdout.flush()
                success = True
                break
        except urllib.error.HTTPError as e:
            last_err = e
            if e.code == 416 and expected_size and existing >= expected_size:
                success = True
                break
            if e.code in (401, 403, 404):
                break
        except Exception as e:
            last_err = e
        time.sleep(1.5 * (attempt + 1))

    if not success:
        out("  urllib download failed (%s), trying curl.exe fallback..." % last_err)
        if not _download_with_curl(url, part_path):
            out("  [Error] Download failed for %s" % os.path.basename(dest_path))
            return False

    if expected_sha256 and len(expected_sha256) == 64:
        out("  Verifying SHA-256...")
        actual = _sha256_file(part_path)
        if actual != expected_sha256.lower():
            out("  [Error] SHA-256 mismatch! Expected %s, got %s" % (expected_sha256[:16], actual[:16]))
            return False
        out("  SHA-256 OK.")

    os.replace(part_path, dest_path)
    out("  [OK] Saved to: %s" % dest_path)
    return True


def _recommend_badge(name):
    low = name.lower()
    if "q4_k_m" in low:
        return " [Recommended - Balanced]"
    if "q5_k_m" in low or "q6_k" in low:
        return " [High Quality]"
    if "q8_0" in low:
        return " [Near Lossless]"
    if "mmproj" in low:
        return " [Vision Projector]"
    return ""


def cmd_list(args):
    endpoint = resolve_endpoint(args.mirror)
    out("Querying %s on %s ..." % (args.repo, endpoint))
    try:
        files = list_repo_ggufs(args.repo, endpoint)
    except RuntimeError as e:
        out("[Error] " + str(e))
        return EXIT_ERROR
    if not files:
        out("No .gguf files found in %s." % args.repo)
        return EXIT_ERROR
    bundles = group_gguf_entries(files)
    for idx, b in enumerate(bundles, 1):
        out("  [%2d] %-52s %10s%s" % (idx, b["label"], human_size(b["total_size"]), _recommend_badge(b["primary_name"])))
    return EXIT_OK


def download_bundle(bundle, target_dir):
    for f in bundle["files"]:
        dest = os.path.join(target_dir, f["name"])
        if not download_file(f["url"], dest, expected_size=f["size"], expected_sha256=f["sha256"]):
            return False
    return True


def cmd_download(args):
    target_dir = os.path.abspath(args.dir)
    os.makedirs(target_dir, exist_ok=True)
    src = args.source.strip()

    if src.lower().startswith(("http://", "https://")):
        parsed = urllib.parse.urlparse(src)
        filename = args.file or os.path.basename(urllib.parse.unquote(parsed.path)) or "downloaded_model.gguf"
        if not filename.lower().endswith(".gguf"):
            filename += ".gguf"
        dest = os.path.join(target_dir, filename)
        if not confirm("Download %s into %s ?" % (filename, target_dir)):
            return EXIT_CANCEL
        return EXIT_OK if download_file(src, dest) else EXIT_ERROR

    endpoint = resolve_endpoint(args.mirror)
    try:
        files = list_repo_ggufs(src, endpoint)
    except RuntimeError as e:
        out("[Error] " + str(e))
        return EXIT_ERROR
    bundles = group_gguf_entries(files)
    if not bundles:
        out("[Error] No .gguf files found in %s." % src)
        return EXIT_ERROR

    chosen = None
    if args.file:
        want = args.file.strip().lower()
        for b in bundles:
            if b["primary_name"].lower() == want or want in b["primary_name"].lower():
                chosen = b
                break
        if not chosen:
            out("[Error] File matching '%s' not found in %s." % (args.file, src))
            return EXIT_ERROR
    else:
        for idx, b in enumerate(bundles, 1):
            out("  [%2d] %-52s %10s%s" % (idx, b["label"], human_size(b["total_size"]), _recommend_badge(b["primary_name"])))
        try:
            sel = input("\nSelect file number (0 to cancel): ").strip()
        except (EOFError, KeyboardInterrupt):
            return EXIT_CANCEL
        if not sel.isdigit() or not (1 <= int(sel) <= len(bundles)):
            return EXIT_CANCEL
        chosen = bundles[int(sel) - 1]

    out("\nTarget directory: %s" % target_dir)
    out("Selected model  : %s (%s)" % (chosen["label"], human_size(chosen["total_size"])))
    if not confirm("Start download?"):
        return EXIT_CANCEL
    return EXIT_OK if download_bundle(chosen, target_dir) else EXIT_ERROR


def cmd_menu(args):
    target_dir = os.path.abspath(args.dir)
    os.makedirs(target_dir, exist_ok=True)
    endpoint = resolve_endpoint(args.mirror)

    while True:
        out("=" * 64)
        out("             GGUF Model Downloader (Hugging Face)")
        out("=" * 64)
        out("  Save directory  : %s" % target_dir)
        out("  Active endpoint : %s" % endpoint)
        out("-" * 64)
        out("  Curated Starter GGUF Repositories:")
        for idx, (repo, desc) in enumerate(CURATED_REPOS, 1):
            out("   [%d] %s" % (idx, repo))
            out("       %s" % desc)
        out("-" * 64)
        out("   [C] Enter custom Hugging Face repo ID (e.g. owner/repo-GGUF)")
        out("   [U] Download from any direct .gguf URL (HF / ModelScope / etc.)")
        out("   [M] Switch Mirror: Global (huggingface.co) <-> China (hf-mirror.com)")
        out("   [0] Back")
        out("=" * 64)
        try:
            choice = input("Select option: ").strip()
        except (EOFError, KeyboardInterrupt):
            return EXIT_CANCEL

        if not choice or choice == "0":
            return EXIT_OK

        if choice.upper() == "M":
            endpoint = ENDPOINTS["cn"] if endpoint == ENDPOINTS["global"] else ENDPOINTS["global"]
            out("\nSwitched endpoint to: %s\n" % endpoint)
            continue

        if choice.upper() == "U":
            try:
                raw_url = input("\nPaste direct .gguf URL (empty to cancel): ").strip()
            except (EOFError, KeyboardInterrupt):
                continue
            if not raw_url:
                continue
            parsed = urllib.parse.urlparse(raw_url)
            fn = os.path.basename(urllib.parse.unquote(parsed.path)) or "downloaded_model.gguf"
            if not fn.lower().endswith(".gguf"):
                fn += ".gguf"
            download_file(raw_url, os.path.join(target_dir, fn))
            continue

        repo = None
        if choice.upper() == "C":
            try:
                repo = input("\nEnter Hugging Face repo ID (e.g. Qwen/Qwen2.5-7B-Instruct-GGUF): ").strip()
            except (EOFError, KeyboardInterrupt):
                continue
        elif choice.isdigit() and 1 <= int(choice) <= len(CURATED_REPOS):
            repo = CURATED_REPOS[int(choice) - 1][0]
        else:
            out("Invalid choice.")
            continue

        if not repo:
            continue

        out("\nFetching GGUF file list from %s/%s ..." % (endpoint, repo))
        try:
            files = list_repo_ggufs(repo, endpoint)
        except RuntimeError as e:
            out("[Error] " + str(e))
            out("[Tip] If you are in Mainland China, press [M] to switch to hf-mirror.com.\n")
            continue

        bundles = group_gguf_entries(files)
        if not bundles:
            out("No .gguf files found in this repository.\n")
            continue

        out("")
        for idx, b in enumerate(bundles, 1):
            out("  [%2d] %-50s %10s%s" % (idx, b["label"], human_size(b["total_size"]), _recommend_badge(b["primary_name"])))
        try:
            sel = input("\nSelect quantization number to download (0 to cancel): ").strip()
        except (EOFError, KeyboardInterrupt):
            continue
        if not sel.isdigit() or not (1 <= int(sel) <= len(bundles)):
            continue
        chosen = bundles[int(sel) - 1]
        if confirm("Download %s (%s) into %s ?" % (chosen["label"], human_size(chosen["total_size"]), target_dir)):
            download_bundle(chosen, target_dir)
            out("")


def build_parser():
    p = argparse.ArgumentParser(description="Optional GGUF model downloader for qidong")
    sub = p.add_subparsers(dest="command")

    def common(sp):
        sp.add_argument("--dir", default=DEFAULT_MODELS_DIR, help="target models folder")
        sp.add_argument("--mirror", default=None, help="global | cn | custom https:// endpoint")
        sp.add_argument("-y", "--yes", action="store_true", help="skip confirmations")

    sp_menu = sub.add_parser("menu", help="interactive model downloader menu")
    common(sp_menu)

    sp_list = sub.add_parser("list", help="list .gguf files in a Hugging Face repo")
    sp_list.add_argument("repo", help="Hugging Face repo ID, e.g. Qwen/Qwen2.5-3B-Instruct-GGUF")
    common(sp_list)

    sp_dl = sub.add_parser("download", help="download a GGUF from a HF repo or direct URL")
    sp_dl.add_argument("source", help="Hugging Face repo ID or direct .gguf URL")
    sp_dl.add_argument("--file", default=None, help="specific .gguf filename or substring")
    common(sp_dl)
    return p


def main(argv=None):
    global _ASSUME_YES
    parser = build_parser()
    args = parser.parse_args(argv)
    if not args.command:
        args = parser.parse_args(["menu"])
    _ASSUME_YES = bool(getattr(args, "yes", False))
    handlers = {"menu": cmd_menu, "list": cmd_list, "download": cmd_download}
    try:
        return handlers[args.command](args)
    except KeyboardInterrupt:
        out("\nCancelled.")
        return EXIT_CANCEL


if __name__ == "__main__":
    sys.exit(main())
