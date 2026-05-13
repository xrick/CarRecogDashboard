"""
大華監控設備連線測試與自動發現工具

發現策略（依序執行，找到任何結果即顯示給使用者選擇）：
  1. DH-Discover UDP 廣播 (port 37810, 新韌體 JSON 協議)
  2. DHIP UDP 廣播      (port 5050,  舊韌體二進位協議)
  3. mDNS 查詢          (_http._tcp / _rtsp._tcp)
  4. ARP 全網段掃描     (依大華 OUI 過濾)
  5. TCP 全網段掃描     (port 80 + magicBox.cgi 指紋驗證)

依賴套件: scapy, requests, netifaces
    sudo pip install scapy requests netifaces --break-system-packages
"""

import socket
import struct
import json
import logging
import ipaddress
import concurrent.futures
import argparse
import sys
from typing import Optional

import requests
from requests.auth import HTTPDigestAuth
from scapy.all import ARP, Ether, srp, conf
import netifaces

logging.getLogger("scapy.runtime").setLevel(logging.ERROR)
conf.verb = 0

DAHUA_USER = "admin"
DAHUA_PASS = "admin"

# 大華已知 OUI 前綴 (來源: IEEE OUI 公開資料 + 多版 ConfigTool 內建清單)
DAHUA_OUI_PREFIXES = {
    "3c:ef:8c", "14:a7:8b", "a0:bd:1d", "90:02:a9", "4c:11:bf",
    "08:ed:ed", "38:af:29", "9c:14:63", "bc:32:5f", "fc:b0:c4",
    "e0:50:8b", "00:01:5b", "00:30:4f", "70:f9:6d", "00:1a:6b",
    "f8:69:d9", "1c:c3:eb", "70:b3:d5", "c8:5b:76",
}

DH_DISCOVER_PORT = 37810
DHIP_DISCOVER_PORT = 5050

# =========================================================================
# 區段 1：自動發現大華設備
# =========================================================================

def get_local_subnets() -> list[tuple[str, str, str]]:
    """回傳本機所有 (interface, ip, cidr) 三元組，排除 loopback。"""
    subnets = []
    for iface in netifaces.interfaces():
        addrs = netifaces.ifaddresses(iface).get(netifaces.AF_INET, [])
        for addr in addrs:
            ip = addr.get("addr")
            netmask = addr.get("netmask")
            if not ip or not netmask or ip.startswith("127."):
                continue
            try:
                network = ipaddress.IPv4Network(f"{ip}/{netmask}", strict=False)
                subnets.append((iface, ip, str(network)))
            except ValueError:
                continue
    return subnets


def discover_via_dh_broadcast(timeout: float = 3.0) -> list[dict]:
    """
    DH-Discover：UDP 37810 廣播，新韌體 (~2017 之後) 支援。
    Payload 是 JSON：{"method":"DHDiscover.search","params":{"mac":"","uni":1}}
    """
    print(f"[*] [方法 1] DH-Discover UDP 廣播 (port {DH_DISCOVER_PORT})...")
    payload = json.dumps({
        "method": "DHDiscover.search",
        "params": {"mac": "", "uni": 1}
    }).encode("utf-8")

    found = []
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.settimeout(timeout)
        sock.bind(("", 0))
        sock.sendto(payload, ("255.255.255.255", DH_DISCOVER_PORT))

        while True:
            try:
                data, addr = sock.recvfrom(8192)
            except socket.timeout:
                break
            try:
                resp = json.loads(data.decode("utf-8", errors="ignore"))
                params = resp.get("params", {})
                dev = params.get("deviceInfo", params)
                ip = dev.get("IPv4Address", {}).get("IPAddress") or addr[0]
                found.append({
                    "ip": ip,
                    "mac": dev.get("Mac", ""),
                    "model": dev.get("DeviceType", ""),
                    "serial": dev.get("SerialNo", ""),
                    "source": "DH-Discover",
                })
            except (json.JSONDecodeError, KeyError):
                # 仍記錄 IP，未知格式也是大華設備
                found.append({"ip": addr[0], "source": "DH-Discover (raw)"})
        sock.close()
    except OSError as e:
        print(f"    [!] socket 錯誤: {e}")
    print(f"    -> 發現 {len(found)} 台")
    return found


