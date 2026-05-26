"""
TopoHelper MCP Server
通过 stdin/stdout JSON-RPC 向 opencode 暴露网络配置工具
"""

import json
import sys
import traceback

# 强制 UTF-8 输入输出（MCP 协议要求）
sys.stdin.reconfigure(encoding="utf-8", errors="replace")
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from tools import scan_topo, deploy_config, verify

TOOLS = [
    {
        "name": "scan_topo",
        "description": "扫描 eNSP .topo 文件，返回所有设备及在线状态。请在任何部署操作之前先调用此工具。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": ".topo 文件的完整路径"},
                "ip": {"type": "string", "description": "eNSP 运行所在 IP，默认 127.0.0.1"},
            },
            "required": ["path"],
        },
    },
    {
        "name": "deploy_config",
        "description": "向指定设备下发配置命令列表。命令已通过 system-view 进入配置模式，不要以 system-view 开头。自动处理 screen-length、More 分页和 echo。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "topo_path": {"type": "string", "description": ".topo 文件路径"},
                "device": {"type": "string", "description": "设备名称，如 R1、SW1"},
                "commands": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "要下发的配置命令列表",
                },
                "ip": {"type": "string", "description": "eNSP 运行所在 IP，默认 127.0.0.1"},
            },
            "required": ["topo_path", "device", "commands"],
        },
    },
    {
        "name": "verify",
        "description": "在设备上执行验证命令并返回输出，用于检查连通性或配置是否正确。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "topo_path": {"type": "string", "description": ".topo 文件路径"},
                "device": {"type": "string", "description": "设备名称"},
                "command": {"type": "string", "description": "验证命令，如 ping 10.0.2.2"},
                "ip": {"type": "string", "description": "eNSP 运行所在 IP，默认 127.0.0.1"},
            },
            "required": ["topo_path", "device", "command"],
        },
    },
]


def _call_tool(name: str, args: dict) -> str:
    """执行工具，返回 JSON 字符串结果"""
    if name == "scan_topo":
        return json.dumps(scan_topo(args["path"], args.get("ip", "127.0.0.1")),
                          ensure_ascii=False)
    elif name == "deploy_config":
        return json.dumps(deploy_config(
            args["topo_path"], args["device"], args["commands"],
            args.get("ip", "127.0.0.1")), ensure_ascii=False)
    elif name == "verify":
        return json.dumps(verify(
            args["topo_path"], args["device"], args["command"],
            args.get("ip", "127.0.0.1")), ensure_ascii=False)
    return json.dumps({"error": f"未知工具: {name}"})


def _respond(req_id, result):
    resp = {"jsonrpc": "2.0", "id": req_id, "result": result}
    sys.stdout.write(json.dumps(resp, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def _error(req_id, code, msg):
    resp = {"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": msg}}
    sys.stdout.write(json.dumps(resp, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def main():
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except json.JSONDecodeError:
            continue

        method = req.get("method", "")
        req_id = req.get("id")

        try:
            if method == "initialize":
                _respond(req_id, {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "TopoHelper", "version": "0.2.0"},
                })

            elif method == "notifications/initialized":
                pass  # 无需回复

            elif method == "tools/list":
                _respond(req_id, {"tools": TOOLS})

            elif method == "tools/call":
                params = req.get("params", {})
                tool_name = params.get("name", "")
                tool_args = params.get("arguments", {})
                result_text = _call_tool(tool_name, tool_args)
                _respond(req_id, {
                    "content": [{"type": "text", "text": result_text}],
                })

            elif method == "ping":
                _respond(req_id, {})

            else:
                _error(req_id, -32601, f"未知方法: {method}")

        except Exception as e:
            _error(req_id, -32603, f"{e}\n{traceback.format_exc()}")


if __name__ == "__main__":
    main()
