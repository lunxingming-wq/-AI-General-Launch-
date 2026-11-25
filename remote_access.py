#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
remote_access.py - Optional Regional Remote Access & Security Helper (stdlib only).

Helps users connect phones/tablets/remote PCs to local qidong (port 8080) with
region-appropriate external tools, plus an optional lightweight Access Token:
  * Global / Overseas : Tailscale (recommended private P2P VPN), Cloudflare Tunnel
  * Mainland China    : EasyTier (recommended CN-friendly P2P VPN), ZeroTier
  * Optional Auth     : .access_token / WEB_ACCESS_TOKEN (localhost stays passwordless)

Completely optional: local PC & home LAN work out of the box without running this.
"""

import argparse
import json
import os
import platform
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import zipfile

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TOOLS_DIR = os.path.join(BASE_DIR, "tools")
TOKEN_FILE = os.path.join(BASE_DIR, ".access_token")
USER_AGENT = "qidong-remote-helper/1.0"
CREATE_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0

EXIT_OK, EXIT_ERROR, EXIT_CANCEL = 0, 1, 2
_ASSUME_YES = False


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


def detect_arch():
    m = (platform.machine() or "").lower()
    if "arm64" in m or "aarch64" in m:
        return "arm64"
    return "x64"


def human_size(n):
    n = float(n or 0)
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return ("%.0f %s" % (n, unit)) if unit == "B" else ("%.1f %s" % (n, unit))
        n /= 1024.0


# ----------------------------------------------------------------------------
# Optional Access Token helpers
# ----------------------------------------------------------------------------
def get_configured_token():
    env_tok = (os.environ.get("WEB_ACCESS_TOKEN") or "").strip()
    if env_tok:
        return env_tok, "env:WEB_ACCESS_TOKEN"
    if os.path.exists(TOKEN_FILE):
        try:
            with open(TOKEN_FILE, "r", encoding="utf-8") as fp:
                tok = fp.read().strip()
            if tok:
                return tok, ".access_token"
        except Exception:
            pass
    return "", None


def save_token(token):
    with open(TOKEN_FILE, "w", encoding="utf-8") as fp:
        fp.write(token.strip() + "\n")


def clear_token():
    if os.path.exists(TOKEN_FILE):
        os.remove(TOKEN_FILE)


# ----------------------------------------------------------------------------
# Local tool detection
# ----------------------------------------------------------------------------
def find_tailscale():
    for cand in (shutil.which("tailscale"), r"C:\Program Files\Tailscale\tailscale.exe"):
        if cand and os.path.exists(cand):
            return cand
    return None


def find_easytier():
    local_dir = os.path.join(TOOLS_DIR, "easytier")
    for cand in (
        os.path.join(local_dir, "easytier-core.exe"),
        shutil.which("easytier-core"),
        shutil.which("easytier-core.exe"),
    ):
        if cand and os.path.exists(cand):
            return cand
    if os.path.isdir(local_dir):
        for root, _, files in os.walk(local_dir):
            if "easytier-core.exe" in files:
                return os.path.join(root, "easytier-core.exe")
    return None


def find_cloudflared():
    for cand in (
        os.path.join(TOOLS_DIR, "cloudflared", "cloudflared.exe"),
        shutil.which("cloudflared"),
        shutil.which("cloudflared.exe"),
    ):
        if cand and os.path.exists(cand):
            return cand
    return None


def find_zerotier():
    for cand in (
        shutil.which("zerotier-cli"),
        r"C:\ProgramData\ZeroTier\One\zerotier-one_x64.exe",
        r"C:\Program Files (x86)\ZeroTier\One\zerotier-cli.bat",
    ):
        if cand and os.path.exists(cand):
            return cand
    return None


# ----------------------------------------------------------------------------
# GitHub release & safe download helpers
# ----------------------------------------------------------------------------
def _gh_headers():
    headers = {"User-Agent": USER_AGENT, "Accept": "application/vnd.github+json"}
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if token:
        headers["Authorization"] = "Bearer " + token.strip()
    return headers


def fetch_latest_release(repo):
    url = "https://api.github.com/repos/%s/releases/latest" % repo
    req = urllib.request.Request(url, headers=_gh_headers())
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        raise RuntimeError("Could not contact GitHub for %s (%s)." % (repo, e))


def apply_mirror(url, mirror):
    if not mirror:
        return url
    prefix = mirror.strip()
    if not prefix.endswith("/"):
        prefix += "/"
    return prefix + url


def download_binary(url, dest_path, expected_size=0):
    os.makedirs(os.path.dirname(os.path.abspath(dest_path)), exist_ok=True)
    part = dest_path + ".part"
    out("  Downloading: %s" % url)
    ok = False
    last_err = None
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=60) as resp:
                cl = resp.headers.get("Content-Length")
                total = int(cl) if (cl and cl.isdigit()) else expected_size
                done = 0
                t0 = time.time()
                last_print = 0.0
                with open(part, "wb") as fp:
                    while True:
                        chunk = resp.read(256 * 1024)
                        if not chunk:
                            break
                        fp.write(chunk)
                        done += len(chunk)
                        now = time.time()
                        if now - last_print >= 0.4 or (total and done >= total):
                            speed = done / max(0.001, now - t0)
                            if total:
                                sys.stdout.write("\r  Progress: %5.1f%%  %s / %s (%s/s)   " % (
                                    min(100.0, done * 100.0 / total),
                                    human_size(done), human_size(total), human_size(speed)
                                ))
                            else:
                                sys.stdout.write("\r  Downloaded: %s (%s/s)   " % (human_size(done), human_size(speed)))
                            sys.stdout.flush()
                            last_print = now
                sys.stdout.write("\n")
                sys.stdout.flush()
                ok = True
                break
        except Exception as e:
            last_err = e
            time.sleep(1.2 * (attempt + 1))

    if not ok:
        curl = shutil.which("curl.exe") or shutil.which("curl")
        if curl:
            out("  urllib failed (%s); retrying with curl.exe..." % last_err)
            res = subprocess.run([curl, "-fL", "--progress-bar", "-o", part, "-A", USER_AGENT, url])
            ok = (res.returncode == 0 and os.path.exists(part) and os.path.getsize(part) > 0)
    if not ok:
        raise RuntimeError("Download failed (%s). Try passing --mirror <proxy_prefix>." % last_err)
    os.replace(part, dest_path)


def safe_extract_zip(zip_path, dest_dir):
    os.makedirs(dest_dir, exist_ok=True)
    dest_real = os.path.realpath(dest_dir)
    with zipfile.ZipFile(zip_path, "r") as zf:
        for info in zf.infolist():
            if info.is_dir():
                continue
            parts = [p for p in info.filename.replace("\\", "/").split("/") if p not in ("", ".")]
            if not parts or any(p == ".." for p in parts):
                continue
            target = os.path.realpath(os.path.join(dest_dir, *parts))
            if not (target == dest_real or target.startswith(dest_real + os.sep)):
                continue
            os.makedirs(os.path.dirname(target), exist_ok=True)
            with zf.open(info) as src, open(target, "wb") as dst:
                shutil.copyfileobj(src, dst)


# ----------------------------------------------------------------------------
# Installers per tool
# ----------------------------------------------------------------------------
def install_easytier(mirror=None):
    arch = detect_arch()
    et_arch = "arm64" if arch == "arm64" else "x86_64"
    out("\n[EasyTier] Checking latest EasyTier/EasyTier release for Windows %s..." % et_arch)
    rel = fetch_latest_release("EasyTier/EasyTier")
    tag = rel.get("tag_name", "")
    pattern = re.compile(r"^easytier-windows-%s-.*\.zip$" % re.escape(et_arch), re.IGNORECASE)
    asset = None
    for a in rel.get("assets", []):
        if pattern.match(a.get("name", "")):
            asset = a
            break
    if not asset:
        raise RuntimeError("No matching Windows %s EasyTier zip found in %s." % (et_arch, tag))

    url = apply_mirror(asset["browser_download_url"], mirror)
    out("  Release : %s" % tag)
    out("  Asset   : %s (%s)" % (asset["name"], human_size(asset.get("size", 0))))
    dest_dir = os.path.join(TOOLS_DIR, "easytier")
    if not confirm("Download and extract portable EasyTier into %s ?" % dest_dir):
        return EXIT_CANCEL

    tmp_zip = os.path.join(tempfile.gettempdir(), asset["name"])
    try:
        download_binary(url, tmp_zip, asset.get("size", 0))
        if os.path.exists(dest_dir):
            shutil.rmtree(dest_dir, ignore_errors=True)
        safe_extract_zip(tmp_zip, dest_dir)
    finally:
        if os.path.exists(tmp_zip):
            try:
                os.remove(tmp_zip)
            except OSError:
                pass

    exe = find_easytier()
    out("\n[OK] EasyTier installed at: %s" % (exe or dest_dir))
    out("\nQuick start example (Run as Administrator on PC, join same network on phone app):")
    out("  \"%s\" -i 10.126.126.1 --network-name my-ai-net --network-secret YourStrongPass -p tcp://public.easytier.top:11010" % (exe or "easytier-core.exe"))
    out("  Then open http://10.126.126.1:8080/mobile on your phone (EasyTier Android/iOS app).")
    return EXIT_OK


def install_cloudflared(mirror=None):
    out("\n[Cloudflare Tunnel] Checking latest cloudflare/cloudflared release...")
    rel = fetch_latest_release("cloudflare/cloudflared")
    tag = rel.get("tag_name", "")
    asset = None
    for a in rel.get("assets", []):
        if a.get("name", "").lower() == "cloudflared-windows-amd64.exe":
            asset = a
            break
    if not asset:
        raise RuntimeError("cloudflared-windows-amd64.exe not found in release %s." % tag)

    url = apply_mirror(asset["browser_download_url"], mirror)
    dest = os.path.join(TOOLS_DIR, "cloudflared", "cloudflared.exe")
    out("  Release : %s" % tag)
    out("  Asset   : %s (%s)" % (asset["name"], human_size(asset.get("size", 0))))
    if not confirm("Download portable cloudflared.exe into %s ?" % dest):
        return EXIT_CANCEL

    download_binary(url, dest, asset.get("size", 0))
    out("\n[OK] cloudflared installed at: %s" % dest)
    out("\nSECURITY NOTE: A Cloudflare Quick Tunnel creates a PUBLIC HTTPS URL.")
    out("  Enable the Optional Access Token ([5] in menu) before sharing publicly!")
    out("  Start tunnel command: \"%s\" tunnel --url http://127.0.0.1:8080" % dest)
    return EXIT_OK


def install_via_winget_or_guide(name, winget_id, download_url, extra_note):
    out("\n[%s]" % name)
    out("  Official download: %s" % download_url)
    out("  %s" % extra_note)
    winget = shutil.which("winget")
    if winget:
        if confirm("Run `winget install --id %s -e` now?" % winget_id, default=False):
            res = subprocess.run([winget, "install", "--id", winget_id, "-e"])
            return EXIT_OK if res.returncode == 0 else EXIT_ERROR
    else:
        out("  (winget not available; download directly from the official URL above.)")
    return EXIT_OK


def print_status():
    try:
        import network_helper
        ep = network_helper.get_all_network_endpoints()
    except Exception:
        ep = {"lan": "127.0.0.1", "tailscale": None, "easytier": None, "zerotier": None}

    tok, tok_src = get_configured_token()
    out("=" * 64)
    out("          Remote Access & Security Status (Port 8080)")
    out("=" * 64)
    out("  LAN IP           : http://%s:8080" % ep["lan"])
    out("  Tailscale        : %s%s" % (
        "Installed" if find_tailscale() else "Not installed",
        ("  -> http://%s:8080" % ep["tailscale"]) if ep.get("tailscale") else ""
    ))
    out("  EasyTier         : %s%s" % (
        "Installed" if find_easytier() else "Not installed",
        ("  -> http://%s:8080" % ep["easytier"]) if ep.get("easytier") else ""
    ))
    out("  ZeroTier         : %s%s" % (
        "Installed" if find_zerotier() else "Not installed",
        ("  -> http://%s:8080" % ep["zerotier"]) if ep.get("zerotier") else ""
    ))
    out("  Cloudflared      : %s" % ("Installed" if find_cloudflared() else "Not installed"))
    if tok:
        masked = tok[:4] + "*" * max(4, len(tok) - 6) + tok[-2:] if len(tok) > 8 else "****"
        out("  Access Token     : ENABLED (%s via %s)" % (masked, tok_src))
    else:
        out("  Access Token     : Disabled (open to LAN / private VPN)")
    out("=" * 64)


def print_regional_guide():
    out("")
    out("=" * 64)
    out("     Recommended Remote Access Software by Country / Region")
    out("=" * 64)
    out("  1. Global / Overseas Users:")
    out("     - Tailscale (Best overall): Private WireGuard P2P mesh.")
    out("       Install on PC + Phone -> open http://<100.x.x.x>:8080/mobile")
    out("     - Cloudflare Tunnel (cloudflared): No phone app required;")
    out("       generates a temporary HTTPS URL. Enable Access Token first!")
    out("")
    out("  2. Mainland China Users:")
    out("     - EasyTier (Recommended): Open-source P2P mesh VPN with fast")
    out("       CN public relay nodes, no overseas account needed. Supports")
    out("       Windows, Android, and iOS. Use [2] to auto-fetch portable zip.")
    out("     - ZeroTier: Mature virtual LAN, works in CN & globally.")
    out("     - Tailscale: Works well if you use a custom DERP relay or proxy.")
    out("")
    out("  3. Security Tip:")
    out("     - Home Wi-Fi / personal Tailscale or EasyTier -> Token optional.")
    out("     - Public Wi-Fi / shared network / Cloudflare Tunnel -> Enable")
    out("       the Optional Access Token ([5]). Localhost (127.0.0.1) stays")
    out("       password-free automatically on your own PC.")
    out("=" * 64)
    out("")


def cmd_token(args):
    action = getattr(args, "action", "status") or "status"
    if action == "status":
        tok, src = get_configured_token()
        if tok:
            out("Access Token is ENABLED (%s): %s" % (src, tok))
        else:
            out("Access Token is DISABLED.")
        return EXIT_OK
    if action == "gen":
        tok = secrets.token_urlsafe(18)
        save_token(tok)
        out("[OK] Generated new Access Token in .access_token:")
        out("     Token     : %s" % tok)
        out("     Phone URL : http://<LAN-OR-VPN-IP>:8080/?token=%s" % tok)
        out("     OpenAI Key: %s" % tok)
        out("     (Restart qidong / server_core.py if currently running; localhost stays password-free.)")
        return EXIT_OK
    if action == "set":
        val = getattr(args, "value", None)
        if not val:
            val = input("Enter custom Access Token (min 4 chars, empty to cancel): ").strip()
        if len(val) < 4:
            out("Cancelled (token too short).")
            return EXIT_CANCEL
        save_token(val)
        out("[OK] Saved Access Token to .access_token.")
        return EXIT_OK
    if action == "clear":
        clear_token()
        out("[OK] Removed .access_token. (Note: if WEB_ACCESS_TOKEN env var is set, unset it too.)")
        return EXIT_OK
    return EXIT_OK


def cmd_tunnel(args):
    cf = find_cloudflared()
    if not cf:
        out("cloudflared.exe is not installed yet.")
        if confirm("Download portable cloudflared.exe now?"):
            rc = install_cloudflared(args.mirror)
            if rc != EXIT_OK:
                return rc
            cf = find_cloudflared()
        else:
            return EXIT_CANCEL
    tok, _ = get_configured_token()
    if not tok:
        out("\n[WARNING] Access Token is currently DISABLED!")
        out("A Cloudflare Quick Tunnel exposes port 8080 to the public internet.")
        if confirm("Generate & enable an Access Token right now before starting the tunnel?", default=True):
            cmd_token(argparse.Namespace(action="gen", value=None))
    out("\nStarting Cloudflare Quick Tunnel -> http://127.0.0.1:8080 (Press Ctrl+C to stop)...")
    try:
        return subprocess.run([cf, "tunnel", "--url", "http://127.0.0.1:8080"]).returncode
    except KeyboardInterrupt:
        return EXIT_OK


def cmd_menu(args):
    mirror = args.mirror
    while True:
        print_status()
        out("  [1] Global Recommended      : Install / Setup Tailscale (Private P2P VPN)")
        out("  [2] China Recommended       : Auto-Download Portable EasyTier (P2P VPN)")
        out("  [3] No-App Quick HTTPS URL  : Auto-Download Portable Cloudflare Tunnel")
        out("  [4] Cross-Region Alternative: Install / Setup ZeroTier")
        out("  [5] Optional Access Token   : Generate / Set / Disable Remote Auth")
        out("  [6] Launch Cloudflare Quick Tunnel (requires qidong running on 8080)")
        out("  [7] View Regional Software Guide")
        out("  [M] Set GitHub Download Mirror (current: %s)" % (mirror or "Direct GitHub"))
        out("  [0] Back")
        out("=" * 64)
        try:
            ch = input("Select option: ").strip()
        except (EOFError, KeyboardInterrupt):
            return EXIT_CANCEL

        if not ch or ch == "0":
            return EXIT_OK
        try:
            if ch == "1":
                install_via_winget_or_guide(
                    "Tailscale", "Tailscale.Tailscale",
                    "https://tailscale.com/download/windows",
                    "Install on Windows + Phone, sign in to the same account, and open http://<100.x.x.x>:8080/mobile."
                )
            elif ch == "2":
                install_easytier(mirror)
            elif ch == "3":
                install_cloudflared(mirror)
            elif ch == "4":
                install_via_winget_or_guide(
                    "ZeroTier One", "ZeroTier.ZeroTierOne",
                    "https://www.zerotier.com/download/",
                    "Create a free private network at my.zerotier.com, join on PC & Phone, then open http://<ZT-IP>:8080/mobile."
                )
            elif ch == "5":
                tok, _ = get_configured_token()
                out("\n  [G] Generate strong random token")
                out("  [S] Set custom token / PIN")
                if tok:
                    out("  [D] Disable / clear token")
                out("  [0] Back")
                sub = input("  Choose: ").strip().upper()
                if sub == "G":
                    cmd_token(argparse.Namespace(action="gen", value=None))
                elif sub == "S":
                    cmd_token(argparse.Namespace(action="set", value=None))
                elif sub == "D":
                    cmd_token(argparse.Namespace(action="clear", value=None))
            elif ch == "6":
                cmd_tunnel(argparse.Namespace(mirror=mirror))
            elif ch == "7":
                print_regional_guide()
            elif ch.upper() == "M":
                val = input("Enter GitHub mirror prefix (e.g. https://gh-proxy.com/, empty for Direct): ").strip()
                mirror = val or None
            else:
                out("Invalid option.")
        except Exception as e:
            out("[Error] %s" % e)
        out("")


def cmd_install(args):
    tool = args.tool.lower()
    if tool == "easytier":
        return install_easytier(args.mirror)
    if tool == "cloudflared":
        return install_cloudflared(args.mirror)
    if tool == "tailscale":
        return install_via_winget_or_guide(
            "Tailscale", "Tailscale.Tailscale",
            "https://tailscale.com/download/windows",
            "Best private mesh VPN for global users."
        )
    if tool == "zerotier":
        return install_via_winget_or_guide(
            "ZeroTier One", "ZeroTier.ZeroTierOne",
            "https://www.zerotier.com/download/",
            "Cross-region virtual LAN."
        )
    out("Unknown tool: %s (choose easytier | cloudflared | tailscale | zerotier)" % tool)
    return EXIT_ERROR


def build_parser():
    p = argparse.ArgumentParser(description="Optional remote access & security helper for qidong")
    sub = p.add_subparsers(dest="command")

    def common(sp):
        sp.add_argument("--mirror", default=os.environ.get("LLAMA_FETCH_MIRROR"), help="GitHub download mirror prefix")
        sp.add_argument("-y", "--yes", action="store_true", help="skip confirmations")

    sp_m = sub.add_parser("menu", help="interactive remote access & security menu")
    common(sp_m)

    sp_s = sub.add_parser("status", help="show detected remote tools, IPs and token status")
    common(sp_s)

    sp_i = sub.add_parser("install", help="install/download an optional remote access tool")
    sp_i.add_argument("tool", choices=["easytier", "cloudflared", "tailscale", "zerotier"])
    common(sp_i)

    sp_t = sub.add_parser("token", help="manage optional remote access token")
    sp_t.add_argument("action", nargs="?", default="status", choices=["status", "gen", "set", "clear"])
    sp_t.add_argument("value", nargs="?", default=None)
    common(sp_t)

    sp_tun = sub.add_parser("tunnel", help="start a Cloudflare Quick Tunnel for port 8080")
    common(sp_tun)
    return p


def main(argv=None):
    global _ASSUME_YES
    parser = build_parser()
    args = parser.parse_args(argv)
    if not args.command:
        args = parser.parse_args(["menu"])
    _ASSUME_YES = bool(getattr(args, "yes", False))
    handlers = {
        "menu": cmd_menu,
        "status": lambda a: (print_status(), EXIT_OK)[1],
        "install": cmd_install,
        "token": cmd_token,
        "tunnel": cmd_tunnel,
    }
    try:
        return handlers[args.command](args)
    except KeyboardInterrupt:
        out("\nCancelled.")
        return EXIT_CANCEL


if __name__ == "__main__":
    sys.exit(main())
