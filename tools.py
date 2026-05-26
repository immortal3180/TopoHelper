"""MCP 工具实现：扫描拓扑 / 部署配置 / 验证连通性"""
import re
from pathlib import Path
from telnet import (get_all_devices, is_port_open, scan_port,
                     deploy_commands, exec_verification)


def scan_topo(path: str, ip: str = "127.0.0.1") -> dict:
    """扫描 .topo 文件，返回设备列表和在线状态"""
    raw = Path(path).read_bytes()
    raw = raw.replace(b'encoding="UNICODE"', b'encoding="UTF-8"')
    for enc in ("gb2312", "gbk", "gb18030", "utf-8"):
        try:
            raw.decode(enc)
            break
        except Exception:
            pass

    devices = get_all_devices(raw.decode("utf-8", errors="replace"))
    online = []
    offline = []
    for name, model, port in devices:
        if port == 0:
            offline.append({"name": name, "model": model, "reason": "PC 或无 Console 端口"})
        elif is_port_open(ip, port):
            device_name = scan_port(ip, port) or "?"
            online.append({"name": name, "model": model, "port": port, "prompt": device_name})
        else:
            offline.append({"name": name, "model": model, "port": port, "reason": "设备未启动"})

    return {
        "topo_path": path,
        "total": len(devices),
        "online": len(online),
        "online_devices": online,
        "offline_devices": offline,
    }


def deploy_config(topo_path: str, device: str, commands: list[str],
                  ip: str = "127.0.0.1") -> dict:
    """向指定设备下发配置命令列表"""
    # 从 .topo 获取端口
    raw = Path(topo_path).read_bytes()
    raw = raw.replace(b'encoding="UNICODE"', b'encoding="UTF-8"')
    from telnet import get_device_port, is_pc

    port = get_device_port(raw.decode("utf-8", errors="replace"), device)
    if port is None or port == 0:
        if is_pc(raw.decode("utf-8", errors="replace"), device):
            return {
                "success": True,
                "device": device,
                "method": "manual",
                "message": "PC 设备，请在 eNSP GUI 中手动配置 IP",
                "commands_for_reference": commands,
            }
        return {"success": False, "device": device, "error": "设备无 Console 端口"}

    if not is_port_open(ip, port):
        return {"success": False, "device": device, "port": port, "error": f"设备不在线 ({ip}:{port})"}

    success = deploy_commands(ip, port, commands)
    if success:
        return {"success": True, "device": device, "port": port,
                "commands_sent": len(commands)}
    else:
        return {"success": False, "device": device, "port": port,
                "error": "下发后检测到 Error/Incomplete/Unrecognized",
                "commands_sent": len(commands)}


def verify(topo_path: str, device: str, command: str,
           ip: str = "127.0.0.1") -> dict:
    """在指定设备上执行验证命令并返回结果"""
    raw = Path(topo_path).read_bytes()
    raw = raw.replace(b'encoding="UNICODE"', b'encoding="UTF-8"')
    from telnet import get_device_port

    port = get_device_port(raw.decode("utf-8", errors="replace"), device)
    if not port:
        return {"success": False, "device": device, "error": "设备无 Console 端口"}

    ok, output = exec_verification(ip, port, command)
    return {
        "success": ok,
        "device": device,
        "command": command,
        "output": output[:500],
    }
