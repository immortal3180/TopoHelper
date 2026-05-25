"""Telnet / socket 操作：端口扫描、设备部署、验证执行"""
import re
import socket
import time
import xml.etree.ElementTree as ET


def d_encode(data: bytes) -> str:
    """自适应解码"""
    for enc in ("gb2312", "gbk", "utf-8"):
        try:
            return data.decode(enc)
        except Exception:
            pass
    return data.decode("latin-1")


def scan_port(ip: str, port: int, timeout=0.3) -> str | None:
    """探测一个端口，返回设备名或 None"""
    try:
        s = socket.create_connection((ip, port), timeout=timeout)
    except Exception:
        return None
    try:
        s.settimeout(1)
        s.sendall(b"\r\n")
        s.recv(4096)
        data = s.recv(4096)
        s.close()
        text = d_encode(data)
        m = re.search(r"[<\[](\S+)[>\]]", text)
        return m.group(1) if m else "?"
    except Exception:
        try:
            s.close()
        except Exception:
            pass
        return None


def is_port_open(ip: str, port: int, timeout=0.5) -> bool:
    try:
        s = socket.create_connection((ip, port), timeout=timeout)
        s.close()
        return True
    except Exception:
        return False


def deploy_commands(ip: str, port: int, commands: list[str], timeout=5) -> bool:
    """下发命令列表，成功返回 True"""
    try:
        s = socket.create_connection((ip, port), timeout=timeout)
    except Exception:
        return False
    try:
        s.settimeout(2)
        time.sleep(0.3)
        try:
            s.recv(4096)
        except Exception:
            pass
        for cmd in commands:
            if not cmd.strip():
                continue
            s.sendall(f"{cmd}\r\n".encode())
            time.sleep(0.15)
            old = s.gettimeout()
            s.settimeout(1)
            try:
                s.recv(4096)
            except Exception:
                pass
            s.settimeout(old)
            try:
                data = s.recv(4096)
                if b"---- More ----" in data:
                    s.sendall(b" \r\n")
            except Exception:
                pass
        s.close()
        return True
    except Exception:
        try:
            s.close()
        except Exception:
            pass
        return False


def exec_verification(ip: str, port: int, cmd: str, timeout=3) -> tuple[bool, str]:
    """执行验证命令，返回 (成功与否, 输出文本)"""
    try:
        s = socket.create_connection((ip, port), timeout=timeout)
    except Exception:
        return False, str(Exception("连接失败"))
    try:
        s.settimeout(2)
        s.sendall(b"\r\n")
        time.sleep(0.1)
        s.recv(4096)
        s.sendall(f"{cmd}\r\n".encode())
        time.sleep(0.3)
        data = b""
        try:
            while True:
                c = s.recv(4096)
                if not c:
                    break
                data += c
        except Exception:
            pass
        s.close()
        out = d_encode(data)
        success = any(kw in out.lower() for kw in
                      ["ttl=", "time=", "received", "up", "established", "full"])
        return success, out
    except Exception as e:
        try:
            s.close()
        except Exception:
            pass
        return False, str(e)


def get_device_port(topo_xml: str, device_name: str) -> int | None:
    try:
        root = ET.fromstring(topo_xml.encode())
        for dev in root.iter("dev"):
            if dev.attrib.get("name") == device_name:
                return int(dev.attrib.get("com_port", "0"))
    except Exception:
        pass
    return None


def is_pc(topo_xml: str, device_name: str) -> bool:
    try:
        root = ET.fromstring(topo_xml.encode())
        for dev in root.iter("dev"):
            if dev.attrib.get("name") == device_name:
                return dev.attrib.get("model", "") in ("PC", "pc")
    except Exception:
        pass
    return False


def get_all_devices(topo_xml: str) -> list[tuple[str, str, int]]:
    """返回 [(name, model, port), ...]"""
    try:
        root = ET.fromstring(topo_xml.encode())
    except Exception:
        return []
    devices = []
    for dev in root.iter("dev"):
        name = dev.attrib.get("name", "?")
        model = dev.attrib.get("model", "?")
        port = int(dev.attrib.get("com_port", "0"))
        devices.append((name, model, port))
    return devices