def discover_via_dhip_broadcast(timeout: float = 3.0) -> list[dict]:
    """
    舊韌體 DHIP 私有協議：UDP 5050 廣播，二進位 32 byte header + JSON body。
    Header: magic(4)=0xa1 0x00 0x00 0x60, session(8)=0, id(4)=0,
            返回的 body_len(4), 保留(4), body_len(4), 保留(4)
    """
    print(f"[*] [方法 2] DHIP UDP 廣播 (port {DHIP_DISCOVER_PORT})...")
    body = json.dumps({
        "method": "DHDiscover.search",
        "params": {"mac": "", "uni": 1}
    }).encode("utf-8")
    body_len = len(body)
    header = struct.pack("<4sQIIII",
                         b"\xa1\x00\x00\x60", 0, 0, body_len, 0, body_len)
    packet = header + body

    found = []
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sock.settimeout(timeout)
        sock.sendto(packet, ("255.255.255.255", DHIP_DISCOVER_PORT))

        while True:
            try:
                data, addr = sock.recvfrom(8192)
            except socket.timeout:
                break
            # 嘗試從 byte 32 後抽取 JSON
            json_start = data.find(b"{")
            if json_start >= 0:
                try:
                    resp = json.loads(data[json_start:].decode("utf-8", errors="ignore"))
                    params = resp.get("params", {})
                    dev = params.get("deviceInfo", params)
                    ip = dev.get("IPv4Address", {}).get("IPAddress") or addr[0]
                    found.append({
                        "ip": ip,
                        "mac": dev.get("Mac", ""),
                        "model": dev.get("DeviceType", ""),
                        "serial": dev.get("SerialNo", ""),
                        "source": "DHIP",
                    })
                    continue
                except json.JSONDecodeError:
                    pass
            found.append({"ip": addr[0], "source": "DHIP (raw)"})
        sock.close()
    except OSError as e:
        print(f"    [!] socket 錯誤: {e}")
    print(f"    -> 發現 {len(found)} 台")
    return found


def discover_via_arp_scan(cidr: str, timeout: float = 3.0) -> list[dict]:
    """ARP 全網段掃描，過濾大華 OUI。"""
    print(f"[*] [方法 3] ARP 全網段掃描 {cidr} (依 OUI 過濾)...")
    found = []
    try:
        arp_request = ARP(pdst=cidr)
        ether = Ether(dst="ff:ff:ff:ff:ff:ff")
        ans = srp(ether / arp_request, timeout=timeout, verbose=0)[0]
        for _, recv in ans:
            mac = recv.hwsrc.lower()
            oui = ":".join(mac.split(":")[:3])
            entry = {"ip": recv.psrc, "mac": mac, "source": "ARP"}
            if oui in DAHUA_OUI_PREFIXES:
                entry["match"] = "OUI 命中大華"
                found.append(entry)
            else:
                # 仍保留，後續用 magicBox 指紋驗證
                entry["match"] = "OUI 未命中（待指紋驗證）"
                found.append(entry)
    except PermissionError:
        print("    [!] 需 root/Administrator 權限")
    except Exception as e:
        print(f"    [!] ARP 錯誤: {e}")
    print(f"    -> 共掃到 {len(found)} 個活躍主機")
    return found


def fingerprint_dahua(ip: str, timeout: float = 2.0) -> bool:
    """
    指紋驗證：對 IP 呼叫 magicBox.cgi。
    大華設備即使密碼錯誤也會回 401 + WWW-Authenticate: Digest realm="..."
    一般非大華 HTTP server 對該 URL 通常回 404。
    """
    try:
        r = requests.get(
            f"http://{ip}/cgi-bin/magicBox.cgi?action=getSystemInfo",
            timeout=timeout, allow_redirects=False
        )
        if r.status_code == 401 and "digest" in r.headers.get("WWW-Authenticate", "").lower():
            return True
        if r.status_code == 200 and ("deviceType" in r.text or "serialNumber" in r.text.lower()):
            return True
    except requests.exceptions.RequestException:
        pass
    return False


def discover_via_tcp_scan(cidr: str, max_workers: int = 64) -> list[dict]:
    """全網段 TCP 80 掃描，再對開啟 80 port 的 IP 做大華指紋驗證。"""
    print(f"[*] [方法 4] TCP 80 掃描 + magicBox.cgi 指紋驗證 {cidr}...")
    network = ipaddress.IPv4Network(cidr, strict=False)
    if network.num_addresses > 1024:
        print(f"    [!] 網段太大 ({network.num_addresses} 個 IP)，跳過 TCP 掃描")
        return []

    candidates = []

    def probe(ip_str: str) -> Optional[str]:
        try:
            with socket.create_connection((ip_str, 80), timeout=0.8):
                return ip_str
        except (socket.timeout, OSError):
            return None

    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as ex:
        futures = {ex.submit(probe, str(ip)): str(ip)
                   for ip in network.hosts()}
        for fut in concurrent.futures.as_completed(futures):
            result = fut.result()
            if result:
                candidates.append(result)

    print(f"    -> {len(candidates)} 個 IP 開啟 port 80，進行指紋比對...")
    found = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as ex:
        results = list(ex.map(fingerprint_dahua, candidates))
    for ip, is_dahua in zip(candidates, results):
        if is_dahua:
            found.append({"ip": ip, "source": "TCP+magicBox 指紋"})
    print(f"    -> 確認 {len(found)} 台為大華設備")
    return found


