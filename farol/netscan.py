"""
Painel "Rede": quem está conectado na rede local.

Funciona offline e sem privilégios de administrador:
  1. Descobre o IP desta máquina e a sub-rede /24.
  2. Envia um pacote UDP vazio para cada IP da sub-rede (porta 9, "discard").
     Isso força o sistema a resolver o endereço MAC (ARP) de quem existe.
  3. Lê a tabela ARP do sistema (/proc/net/arp no Linux, 'arp -a' no Windows/macOS).
  4. Tenta descobrir o nome de cada aparelho (DNS reverso / NetBIOS / mDNS do sistema).

Por segurança, só varre redes PRIVADAS (10.x, 172.16-31.x, 192.168.x).
Não faz varredura de portas — só lista quem está presente.
"""
from __future__ import annotations

import ipaddress
import os
import re
import socket
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor

_IP_MAC = re.compile(r"(\d{1,3}(?:\.\d{1,3}){3})\D+?([0-9a-fA-F]{1,2}(?:[:-][0-9a-fA-F]{1,2}){5})")


def local_ip() -> str:
    """IP desta máquina na LAN (o 'connect' em UDP não envia nada pela rede)."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


def _norm_mac(mac: str) -> str:
    parts = re.split(r"[:-]", mac)
    return ":".join(p.zfill(2) for p in parts).lower()


def read_arp() -> dict[str, str]:
    """Tabela ARP do sistema -> {ip: mac}."""
    table: dict[str, str] = {}
    if sys.platform.startswith("linux") and os.path.exists("/proc/net/arp"):
        with open("/proc/net/arp") as fh:
            next(fh, None)
            for line in fh:
                cols = line.split()
                if len(cols) >= 4 and cols[2] != "0x0" and cols[3] != "00:00:00:00:00:00":
                    table[cols[0]] = cols[3].lower()
        return table
    try:
        out = subprocess.run(["arp", "-a"], capture_output=True, text=True, timeout=10).stdout
    except (OSError, subprocess.SubprocessError):
        return table
    for ip, mac in _IP_MAC.findall(out):
        m = _norm_mac(mac)
        if m not in ("ff:ff:ff:ff:ff:ff", "00:00:00:00:00:00"):
            table[ip] = m
    return table


def _gateway_guess(ip: str) -> str:
    return ".".join(ip.split(".")[:3] + ["1"])


def _hostname(ip: str) -> str:
    try:
        return socket.gethostbyaddr(ip)[0]
    except OSError:
        return ""


def scan(wait: float = 1.5) -> dict:
    """Faz a varredura e devolve a lista de dispositivos."""
    me = local_ip()
    started = time.time()
    devices = []
    try:
        addr = ipaddress.IPv4Address(me)
    except ValueError:
        addr = None
    if addr and addr.is_private and not addr.is_loopback:
        net = ipaddress.IPv4Network(f"{me}/24", strict=False)
        # 1) "Cutuca" cada IP para popular a tabela ARP.
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.setblocking(False)
        for host in net.hosts():
            try:
                s.sendto(b"", (str(host), 9))
            except OSError:
                pass
        s.close()
        time.sleep(wait)
        # 2) Lê a tabela e descobre nomes em paralelo (com limite de tempo).
        arp = {ip: mac for ip, mac in read_arp().items()
               if ipaddress.IPv4Address(ip) in net}
        with ThreadPoolExecutor(max_workers=32) as pool:
            names = dict(zip(arp, pool.map(_hostname, arp)))
        gw = _gateway_guess(me)
        for ip, mac in sorted(arp.items(), key=lambda kv: ipaddress.IPv4Address(kv[0])):
            devices.append({"ip": ip, "mac": mac, "name": names.get(ip, ""),
                            "gateway": ip == gw, "self": False})
        devices.insert(0, {"ip": me, "mac": "", "name": socket.gethostname(), "gateway": False, "self": True})
        subnet = str(net)
    else:
        subnet = ""
    return {"subnet": subnet, "local_ip": me, "devices": devices,
            "ms": int((time.time() - started) * 1000)}
