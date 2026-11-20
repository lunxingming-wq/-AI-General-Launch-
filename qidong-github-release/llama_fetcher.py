#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
llama_fetcher.py - automatic llama.cpp engine installer / updater for Windows.

Detects the user's hardware (NVIDIA / AMD / Intel / CPU-only, x64 / arm64,
driver CUDA version, GPU compute capability) and downloads the matching
prebuilt `llama-server` package (plus the matching `cudart` runtime for CUDA
builds) from the official llama.cpp GitHub releases.

Standard library only. Features:
  * hardware-aware package selection (CUDA 12.x / 13.x / Vulkan / CPU / ...)
  * newest release that actually contains the needed assets
  * resumable downloads, SHA-256 verification, staged extraction
  * install record (.llama_install.json) and update checks
  * optional mirror prefix and GITHUB_TOKEN support

Commands:
  info      show detected hardware, installed build and the recommended package
  install   download and install (default: newest compatible release)
  update    install only if a newer build is available
  ensure    install only if llama-server.exe is missing (used by qidong.bat)
  menu      interactive engine manager (used by qidong.bat)
  list      list the Windows packages available in a release
"""

import argparse
import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import zipfile

REPO = "ggml-org/llama.cpp"
API_RELEASES = "https://api.github.com/repos/%s/releases" % REPO
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATE_FILE = ".llama_install.json"
CACHE_DIRNAME = ".llama_cache"
USER_AGENT = "qidong-llama-fetcher/1.0"
CREATE_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0

ENGINE_RE = re.compile(r"^llama-(?P<tag>.+?)-bin-win-(?P<variant>.+)-(?P<arch>x64|arm64)\.zip$")
CUDART_RE = re.compile(r"^cudart-llama-bin-win-cuda-(?P<ver>[\d.]+)-(?P<arch>x64|arm64)\.zip$")

EXIT_OK, EXIT_ERROR, EXIT_CANCEL = 0, 1, 2

_ASSUME_YES = False


# ----------------------------------------------------------------------------
# small helpers
# ----------------------------------------------------------------------------
def out(msg=""):
    try:
        print(msg, flush=True)
    except UnicodeEncodeError:
        print(msg.encode("ascii", "replace").decode("ascii"), flush=True)


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


def human_size(n):
    n = float(n)
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return ("%.0f %s" % (n, unit)) if unit == "B" else ("%.1f %s" % (n, unit))
        n /= 1024.0


def tag_number(tag):
    digits = re.sub(r"\D", "", tag or "")
    return int(digits) if digits else 0


def ver_tuple(ver):
    try:
        return tuple(int(p) for p in str(ver).split("."))
    except ValueError:
        return (0,)


def run_cmd(cmd, timeout=12, merge_stderr=False):
    try:
        return subprocess.check_output(
            cmd,
            stderr=subprocess.STDOUT if merge_stderr else subprocess.DEVNULL,
            timeout=timeout,
            creationflags=CREATE_NO_WINDOW,
        ).decode("utf-8", "ignore")
    except Exception:
        return ""


# ----------------------------------------------------------------------------
# hardware detection
# ----------------------------------------------------------------------------
def detect_arch():
    machine = (
        os.environ.get("PROCESSOR_ARCHITEW6432")
        or os.environ.get("PROCESSOR_ARCHITECTURE")
        or platform.machine()
        or ""
    ).upper()
    return "arm64" if ("ARM64" in machine or "AARCH64" in machine) else "x64"


def _find_nvidia_smi():
    candidates = [
        "nvidia-smi",
        r"C:\Windows\System32\nvidia-smi.exe",
        r"C:\Program Files\NVIDIA Corporation\NVSMI\nvidia-smi.exe",
    ]
    for exe in candidates:
        if run_cmd([exe, "-L"], timeout=8).strip():
            return exe
    return None


def detect_nvidia():
    exe = _find_nvidia_smi()
    if not exe:
        return None
    text = run_cmd(
        [exe, "--query-gpu=name,driver_version,compute_cap", "--format=csv,noheader"]
    )
    has_cc = bool(text.strip())
    if not has_cc:  # older drivers do not know the compute_cap field
        text = run_cmd([exe, "--query-gpu=name,driver_version", "--format=csv,noheader"])
    gpus = []
    for line in text.strip().splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) >= 2:
            cc = None
            if has_cc and len(parts) >= 3:
                try:
                    cc = float(parts[2])
                except ValueError:
                    cc = None
            gpus.append({"name": parts[0], "driver": parts[1], "cc": cc})
    if not gpus:
        return None
    header = run_cmd([exe])
    # older drivers print "CUDA Version:", newer ones "CUDA UMD Version:"
    m = re.search(r"CUDA(?:\s+UMD)?\s+Version:\s*([\d.]+)", header)
    ccs = [g["cc"] for g in gpus if g["cc"] is not None]
    return {
        "gpus": gpus,
        "driver": gpus[0]["driver"],
        "cuda": m.group(1) if m else None,
        "min_cc": min(ccs) if ccs else None,
    }


def detect_video_controllers():
    text = run_cmd(
        ["powershell", "-NoProfile", "-Command",
         "Get-CimInstance Win32_VideoController | Select-Object -ExpandProperty Name"],
        timeout=20,
    )
    names = [ln.strip() for ln in text.splitlines() if ln.strip()]
    result = []
    for n in names:
        low = n.lower()
        if any(x in low for x in ("microsoft basic", "remote", "virtual", "vmware", "hyper-v")):
            continue
        result.append(n)
    return result


def detect_hardware():
    hw = {"arch": detect_arch(), "nvidia": detect_nvidia(), "amd": [], "intel": [], "qualcomm": [], "other": []}
    for n in detect_video_controllers():
        low = n.lower()
        if "nvidia" in low:
            continue
        if "amd" in low or "radeon" in low:
            hw["amd"].append(n)
        elif "intel" in low:
            hw["intel"].append(n)
        elif "qualcomm" in low or "adreno" in low:
            hw["qualcomm"].append(n)
        else:
            hw["other"].append(n)
    return hw


def describe_hardware(hw):
    lines = ["Architecture : %s" % hw["arch"]]
    nv = hw["nvidia"]
    if nv:
        for g in nv["gpus"]:
            cc = ("compute %.1f" % g["cc"]) if g["cc"] is not None else "compute n/a"
            lines.append("NVIDIA GPU   : %s (%s)" % (g["name"], cc))
        lines.append("NVIDIA driver: %s (supports CUDA %s)" % (nv["driver"], nv["cuda"] or "unknown"))
    for key, label in (("amd", "AMD GPU"), ("intel", "Intel GPU"), ("qualcomm", "Qualcomm GPU"), ("other", "Other GPU")):
        for n in hw[key]:
            lines.append("%-13s: %s" % (label, n))
    if not nv and not (hw["amd"] or hw["intel"] or hw["qualcomm"] or hw["other"]):
        lines.append("GPU          : none detected (CPU build will be used)")
    return "\n".join(lines)


# ----------------------------------------------------------------------------
# GitHub release handling
# ----------------------------------------------------------------------------
def http_json(url):
    headers = {"User-Agent": USER_AGENT, "Accept": "application/vnd.github+json"}
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if token:
        headers["Authorization"] = "Bearer " + token
    last_err = None
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            last_err = e
            if e.code in (403, 429):
                raise RuntimeError(
                    "GitHub API rate limit reached. Wait a while, set the GITHUB_TOKEN "
                    "environment variable, or retry later."
                )
        except Exception as e:  # network error
            last_err = e
        time.sleep(1.5 * (attempt + 1))
    raise RuntimeError("Cannot reach GitHub (%s). Check your network/proxy or use --mirror." % last_err)


def iter_releases(max_pages=3):
    for page in range(1, max_pages + 1):
        data = http_json("%s?per_page=30&page=%d" % (API_RELEASES, page))
        if not data:
            return
        for rel in data:
            yield rel


def parse_release_assets(release, arch):
    engines, cudarts = {}, {}
    for a in release.get("assets", []):
        name = a.get("name", "")
        if a.get("state", "uploaded") != "uploaded":
            continue
        m = ENGINE_RE.match(name)
        if m and m.group("arch") == arch:
            engines[m.group("variant")] = a
            continue
        m = CUDART_RE.match(name)
        if m and m.group("arch") == arch:
            cudarts[m.group("ver")] = a
    return engines, cudarts


def split_variant(variant):
    """'cuda-13.5' -> ('cuda', '13.5'); 'vulkan' -> ('vulkan', '')."""
    m = re.match(r"^([a-z]+)(?:-(.+))?$", variant)
    return (m.group(1), m.group(2) or "") if m else (variant, "")


def pick_cuda(engines, cudarts, nv, notes):
    options = []
    for variant in engines:
        fam, ver = split_variant(variant)
        if fam == "cuda" and ver in cudarts:
            options.append((ver_tuple(ver), variant, ver))
    if not options:
        return None
    max_major = None
    if nv and nv.get("cuda"):
        max_major = ver_tuple(nv["cuda"])[0]
    if max_major is None:
        # driver CUDA version unknown: choose the oldest (most compatible) build
        notes.append("Driver CUDA version could not be detected; choosing the most compatible CUDA build.")
        return sorted(options)[0][1]
    legacy_gpu = bool(nv and nv.get("min_cc") is not None and nv["min_cc"] < 7.5)
    filtered = []
    for vt, variant, ver in options:
        if vt[0] > max_major:
            continue
        if legacy_gpu and vt[0] >= 13:
            continue
        filtered.append((vt, variant, ver))
    if legacy_gpu:
        notes.append("GPU compute capability %.1f is below 7.5: CUDA 13 builds dropped it, using CUDA 12.x." % nv["min_cc"])
    if not filtered:
        notes.append("Driver supports CUDA %s only; no matching CUDA build in this release." % nv["cuda"])
        return None
    filtered.sort()
    return filtered[-1][1]


def build_plan(release, hw, variant_pref="auto"):
    """Return a plan dict for this release, or None if the release cannot satisfy it."""
    engines, cudarts = parse_release_assets(release, hw["arch"])
    if not engines:
        return None
    notes = []
    chosen = None
    pref = (variant_pref or "auto").lower()

    if pref != "auto":
        if pref in engines:
            chosen = pref
        else:
            fam_matches = [v for v in engines if split_variant(v)[0] == pref]
            if pref == "cuda":
                chosen = pick_cuda(engines, cudarts, hw["nvidia"], notes) or (sorted(fam_matches, key=lambda v: ver_tuple(split_variant(v)[1]))[-1] if fam_matches else None)
            elif fam_matches:
                chosen = sorted(fam_matches, key=lambda v: ver_tuple(split_variant(v)[1]))[-1]
        if not chosen:
            return None
        notes.append("Variant chosen manually: %s." % chosen)
    else:
        order = []
        if hw["nvidia"]:
            order = ["cuda", "vulkan", "cpu"]
        elif hw["qualcomm"] and hw["arch"] == "arm64":
            order = ["opencl-adreno", "vulkan", "cpu"]
        elif hw["amd"] or hw["intel"] or hw["other"]:
            order = ["vulkan", "cpu"]
        else:
            order = ["cpu"]
        for cand in order:
            if cand == "cuda":
                chosen = pick_cuda(engines, cudarts, hw["nvidia"], notes)
            elif cand in engines:
                chosen = cand
            if chosen:
                if cand != order[0]:
                    notes.append("Falling back to the %s build." % cand)
                break
        if not chosen:
            return None

    fam, ver = split_variant(chosen)
    cudart = cudarts.get(ver) if fam == "cuda" else None
    if fam == "cuda" and cudart is None:
        return None
    return {
        "tag": release["tag_name"],
        "variant": chosen,
        "engine": engines[chosen],
        "cudart": cudart,
        "notes": notes,
        "arch": hw["arch"],
    }


def find_plan(hw, variant_pref="auto", tag=None):
    for rel in iter_releases():
        if tag and rel["tag_name"].lower() != tag.lower():
            continue
        plan = build_plan(rel, hw, variant_pref)
        if plan:
            return plan
        if tag:
            break
    return None


# ----------------------------------------------------------------------------
# installed build info
# ----------------------------------------------------------------------------
def read_state(target):
    p = os.path.join(target, STATE_FILE)
    if os.path.exists(p):
        try:
            with open(p, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return None
    return None


def installed_info(target):
    exe = os.path.join(target, "llama-server.exe")
    if not os.path.exists(exe):
        return None
    info = {"exe": exe, "tag": None, "variant": None, "version_text": ""}
    st = read_state(target)
    if st:
        info["tag"] = st.get("tag")
        info["variant"] = st.get("variant")
    text = run_cmd([exe, "--version"], timeout=15, merge_stderr=True)
    info["version_text"] = " ".join(text.split())[:160]
    m = re.search(r"build\s+(\d+)", text)
    if m and not info["tag"]:
        info["tag"] = "b" + m.group(1)
    return info


def is_server_running():
    text = run_cmd(["tasklist", "/FI", "IMAGENAME eq llama-server.exe", "/FO", "CSV", "/NH"])
    return "llama-server.exe" in text.lower()


# ----------------------------------------------------------------------------
# download / verify / extract
# ----------------------------------------------------------------------------
def sha256_of(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def expected_sha(asset):
    d = asset.get("digest") or ""
    return d.split(":", 1)[1].lower() if d.startswith("sha256:") else None


def file_ok(path, asset):
    if not os.path.exists(path) or os.path.getsize(path) != asset.get("size"):
        return False
    want = expected_sha(asset)
    return True if not want else sha256_of(path) == want


def _download_with_curl(url, part, total):
    curl_exe = shutil.which("curl.exe") or (r"C:\Windows\System32\curl.exe" if os.path.exists(r"C:\Windows\System32\curl.exe") else None)
    if not curl_exe:
        return False
    cmd = [
        curl_exe, "-L", "-f", "--retry", "3", "--retry-delay", "2",
        "-C", "-", "-#", "-A", USER_AGENT, "-o", part, url,
    ]
    res = subprocess.run(cmd)
    if res.returncode == 0 and (not total or (os.path.exists(part) and os.path.getsize(part) == total)):
        return True
    return False


def download_asset(asset, dest, mirror=None):
    url = asset["browser_download_url"]
    if mirror:
        url = mirror.rstrip("/") + "/" + url
    total = asset.get("size") or 0
    part = dest + ".part"
    if file_ok(dest, asset):
        out("  Using cached %s" % os.path.basename(dest))
        return

    downloaded = False
    for attempt in range(1, 4):
        resume = os.path.getsize(part) if os.path.exists(part) else 0
        headers = {"User-Agent": USER_AGENT, "Accept": "*/*"}
        if resume:
            headers["Range"] = "bytes=%d-" % resume
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=40) as resp:
                if resume and resp.status != 206:
                    resume = 0  # server ignored Range, start over
                mode = "ab" if resume else "wb"
                done = resume
                t0, last = time.time(), 0.0
                with open(part, mode) as f:
                    while True:
                        chunk = resp.read(256 * 1024)
                        if not chunk:
                            break
                        f.write(chunk)
                        done += len(chunk)
                        now = time.time()
                        if now - last > 0.25:
                            last = now
                            speed = (done - resume) / max(now - t0, 0.001)
                            pct = (done * 100.0 / total) if total else 0
                            bar = "#" * int(pct / 100 * 28)
                            sys.stdout.write("\r  [%-28s] %5.1f%%  %s / %s  %s/s   " % (
                                bar, pct, human_size(done), human_size(total), human_size(speed)))
                            sys.stdout.flush()
                sys.stdout.write("\n")
        except urllib.error.HTTPError as e:
            if e.code == 416 and os.path.exists(part):
                pass  # already complete
            else:
                out("  Download error (%s), retry %d/3 ..." % (e, attempt))
                if e.code == 403:
                    break
                time.sleep(2 * attempt)
                continue
        except Exception as e:
            out("\n  Download interrupted (%s), retry %d/3 ..." % (e, attempt))
            time.sleep(2 * attempt)
            continue
        if total and os.path.getsize(part) != total:
            out("  Size mismatch, retrying ...")
            if os.path.getsize(part) > total:
                os.remove(part)
            continue
        os.replace(part, dest)
        downloaded = True
        break

    if not downloaded and _download_with_curl(url, part, total):
        os.replace(part, dest)
        downloaded = True

    if not downloaded:
        raise RuntimeError(
            "Download failed: %s. Check network/proxy or retry with --mirror <url_prefix>." % asset["name"]
        )

    want = expected_sha(asset)
    if want:
        out("  Verifying SHA-256 ...")
        if sha256_of(dest) != want:
            os.remove(dest)
            raise RuntimeError("SHA-256 mismatch for %s (file removed, run again)." % asset["name"])


def safe_members(zf, flatten_dlls_only=False, anchor="llama-server.exe"):
    """Yield (zipinfo, relative_target_path) with zip-slip protection."""
    names = [i for i in zf.infolist() if not i.is_dir()]
    prefix = ""
    if not flatten_dlls_only:
        for i in names:
            if os.path.basename(i.filename).lower() == anchor:
                prefix = i.filename[: -len(os.path.basename(i.filename))]
                break
    for info in names:
        name = info.filename.replace("\\", "/")
        if name.startswith("/") or ".." in name.split("/") or ":" in name:
            continue
        if flatten_dlls_only:
            if not name.lower().endswith(".dll"):
                continue
            yield info, os.path.basename(name)
        else:
            if prefix and not name.startswith(prefix.replace("\\", "/")):
                continue
            yield info, name[len(prefix):]


def extract_to_stage(zip_path, stage, flatten_dlls_only=False):
    count = 0
    with zipfile.ZipFile(zip_path) as zf:
        for info, rel in safe_members(zf, flatten_dlls_only):
            if not rel:
                continue
            dst = os.path.join(stage, rel)
            os.makedirs(os.path.dirname(dst) or stage, exist_ok=True)
            with zf.open(info) as src, open(dst, "wb") as f:
                shutil.copyfileobj(src, f)
            count += 1
    return count


def apply_stage(stage, target):
    failures = []
    copied = 0
    for root, _dirs, files in os.walk(stage):
        for fn in files:
            src = os.path.join(root, fn)
            rel = os.path.relpath(src, stage)
            dst = os.path.join(target, rel)
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            tmp = dst + ".new"
            try:
                shutil.copy2(src, tmp)
                os.replace(tmp, dst)
                copied += 1
            except Exception as e:
                failures.append((rel, str(e)))
                if os.path.exists(tmp):
                    try:
                        os.remove(tmp)
                    except Exception:
                        pass
    return copied, failures


# ----------------------------------------------------------------------------
# install
# ----------------------------------------------------------------------------
def print_plan(plan):
    out("  Release : %s" % plan["tag"])
    out("  Package : %s (%s)" % (plan["engine"]["name"], human_size(plan["engine"]["size"])))
    if plan["cudart"]:
        out("  Runtime : %s (%s)" % (plan["cudart"]["name"], human_size(plan["cudart"]["size"])))
    for n in plan["notes"]:
        out("  Note    : %s" % n)


def install_plan(plan, target, mirror=None, keep_cache=False):
    if is_server_running():
        out("llama-server.exe is currently running. Close it (and qidong) first, then retry.")
        return EXIT_ERROR

    need = plan["engine"]["size"] + (plan["cudart"]["size"] if plan["cudart"] else 0)
    cache = os.path.join(target, CACHE_DIRNAME)
    os.makedirs(cache, exist_ok=True)
    free = shutil.disk_usage(target).free
    if free < need * 2.2:
        out("Not enough free disk space: need about %s, have %s." % (human_size(need * 2.2), human_size(free)))
        return EXIT_ERROR

    stage = tempfile.mkdtemp(prefix="stage_", dir=cache)
    try:
        out("[1/3] Downloading engine package ...")
        engine_zip = os.path.join(cache, plan["engine"]["name"])
        download_asset(plan["engine"], engine_zip, mirror)
        cudart_zip = None
        if plan["cudart"]:
            out("[2/3] Downloading CUDA runtime ...")
            cudart_zip = os.path.join(cache, plan["cudart"]["name"])
            download_asset(plan["cudart"], cudart_zip, mirror)
        else:
            out("[2/3] CUDA runtime not needed for this variant.")

        out("[3/3] Extracting and installing ...")
        n1 = extract_to_stage(engine_zip, stage)
        if not os.path.exists(os.path.join(stage, "llama-server.exe")):
            raise RuntimeError("llama-server.exe not found inside %s" % plan["engine"]["name"])
        n2 = extract_to_stage(cudart_zip, stage, flatten_dlls_only=True) if cudart_zip else 0
        copied, failures = apply_stage(stage, target)
        if failures:
            out("Some files could not be replaced (are they in use?):")
            for rel, err in failures[:8]:
                out("  - %s: %s" % (rel, err))
            return EXIT_ERROR
        out("  Installed %d files (%d engine, %d runtime)." % (copied, n1, n2))

        state = {
            "tag": plan["tag"],
            "variant": plan["variant"],
            "arch": plan["arch"],
            "engine_asset": plan["engine"]["name"],
            "cudart_asset": plan["cudart"]["name"] if plan["cudart"] else None,
            "installed_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        }
        with open(os.path.join(target, STATE_FILE), "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2)

        if not keep_cache:
            for z in (engine_zip, cudart_zip):
                if z and os.path.exists(z):
                    os.remove(z)
        info = installed_info(target)
        out("")
        out("Done. %s" % (info["version_text"] if info and info["version_text"] else "llama-server.exe installed."))
        return EXIT_OK
    except KeyboardInterrupt:
        out("\nCancelled. Partial downloads are kept and will resume next time.")
        return EXIT_CANCEL
    except Exception as e:
        out("Install failed: %s" % e)
        return EXIT_ERROR
    finally:
        shutil.rmtree(stage, ignore_errors=True)
        try:
            if os.path.isdir(cache) and not os.listdir(cache):
                os.rmdir(cache)
        except Exception:
            pass


# ----------------------------------------------------------------------------
# commands
# ----------------------------------------------------------------------------
def resolve_plan(args, hw):
    out("Contacting GitHub releases ...")
    plan = find_plan(hw, getattr(args, "variant", "auto"), getattr(args, "tag", None))
    if not plan:
        out("No compatible package was found for this machine / selection.")
    return plan


def cmd_info(args):
    target = os.path.abspath(args.dir)
    hw = detect_hardware()
    out(describe_hardware(hw))
    inst = installed_info(target)
    out("")
    if inst:
        out("Installed    : %s%s" % (inst["tag"] or "unknown build", (" / " + inst["variant"]) if inst["variant"] else ""))
        out("Version text : %s" % inst["version_text"])
    else:
        out("Installed    : llama-server.exe not found in %s" % target)
    try:
        plan = resolve_plan(args, hw)
    except RuntimeError as e:
        out(str(e))
        return EXIT_ERROR
    if plan:
        out("")
        out("Recommended package for this machine:")
        print_plan(plan)
        if inst and inst["tag"] and tag_number(plan["tag"]) > tag_number(inst["tag"]):
            out("  -> A newer build is available (%s -> %s)." % (inst["tag"], plan["tag"]))
        elif inst and inst["tag"]:
            out("  -> Your build is up to date.")
        elif inst:
            out("  -> Installed build could not be identified; run 'install' to refresh it.")
    return EXIT_OK


def cmd_install(args):
    target = os.path.abspath(args.dir)
    hw = detect_hardware()
    out(describe_hardware(hw))
    out("")
    try:
        plan = resolve_plan(args, hw)
    except RuntimeError as e:
        out(str(e))
        return EXIT_ERROR
    if not plan:
        return EXIT_ERROR
    out("Selected package:")
    print_plan(plan)
    if not confirm("Download and install into %s ?" % target):
        return EXIT_CANCEL
    return install_plan(plan, target, args.mirror, args.keep_cache)


def cmd_update(args):
    target = os.path.abspath(args.dir)
    hw = detect_hardware()
    inst = installed_info(target)
    try:
        plan = resolve_plan(args, hw)
    except RuntimeError as e:
        out(str(e))
        return EXIT_ERROR
    if not plan:
        return EXIT_ERROR
    if inst and inst["tag"] and tag_number(plan["tag"]) <= tag_number(inst["tag"]) and not args.force:
        out("Already up to date (%s)." % inst["tag"])
        return EXIT_OK
    out("Update available:" if inst else "Not installed yet:")
    print_plan(plan)
    if not confirm("Install this build into %s ?" % target):
        return EXIT_CANCEL
    return install_plan(plan, target, args.mirror, args.keep_cache)


def cmd_ensure(args):
    target = os.path.abspath(args.dir)
    if os.path.exists(os.path.join(target, "llama-server.exe")):
        return EXIT_OK
    out("llama-server.exe was not found in %s." % target)
    out("qidong can download the right llama.cpp build for this PC automatically.")
    out("")
    hw = detect_hardware()
    out(describe_hardware(hw))
    out("")
    try:
        plan = resolve_plan(args, hw)
    except RuntimeError as e:
        out(str(e))
        return EXIT_ERROR
    if not plan:
        return EXIT_ERROR
    out("Selected package:")
    print_plan(plan)
    if not confirm("Download and install now?"):
        return EXIT_CANCEL
    return install_plan(plan, target, args.mirror, args.keep_cache)


def cmd_list(args):
    hw = detect_hardware()
    out("Contacting GitHub releases ...")
    try:
        for rel in iter_releases(1):
            if args.tag and rel["tag_name"].lower() != args.tag.lower():
                continue
            engines, cudarts = parse_release_assets(rel, hw["arch"])
            if not engines:
                continue
            out("Release %s (%s)" % (rel["tag_name"], hw["arch"]))
            for v, a in sorted(engines.items()):
                extra = ""
                fam, ver = split_variant(v)
                if fam == "cuda":
                    extra = "  + cudart %s" % ("yes" if ver in cudarts else "MISSING")
                out("  %-20s %10s%s" % (v, human_size(a["size"]), extra))
            return EXIT_OK
    except RuntimeError as e:
        out(str(e))
        return EXIT_ERROR
    out("Release not found.")
    return EXIT_ERROR


def cmd_menu(args):
    target = os.path.abspath(args.dir)
    out("=" * 60)
    out("  llama.cpp engine manager")
    out("=" * 60)
    hw = detect_hardware()
    out(describe_hardware(hw))
    inst = installed_info(target)
    out("")
    if inst:
        out("Installed    : %s%s" % (inst["tag"] or "unknown build", (" / " + inst["variant"]) if inst["variant"] else ""))
        out("Version text : %s" % inst["version_text"])
    else:
        out("Installed    : not found")
    try:
        plan = resolve_plan(args, hw)
    except RuntimeError as e:
        out(str(e))
        return EXIT_ERROR
    if not plan:
        return EXIT_ERROR
    out("")
    out("Recommended package:")
    print_plan(plan)
    if inst and inst["tag"]:
        if tag_number(plan["tag"]) > tag_number(inst["tag"]):
            out("  -> Newer build available: %s -> %s" % (inst["tag"], plan["tag"]))
        else:
            out("  -> Your build is up to date.")
    out("")
    out("  [1] Install / update to the recommended package")
    out("  [2] Choose a package variant manually")
    out("  [0] Back")
    try:
        choice = input("Select: ").strip()
    except (EOFError, KeyboardInterrupt):
        return EXIT_CANCEL
    if choice == "1":
        return install_plan(plan, target, args.mirror, args.keep_cache) if confirm("Install now?") else EXIT_CANCEL
    if choice == "2":
        engines, cudarts = parse_release_assets_for_tag(plan["tag"], hw["arch"])
        variants = sorted(engines.keys())
        out("")
        for i, v in enumerate(variants, 1):
            out("  [%d] %-20s %s" % (i, v, human_size(engines[v]["size"])))
        try:
            sel = input("Variant number (0 = cancel): ").strip()
        except (EOFError, KeyboardInterrupt):
            return EXIT_CANCEL
        if sel.isdigit() and 1 <= int(sel) <= len(variants):
            manual = find_plan(hw, variants[int(sel) - 1], plan["tag"])
            if manual:
                out("")
                print_plan(manual)
                if confirm("Install this package?"):
                    return install_plan(manual, target, args.mirror, args.keep_cache)
            else:
                out("That variant is not available (missing runtime?).")
    return EXIT_CANCEL


def parse_release_assets_for_tag(tag, arch):
    for rel in iter_releases():
        if rel["tag_name"].lower() == tag.lower():
            return parse_release_assets(rel, arch)
    return {}, {}


def build_parser():
    p = argparse.ArgumentParser(description="llama.cpp engine fetcher for qidong")
    sub = p.add_subparsers(dest="command")

    def common(sp):
        sp.add_argument("--dir", default=BASE_DIR, help="install directory (default: script folder)")
        sp.add_argument("--variant", default="auto", help="auto | cuda | cuda-12.4 | cuda-13.5 | vulkan | cpu | rocm | sycl | ...")
        sp.add_argument("--tag", default=None, help="specific release tag, e.g. b12541")
        sp.add_argument("--mirror", default=os.environ.get("LLAMA_FETCH_MIRROR"), help="URL prefix for downloads (mirror/proxy)")
        sp.add_argument("--keep-cache", action="store_true", help="keep downloaded zip files")
        sp.add_argument("-y", "--yes", action="store_true", help="do not ask for confirmation")

    for name, helptext in (("info", "show hardware and recommended package"),
                           ("install", "download and install"),
                           ("update", "install if a newer build exists"),
                           ("ensure", "install only if llama-server.exe is missing"),
                           ("menu", "interactive manager"),
                           ("list", "list packages of a release")):
        sp = sub.add_parser(name, help=helptext)
        common(sp)
        if name == "update":
            sp.add_argument("--force", action="store_true", help="reinstall even if up to date")
    return p


def main(argv=None):
    global _ASSUME_YES
    parser = build_parser()
    args = parser.parse_args(argv)
    if not args.command:
        parser.print_help()
        return EXIT_OK
    _ASSUME_YES = bool(getattr(args, "yes", False))
    handlers = {
        "info": cmd_info, "install": cmd_install, "update": cmd_update,
        "ensure": cmd_ensure, "menu": cmd_menu, "list": cmd_list,
    }
    try:
        return handlers[args.command](args)
    except KeyboardInterrupt:
        out("\nCancelled.")
        return EXIT_CANCEL


if __name__ == "__main__":
    sys.exit(main())