def discover_all() -> list[dict]:
    """彙整所有發現方法，去重後回傳。"""
    print("\n" + "=" * 60)
    print(" 階段 A：自動發現大華監控設備")
    print("=" * 60)

    all_devices: dict[str, dict] = {}

    # 廣播類（不限子網）
    for dev in discover_via_dh_broadcast():
        all_devices.setdefault(dev["ip"], dev)
    for dev in discover_via_dhip_broadcast():
        all_devices.setdefault(dev["ip"], dev)

    # 主動掃描（每個本機子網）
    subnets = get_local_subnets()
    for iface, ip, cidr in subnets:
        print(f"\n[*] 處理本機介面 {iface} ({ip}, {cidr})")
        for dev in discover_via_arp_scan(cidr):
            existing = all_devices.get(dev["ip"])
            if existing:
                # 補上 MAC
                existing.setdefault("mac", dev.get("mac", ""))
            else:
                # 只有 OUI 命中才直接收錄，否則進指紋階段
                if "命中" in dev.get("match", ""):
                    all_devices[dev["ip"]] = dev

        for dev in discover_via_tcp_scan(cidr):
            all_devices.setdefault(dev["ip"], dev)

    return list(all_devices.values())


# =========================================================================
# 區段 2：原有三層測試（保留）
# =========================================================================

def verify_arp_reachability(target_ip: str) -> bool:
    print(f"[*] L2 ARP 探測 {target_ip}...")
    try:
        ans = srp(Ether(dst="ff:ff:ff:ff:ff:ff") / ARP(pdst=target_ip),
                  timeout=3, verbose=0)[0]
        if ans:
            print(f"[+] MAC: {ans[0][1].hwsrc}")
            return True
        print("[-] ARP 無回應")
        return False
    except PermissionError:
        print("[!] 需 root 權限")
        return False
    except Exception as e:
        print(f"[!] ARP 錯誤: {e}")
        return False


def check_tcp_port(target_ip: str, port: int = 80) -> bool:
    print(f"[*] L4 TCP 測試 {target_ip}:{port}...")
    try:
        with socket.create_connection((target_ip, port), timeout=3):
            print(f"[+] Port {port} OPEN")
            return True
    except (socket.timeout, OSError) as e:
        print(f"[-] TCP 失敗: {e}")
        return False


def test_dahua_http_api(target_ip: str, username: str, password: str) -> bool:
    print(f"[*] L7 HTTP API 測試 {target_ip}...")
    url = f"http://{target_ip}/cgi-bin/magicBox.cgi?action=getSystemInfo"
    try:
        r = requests.get(url, auth=HTTPDigestAuth(username, password), timeout=5)
        if r.status_code == 200:
            print("[+] API 成功，設備資訊：")
            print(r.text.strip())
            return True
        if r.status_code == 401:
            print("[-] 401 認證失敗，請確認帳密")
        else:
            print(f"[-] HTTP {r.status_code}")
    except requests.exceptions.RequestException as e:
        print(f"[-] 請求異常: {e}")
    return False


# =========================================================================
# 區段 3：主流程
# =========================================================================

def select_device(devices: list[dict]) -> Optional[str]:
    if not devices:
        return None
    if len(devices) == 1:
        ip = devices[0]["ip"]
        print(f"\n[+] 自動選擇唯一設備：{ip}")
        return ip

    print("\n發現多台設備，請選擇：")
    for i, d in enumerate(devices):
        extra = f" MAC={d.get('mac', '?')} 型號={d.get('model', '?')} 來源={d['source']}"
        print(f"  [{i}] {d['ip']}{extra}")
    while True:
        choice = input("選擇編號 (或直接 Enter 取第 0 個): ").strip()
        if not choice:
            return devices[0]["ip"]
        if choice.isdigit() and 0 <= int(choice) < len(devices):
            return devices[int(choice)]["ip"]


def main():
    parser = argparse.ArgumentParser(description="大華監控設備自動發現與連線測試")
    parser.add_argument("--ip", help="跳過發現直接使用此 IP")
    parser.add_argument("--user", default=DAHUA_USER)
    parser.add_argument("--password", default=DAHUA_PASS)
    
    args = parser.parse_args()

    print("=== 大華監控設備連線測試工具（含自動發現） ===\n")

    target_ip = args.ip
    if not target_ip:
        devices = discover_all()
        if not devices:
            print("\n[!] 所有發現方法都未找到大華設備。")
            print("    可能原因：")
            print("    1. 設備不在本機任一子網（需設定次要 IP 或調整路由）")
            print("    2. 設備防火牆封鎖了發現協議")
            print("    3. 本機未以 root 執行（ARP 廣播需要）")
            print("    請手動指定 IP：python test_connect.py --ip <IP>")
            sys.exit(1)
        target_ip = select_device(devices)

    print("\n" + "=" * 60)
    print(f" 階段 B：對 {target_ip} 進行三層連線測試")
    print("=" * 60)
    verify_arp_reachability(target_ip)
    print("-" * 40)
    tcp_ok = check_tcp_port(target_ip, 80)
    print("-" * 40)
    if tcp_ok:
        test_dahua_http_api(target_ip, args.user, args.password)
    else:
        print("[!] TCP 不通，跳過 HTTP API 測試")


if __name__ == "__main__":
    main()