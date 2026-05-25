"""LLM 调用：配置生成 / 验证命令生成 / 失败修正"""
import re
from openai import OpenAI


SYSTEM_PROMPT = """你是一个华为/H3C/Cisco 网络配置专家。用户会提供:
1. eNSP 拓扑文件的 XML 内容
2. 配置需求描述

你需要为拓扑中的每台设备生成完整的 CLI 配置命令。

输出格式（严格遵守）:

--设备名--
命令1
命令2
...
--设备名--
命令1
...

规则:
1. 接口命名: 参考拓扑 XML 中 <slot> 内的 <interface> 声明
2. 华为/H3C 命令: system-view 开头, return 结尾
3. 合理分配 IP 地址(若未指定则自行分配), 互联链路用 /30
4. PC 设备: 输出 IP 设置方案, 格式: IP:192.168.1.10 MASK:255.255.255.0 GATEWAY:192.168.1.1
5. 包含路由表、连通性所需的完整配置(接口IP、路由协议、VLAN等)
6. 每行一条命令, 不要注释, 不要解释
7. 确保配置顺序正确: 先 system-view, 接口配置, 协议配置, return"""

VERIFY_PROMPT = """你是一个网络验证专家。根据拓扑和配置要求，生成连通性测试命令列表。
每行一个命令，格式: 设备名:命令。
例如: R1:ping 10.0.2.2 或 R2:display ospf peer"""

FIX_PROMPT = """你是网络排错专家。根据测试失败信息，修正设备配置命令。
输出格式同上（--设备名-- + CLI 命令）。只输出需要修正的设备。"""


def _make_client(api_key: str, base_url: str | None) -> OpenAI:
    return OpenAI(api_key=api_key, base_url=base_url)


def generate_config(api_key: str, base_url: str | None, model: str,
                    topo_xml: str, requirement: str) -> dict[str, list[str]]:
    """返回 {设备名: [命令列表]}"""
    client = _make_client(api_key, base_url)
    resp = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user",
             "content": f"## 拓扑文件\n```xml\n{topo_xml}\n```\n\n"
                        f"## 配置要求\n{requirement}\n\n"},
        ],
        temperature=0.2,
    )
    return _parse_output(resp.choices[0].message.content)


def generate_verification(api_key: str, base_url: str | None, model: str,
                          topo_xml: str, requirement: str) -> list[tuple[str, str]]:
    """返回 [(设备名, 验证命令), ...]"""
    client = _make_client(api_key, base_url)
    resp = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": VERIFY_PROMPT},
            {"role": "user",
             "content": f"## 拓扑\n```xml\n{topo_xml}\n```\n## 配置要求\n{requirement}\n"},
        ],
        temperature=0.1,
    )
    cmds = []
    for line in resp.choices[0].message.content.split("\n"):
        m = re.match(r"(\S+)\s*[:：]\s*(.+)", line.strip())
        if m:
            cmds.append((m.group(1), m.group(2).strip()))
    return cmds


def fix_config(api_key: str, base_url: str | None, model: str,
               topo_xml: str, requirement: str,
               failures: list[tuple[str, str, str]]) -> dict[str, list[str]]:
    """根据失败信息返回修正后的配置"""
    client = _make_client(api_key, base_url)
    fail_text = "\n".join(f"{d}:{c} → {o}" for d, c, o in failures)
    resp = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": FIX_PROMPT},
            {"role": "user",
             "content": f"## 拓扑\n```xml\n{topo_xml}\n```\n"
                        f"## 原始需求\n{requirement}\n"
                        f"## 测试失败\n{fail_text}\n"},
        ],
        temperature=0.2,
    )
    return _parse_output(resp.choices[0].message.content)


def _parse_output(text: str) -> dict[str, list[str]]:
    """从 LLM 输出中按 --设备名-- 分割"""
    result = {}
    current_dev = None
    current_cmds = []
    for line in text.split("\n"):
        m = re.match(r"^--\s*(.+?)\s*--$", line.strip())
        if m:
            if current_dev and current_cmds:
                result[current_dev] = current_cmds
            current_dev = m.group(1).strip()
            current_cmds = []
        elif current_dev:
            s = line.strip()
            if s and not s.startswith("#") and not s.startswith("!"):
                current_cmds.append(s)
    if current_dev and current_cmds:
        result[current_dev] = current_cmds
    return result
