# -*- coding: utf-8 -*-
import os
import sys
import subprocess
import re

TARGET_DIR = os.path.dirname(os.path.abspath(__file__))


def _parse_ipconfig():
    ips = []
    for enc in ("utf-8", "gbk", "cp1252"):
        try:
            out = subprocess.check_output(
                ["ipconfig"],
                text=True,
                encoding=enc,
                errors="ignore",
                creationflags=0x08000000 if sys.platform == "win32" else 0,
            )
            current_adapter = ""
            for line in out.splitlines():
                if line and not line.startswith(" ") and ":" in line:
                    current_adapter = line.split(":")[0].strip()
                if "IPv4" in line or "IP Address" in line:
                    m = re.search(r"(\d+\.\d+\.\d+\.\d+)", line)
                    if m:
                        ip = m.group(1)
                        if not ip.startswith(("127.", "169.254.")):
                            ips.append((current_adapter, ip))
            if ips:
                break
        except Exception:
            continue
    return ips


def get_all_network_endpoints():
    """Return dict with LAN, Tailscale, EasyTier, and ZeroTier IPv4 addresses."""
    tailscale_ip = None
    easytier_ip = None
    zerotier_ip = None

    ts_bins = ["tailscale"]
    default_ts_path = r"C:\Program Files\Tailscale\tailscale.exe"
    if os.path.exists(default_ts_path):
        ts_bins.append(default_ts_path)

    for ts_bin in ts_bins:
        try:
            ts_out = subprocess.check_output(
                [ts_bin, "ip", "-4"],
                text=True,
                encoding="utf-8",
                errors="ignore",
                timeout=2,
                creationflags=0x08000000 if sys.platform == "win32" else 0,
            ).strip()
            if ts_out and ts_out.startswith("100."):
                tailscale_ip = ts_out.splitlines()[0].strip()
                break
        except Exception:
            continue

    ips = _parse_ipconfig()
    lan_ip = None
    vpn_keywords = ("tailscale", "easytier", "zerotier", "mihomo", "clash", "wintun", "wireguard", "vethernet")

    for adapter, ip in ips:
        low = adapter.lower()
        if "tailscale" in low:
            if not tailscale_ip and ip.startswith("100."):
                tailscale_ip = ip
        elif "easytier" in low or low.startswith("et"):
            if not easytier_ip:
                easytier_ip = ip
        elif "zerotier" in low:
            if not zerotier_ip:
                zerotier_ip = ip
        elif not any(k in low for k in vpn_keywords):
            if ip.startswith(("192.168.", "10.", "172.")) and not lan_ip:
                lan_ip = ip

    if not lan_ip and ips:
        for adapter, ip in ips:
            low = adapter.lower()
            if not any(k in low for k in ("mihomo", "clash", "tailscale", "easytier", "zerotier")):
                lan_ip = ip
                break
        if not lan_ip:
            lan_ip = ips[0][1]

    return {
        "lan": lan_ip or "127.0.0.1",
        "tailscale": tailscale_ip,
        "easytier": easytier_ip,
        "zerotier": zerotier_ip,
    }


def get_network_ips():
    ep = get_all_network_endpoints()
    return ep["lan"], ep["tailscale"]


def _detect_console_encoding() -> str:
    try:
        import ctypes
        cp = ctypes.windll.kernel32.GetConsoleOutputCP()
        if cp == 65001:
            return "utf-8"
        if cp in (936, 54936):
            return "gbk"
        if cp > 0:
            return f"cp{cp}"
    except Exception:
        pass
    return "utf-8"


_CONSOLE_ENC = _detect_console_encoding()


def _bat_write(text: str) -> None:
    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32
        h_stdout = kernel32.GetStdHandle(-11)
        written = ctypes.c_ulong(0)
        if kernel32.WriteConsoleW(h_stdout, text, len(text), ctypes.byref(written), None):
            return
    except Exception:
        pass
    try:
        sys.stdout.buffer.write(text.encode(_CONSOLE_ENC, errors="replace"))
        sys.stdout.buffer.flush()
    except Exception:
        try:
            sys.stdout.write(text)
            sys.stdout.flush()
        except Exception:
            pass


def print_endpoints():
    ep = get_all_network_endpoints()

    lines = [
        "------------------------------------------------------------",
        "[Service Endpoints (Web UI & API Hub)]",
        " * Local PC Access       : http://127.0.0.1:8080",
        f" * LAN (Phone / Tablet)  : http://{ep['lan']}:8080",
        "   (Mobile-ready chat synced with local SQLite history)",
    ]
    if ep["tailscale"]:
        lines.append(f" * Tailscale Remote      : http://{ep['tailscale']}:8080")
    if ep["easytier"]:
        lines.append(f" * EasyTier Remote       : http://{ep['easytier']}:8080")
    if ep["zerotier"]:
        lines.append(f" * ZeroTier Remote       : http://{ep['zerotier']}:8080")
    lines.append(" * OpenAI-Compatible API : http://127.0.0.1:8080/v1")
    lines.append("------------------------------------------------------------")

    _bat_write("\n".join(lines) + "\n")


def main():
    if len(sys.argv) < 2 or sys.argv[1] == "--print-endpoints":
        print_endpoints()
    elif sys.argv[1] == "--get-lan-ip":
        lan_ip, _ = get_network_ips()
        _bat_write(lan_ip + "\n")
    else:
        print_endpoints()


if __name__ == "__main__":
    main()
