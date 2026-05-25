"""
TopoHelper — 自然语言驱动的网络配置全流程工具
步骤 1-9 集成在一个 GUI 中
"""

import json
import os
import re
import shutil
import socket
import subprocess
import sys as _sys
import time
import xml.etree.ElementTree as ET
import tkinter as tk
from datetime import datetime
from pathlib import Path
from threading import Thread
from tkinter import filedialog, messagebox, ttk

from openai import OpenAI

# ── 全局状态 ──────────────────────────────────────────────

topo_path = ""
topo_xml = ""
log_lines = []
sock = None
generated_config = {}  # {设备名: [命令列表]}
current_ip = "127.0.0.1"

# 配置文件路径（与 .exe 同目录）
_config_dir = Path(_sys.argv[0]).parent if hasattr(_sys, "argv") else Path(".")
CONFIG_FILE = _config_dir / "topohelper.json"


def _save_config():
    """保存 LLM 配置到本地文件"""
    try:
        data = {
            "key": key_var.get().strip(),
            "url": url_var.get().strip(),
            "model": model_var.get().strip(),
        }
        CONFIG_FILE.write_text(json.dumps(data), encoding="utf-8")
    except:
        pass


def _load_config():
    """启动时加载本地配置并填充界面"""
    if not CONFIG_FILE.exists():
        return
    try:
        data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        if data.get("key"):
            key_var.set(data["key"])
        if data.get("url"):
            url_var.set(data["url"])
        if data.get("model"):
            model_var.set(data["model"])
    except:
        pass


def log(msg: str):
    """写日志"""
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    log_lines.append(line)
    root.after(0, lambda: _log_to_ui(line))


def _log_to_ui(line: str):
    log_text.insert("end", line + "\n")
    log_text.see("end")
    # 同时写文件
    try:
        with open("topo_helper.log", "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except:
        pass


# ── 步骤 2+5: 发现 .topo + 扫描设备 ─────────────────────────

def browse_topo():
    global topo_path, topo_xml
    path = filedialog.askopenfilename(filetypes=[("eNSP topo", "*.topo")])
    if not path:
        return
    topo_path = path
    topo_file_var.set(path)
    try:
        raw = Path(path).read_bytes()
        raw = raw.replace(b'encoding="UNICODE"', b'encoding="UTF-8"')
        # 尝试多种编码解码
        for enc in ("gb2312", "gbk", "gb18030", "utf-8"):
            try:
                topo_xml = raw.decode(enc)
                break
            except:
                continue
        else:
            topo_xml = raw.decode("utf-8", errors="replace")
        log(f"已加载: {path}")
        scan_devices()
    except Exception as e:
        log(f"加载失败: {e}")


def scan_devices():
    global current_ip
    current_ip = ip_var.get().strip() or "127.0.0.1"
    device_list.delete(0, "end")
    device_list.insert("end", "扫描中...")
    btn_scan.config(state="disabled")

    def _s():
        try:
            raw = topo_xml.encode()
            root_el = ET.fromstring(raw)
        except:
            root.after(0, lambda: device_list.delete(0, "end"))
            root.after(0, lambda: device_list.insert("end", "请先加载 .topo"))
            root.after(0, lambda: btn_scan.config(state="normal"))
            return

        devices = []
        for dev in root_el.iter("dev"):
            name = dev.attrib.get("name", "?")
            model = dev.attrib.get("model", "?")
            port = int(dev.attrib.get("com_port", "0"))
            if port > 0:
                devices.append((name, model, port))

        root.after(0, lambda: device_list.delete(0, "end"))
        for name, model, port in devices:
            # 检查在线
            alive = False
            try:
                s = socket.create_connection((current_ip, port), timeout=0.3)
                s.settimeout(1)
                s.sendall(b"\r\n")
                s.recv(4096)
                s.close()
                alive = True
            except:
                pass
            status = "在线" if alive else "离线"
            display = f"{name:8s} {model:10s} {current_ip}:{port}  {status}"
            root.after(0, lambda d=display: device_list.insert("end", d))

        online = sum(1 for d in devices if "在线" in d[0] if False)  # placeholder
        n_online = 0
        for _, _, port in devices:
            try:
                s = socket.create_connection((current_ip, port), timeout=0.3)
                s.close()
                n_online += 1
            except:
                pass
        log(f"扫描完成: {len(devices)} 台设备, {n_online} 在线")
        root.after(0, lambda: btn_scan.config(state="normal"))

    Thread(target=_s, daemon=True).start()


# ── 步骤 3: LLM 生成配置 ───────────────────────────────────

def generate_config():
    global generated_config
    if not topo_xml:
        messagebox.showwarning("提示", "请先加载 .topo 文件")
        return

    requirement = req_text.get("1.0", "end").strip()
    if not requirement:
        messagebox.showwarning("提示", "请输入配置要求")
        return

    api_key = key_var.get().strip()
    model = model_var.get().strip() or "gpt-4o"
    base_url = url_var.get().strip() or None

    if not api_key:
        import os
        api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        messagebox.showwarning("提示", "请填写 API Key")
        return

    btn_gen.config(state="disabled", text="生成中...")
    log("正在调用 LLM 生成配置...")

    def _g():
        try:
            client = OpenAI(api_key=api_key, base_url=base_url)
            resp = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user",
                     "content": f"## 拓扑文件\n```xml\n{topo_xml}\n```\n\n"
                                f"## 配置要求\n{requirement}\n\n"
                                f"## 输出\n请按指定格式输出每台设备的配置命令。PC 设备请给出 IP 设置方案。"},
                ],
                temperature=0.2,
            )
            text = resp.choices[0].message.content
            root.after(0, lambda: _parse_config(text))
        except Exception as e:
            log(f"LLM 调用失败: {e}")
            root.after(0, lambda: btn_gen.config(state="normal", text="生成配置"))

    Thread(target=_g, daemon=True).start()


def _parse_config(text: str):
    """从 LLM 输出中按 --设备名-- 分割"""
    global generated_config
    generated_config = {}
    current_dev = None
    current_cmds = []

    for line in text.split("\n"):
        m = re.match(r"^--\s*(.+?)\s*--$", line.strip())
        if m:
            if current_dev and current_cmds:
                generated_config[current_dev] = current_cmds
            current_dev = m.group(1).strip()
            current_cmds = []
        elif current_dev:
            stripped = line.strip()
            if stripped and not stripped.startswith("#") and not stripped.startswith("!"):
                current_cmds.append(stripped)
    if current_dev and current_cmds:
        generated_config[current_dev] = current_cmds

    # 显示预览
    preview_text.delete("1.0", "end")
    for dev, cmds in generated_config.items():
        preview_text.insert("end", f"── {dev} ──\n")
        for c in cmds:
            preview_text.insert("end", f"  {c}\n")
        preview_text.insert("end", "\n")

    log(f"配置生成完成: {len(generated_config)} 台设备")
    _save_config()
    btn_gen.config(state="normal", text="生成配置")
    btn_deploy.config(state="normal")


# ── 步骤 6: 批量部署 ───────────────────────────────────────

def deploy_all():
    global generated_config, current_ip
    if not generated_config:
        messagebox.showwarning("提示", "请先生成配置")
        return

    ans = messagebox.askyesno("确认部署", f"将向 {len(generated_config)} 台设备下发配置，确认？")
    if not ans:
        return

    btn_deploy.config(state="disabled", text="部署中...")
    log(f"开始批量部署 (目标 {current_ip})...")

    def _d():
        ok = 0
        fail = 0
        for dev_name, cmds in generated_config.items():
            log(f"→ {dev_name}: {len(cmds)} 条命令")
            port = _get_port(dev_name)
            if port is None or port == 0:
                if _is_pc(dev_name):
                    log(f"  {dev_name}: PC 设备，请根据生成的配置手动设置 IP")
                    ok += 1
                else:
                    log(f"  {dev_name}: 无 com_port, 跳过")
                    fail += 1
                continue

            # Telnet 部署
            # 先确认在线
            try:
                test = socket.create_connection((current_ip, port), timeout=2)
                test.close()
            except:
                log(f"  {dev_name}: 设备不在线 ({current_ip}:{port})")
                fail += 1
                continue

            try:
                s = socket.create_connection((current_ip, port), timeout=5)
                s.settimeout(2)
                time.sleep(0.3)
                # 收初始输出
                try:
                    s.recv(4096)
                except:
                    pass
                for cmd in cmds:
                    if not cmd.strip():
                        continue
                    s.sendall(f"{cmd}\r\n".encode())
                    time.sleep(0.15)
                    # 吃掉 echo
                    old = s.gettimeout()
                    s.settimeout(1)
                    try:
                        s.recv(4096)
                    except:
                        pass
                    s.settimeout(old)
                    # 检查 More
                    try:
                        data = s.recv(4096)
                        if b"---- More ----" in data:
                            s.sendall(b" \r\n")
                    except:
                        pass
                s.close()
                log(f"  {dev_name}: {len(cmds)} 条下发完成")
                ok += 1
            except Exception as e:
                log(f"  {dev_name}: 连接失败 ({e})")
                fail += 1

        log(f"部署完成: {ok} 成功, {fail} 失败")
        root.after(0, lambda: btn_deploy.config(state="normal", text="部署"))

        # 如果全部成功 → 自动进入验证
        if fail == 0:
            log("→ 进入连通性验证")
            root.after(500, verify_connectivity)

    Thread(target=_d, daemon=True).start()


def _get_port(dev_name: str) -> int | None:
    try:
        root_el = ET.fromstring(topo_xml.encode())
        for dev in root_el.iter("dev"):
            if dev.attrib.get("name") == dev_name:
                return int(dev.attrib.get("com_port", "0"))
    except:
        pass
    return None


def _is_pc(dev_name: str) -> bool:
    try:
        root_el = ET.fromstring(topo_xml.encode())
        for dev in root_el.iter("dev"):
            if dev.attrib.get("name") == dev_name:
                return dev.attrib.get("model", "") in ("PC", "pc")
    except:
        pass
    return False


# ── 步骤 7+8: 连通性验证 ───────────────────────────────────

retry_count = 0
MAX_RETRIES = 2


def verify_connectivity():
    global retry_count
    log("连通性验证: 生成测试命令...")

    requirement = req_text.get("1.0", "end").strip()
    api_key = key_var.get().strip()
    model = model_var.get().strip() or "gpt-4o"
    base_url = url_var.get().strip() or None
    if not api_key:
        import os
        api_key = os.getenv("OPENAI_API_KEY")

    def _v():
        global retry_count
        try:
            client = OpenAI(api_key=api_key, base_url=base_url)
            resp = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system",
                     "content": "你是一个网络验证专家。根据拓扑和配置要求，生成连通性测试命令列表。"
                                "每行一个命令，格式: 设备名:命令。"
                                "例如: R1:ping 10.0.2.2 或 R2:display ospf peer"},
                    {"role": "user",
                     "content": f"## 拓扑\n```xml\n{topo_xml}\n```\n"
                                f"## 配置要求\n{requirement}\n"
                                f"## 输出\n列出验证连通性的具体命令"},
                ],
                temperature=0.1,
            )
            text = resp.choices[0].message.content
            test_cmds = []
            for line in text.split("\n"):
                m = re.match(r"(\S+)\s*[:：]\s*(.+)", line.strip())
                if m:
                    test_cmds.append((m.group(1), m.group(2).strip()))
        except Exception as e:
            log(f"验证命令生成失败: {e}")
            return

        if not test_cmds:
            log("无验证命令生成，跳过")
            return

        log(f"→ 执行 {len(test_cmds)} 条测试命令")
        failures = []
        for dev_name, cmd in test_cmds:
            port = _get_port(dev_name)
            if not port:
                continue
            try:
                s = socket.create_connection((current_ip, port), timeout=3)
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
                        if not c: break
                        data += c
                except:
                    pass
                s.close()
                out = data.decode("gb2312", errors="replace")
                # 简单判断
                success = any(kw in out.lower() for kw in
                              ["ttl=", "time=", "received", "up", "established", "full"])
                status = "✓" if success else "✗"
                log(f"  {dev_name}:{cmd}  {status}")
                if not success:
                    failures.append((dev_name, cmd, out[:200]))
            except Exception as e:
                log(f"  {dev_name}:{cmd}  执行失败 ({e})")
                failures.append((dev_name, cmd, str(e)))

        if not failures:
            log("✓ 全连通性测试通过")
            btn_gen.config(state="normal")
            return

        # 有失败
        retry_count += 1
        log(f"✗ {len(failures)} 项测试失败 (第{retry_count}次)")

        if retry_count > MAX_RETRIES:
            log(f"已达最大重试次数 {MAX_RETRIES}，请手动排查")
            retry_count = 0
            btn_gen.config(state="normal")
            return

        # 重试：让 LLM 分析失败并修正
        log("→ 正在分析失败原因...")
        fail_text = "\n".join(f"{d}:{c} → {o}" for d, c, o in failures)
        try:
            resp = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system",
                     "content": "你是网络排错专家。根据测试失败信息，修正设备配置命令。"
                                "输出格式同上（--设备名-- + CLI 命令）。只输出需要修正的设备。"},
                    {"role": "user",
                     "content": f"## 拓扑\n```xml\n{topo_xml}\n```\n"
                                f"## 原始配置要求\n{requirement}\n"
                                f"## 测试失败\n{fail_text}\n"
                                f"## 修正后的配置"},
                ],
                temperature=0.2,
            )
            fix_text = resp.choices[0].message.content
            # 重新解析修正配置
            global generated_config
            generated_config = {}
            cur_d = None
            cur_c = []
            for line in fix_text.split("\n"):
                m = re.match(r"^--\s*(.+?)\s*--$", line.strip())
                if m:
                    if cur_d and cur_c:
                        generated_config[cur_d] = cur_c
                    cur_d = m.group(1).strip()
                    cur_c = []
                elif cur_d:
                    s = line.strip()
                    if s and not s.startswith("#") and not s.startswith("!"):
                        cur_c.append(s)
            if cur_d and cur_c:
                generated_config[cur_d] = cur_c

            log(f"修正完成: {len(generated_config)} 台设备 → 重新部署")
            _redeploy_and_verify()
        except Exception as e:
            log(f"修正失败: {e}")
            retry_count = 0
            btn_gen.config(state="normal")

    Thread(target=_v, daemon=True).start()


def _redeploy_and_verify():
    """重试：部署修正配置 → 再次验证"""
    global current_ip

    def _rd():
        ok, fail = 0, 0
        for dev_name, cmds in generated_config.items():
            port = _get_port(dev_name)
            if not port:
                continue
            try:
                s = socket.create_connection((current_ip, port), timeout=3)
                s.settimeout(0.5)
                s.recv(4096)
                for cmd in cmds:
                    if not cmd.strip(): continue
                    s.sendall(f"{cmd}\r\n".encode())
                    time.sleep(0.1)
                    old = s.gettimeout()
                    s.settimeout(0.5)
                    try: s.recv(4096)
                    except: pass
                    s.settimeout(old)
                    try:
                        d = s.recv(4096)
                        if b"---- More ----" in d:
                            s.sendall(b" \r\n")
                    except: pass
                s.close()
                log(f"  修正: {dev_name} {len(cmds)}条 ✓")
                ok += 1
            except Exception as e:
                log(f"  修正: {dev_name} 失败 ({e})")
                fail += 1
        log(f"修正部署完成, 重新验证...")
        root.after(500, verify_connectivity)

    Thread(target=_rd, daemon=True).start()


# ── LLM 提示词 ─────────────────────────────────────────────

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


def _open_terminal(event=None):
    """双击设备行打开终端，优先 PuTTY（跨平台），否则系统 telnet"""
    sel = device_list.curselection()
    if not sel:
        return
    line = device_list.get(sel[0])
    m = re.search(r"(\d+\.\d+\.\d+\.\d+):(\d+)", line)
    if not m:
        return
    ip = m.group(1)
    port = m.group(2)

    putty = shutil.which("putty") or shutil.which("putty.exe")
    if putty:
        subprocess.Popen([putty, "-telnet", ip, "-P", port],
                         creationflags=subprocess.CREATE_NO_WINDOW if _sys.platform == "win32" else 0)
        return

    # 回退系统 telnet
    if _sys.platform == "win32":
        os.system(f"start telnet {ip} {port}")
    elif _sys.platform == "darwin":
        subprocess.Popen(["osascript", "-e",
                          f'tell app "Terminal" to do script "telnet {ip} {port}"'])
    else:
        for term in ["x-terminal-emulator", "gnome-terminal", "konsole", "xfce4-terminal"]:
            if shutil.which(term):
                subprocess.Popen([term, "-e", f"telnet {ip} {port}"])
                break
        else:
            subprocess.Popen(["telnet", ip, port])


# ── GUI 布局 ───────────────────────────────────────────────

root = tk.Tk()
root.title("TopoHelper")
root.geometry("900x650")

# 主容器
container = tk.Frame(root)
container.pack(fill="both", expand=True)

left = tk.Frame(container, bg="#1e1e2e")
left.pack(side="left", fill="both", expand=True)

# 侧边栏容器（日志面板 + 伸缩条）
right_wrapper = tk.Frame(container, bg="#45475a")
right_wrapper.pack(side="right", fill="y")
right_visible = True

# 伸缩按钮（始终可见）
toggle_bar = tk.Frame(right_wrapper, bg="#45475a", width=6)
toggle_bar.pack(side="left", fill="y")
toggle_label = tk.Label(toggle_bar, text="◀", bg="#45475a", fg="#cdd6f4",
                         font=("", 8), cursor="hand2")
toggle_label.pack(expand=True)

# 日志面板
right = tk.Frame(right_wrapper, bg="#181825", width=300)
right.pack(side="left", fill="both", expand=True)

def _toggle_log():
    global right_visible
    if right_visible:
        right.pack_forget()
        right_visible = False
        toggle_label.config(text="▶")
    else:
        right.pack(side="left", fill="both", expand=True)
        right_visible = True
        toggle_label.config(text="◀")

toggle_label.bind("<Button-1>", lambda e: _toggle_log())

# ── 左侧面板 ──

# .topo 文件
tk.Label(left, text=".topo 文件", bg="#1e1e2e", fg="#cdd6f4",
         font=("", 10, "bold")).pack(anchor="w", padx=10, pady=(10, 0))
f1 = tk.Frame(left, bg="#1e1e2e")
f1.pack(fill="x", padx=10)
topo_file_var = tk.StringVar(value="未选择")
tk.Entry(f1, textvariable=topo_file_var, state="readonly", width=35,
         bg="#313244", fg="#cdd6f4").pack(side="left")
tk.Button(f1, text="浏览", command=browse_topo, width=6,
          bg="#45475a", fg="#cdd6f4").pack(side="left", padx=5)

# 设备列表
tk.Label(left, text="设备列表", bg="#1e1e2e", fg="#cdd6f4",
         font=("", 10, "bold")).pack(anchor="w", padx=10, pady=(10, 0))
f2 = tk.Frame(left, bg="#1e1e2e")
f2.pack(fill="x", padx=10)
tk.Label(f2, text="IP:", bg="#1e1e2e", fg="#a6adc8").pack(side="left")
ip_var = tk.StringVar(value="127.0.0.1")
tk.Entry(f2, textvariable=ip_var, width=18, bg="#313244", fg="#cdd6f4").pack(side="left", padx=5)
btn_scan = tk.Button(f2, text="扫描", command=scan_devices, width=6, bg="#45475a", fg="#cdd6f4")
btn_scan.pack(side="left")

device_list = tk.Listbox(left, bg="#11111b", fg="#a6e3a1",
                          font=("Consolas", 10), selectbackground="#45475a")
device_list.pack(fill="both", expand=True, padx=10, pady=5)
device_list.bind("<Double-Button-1>", _open_terminal)

# 配置要求
tk.Label(left, text="配置要求", bg="#1e1e2e", fg="#cdd6f4",
         font=("", 10, "bold")).pack(anchor="w", padx=10, pady=(10, 0))
req_text = tk.Text(left, height=4, bg="#11111b", fg="#cdd6f4", font=("", 10),
                    insertbackground="#cdd6f4")
req_text.pack(fill="x", padx=10)

# LLM 配置
tk.Label(left, text="LLM 配置", bg="#1e1e2e", fg="#cdd6f4",
         font=("", 10, "bold")).pack(anchor="w", padx=10, pady=(10, 0))
f3 = tk.Frame(left, bg="#1e1e2e")
f3.pack(fill="x", padx=10)
tk.Label(f3, text="Key:", bg="#1e1e2e", fg="#a6adc8", width=4).pack(side="left")
key_var = tk.StringVar()
tk.Entry(f3, textvariable=key_var, width=28, show="*", bg="#313244", fg="#cdd6f4").pack(side="left")
f4 = tk.Frame(left, bg="#1e1e2e")
f4.pack(fill="x", padx=10, pady=2)
tk.Label(f4, text="URL:", bg="#1e1e2e", fg="#a6adc8", width=4).pack(side="left")
url_var = tk.StringVar(value="https://api.openai.com/v1")
tk.Entry(f4, textvariable=url_var, width=28, bg="#313244", fg="#cdd6f4").pack(side="left")
f5 = tk.Frame(left, bg="#1e1e2e")
f5.pack(fill="x", padx=10, pady=2)
tk.Label(f5, text="Model:", bg="#1e1e2e", fg="#a6adc8", width=4).pack(side="left")
model_var = tk.StringVar(value="gpt-4o")
tk.Entry(f5, textvariable=model_var, width=28, bg="#313244", fg="#cdd6f4").pack(side="left")

# 按钮
f6 = tk.Frame(left, bg="#1e1e2e")
f6.pack(fill="x", padx=10, pady=10)
btn_gen = tk.Button(f6, text="生成配置", command=generate_config,
                     bg="#89b4fa", fg="#1e1e2e", font=("", 10, "bold"), width=12)
btn_gen.pack(side="left")
btn_deploy = tk.Button(f6, text="部署", command=deploy_all, state="disabled",
                        bg="#a6e3a1", fg="#1e1e2e", font=("", 10, "bold"), width=8)
btn_deploy.pack(side="left", padx=5)

# 配置预览
tk.Label(left, text="配置预览", bg="#1e1e2e", fg="#cdd6f4",
         font=("", 10, "bold")).pack(anchor="w", padx=10, pady=(5, 0))
preview_text = tk.Text(left, bg="#11111b", fg="#a6e3a1",
                        font=("Consolas", 9), state="normal")
preview_text.pack(fill="both", expand=True, padx=10, pady=(0, 10))

# ── 右侧面板: 日志 ──

log_text = tk.Text(right, bg="#11111b", fg="#cdd6f4", font=("Consolas", 9),
                    state="normal")
log_text.pack(fill="both", expand=True, padx=10, pady=(0, 10))

# 日志标题
tk.Label(right, text="执行日志", bg="#181825", fg="#cdd6f4",
         font=("", 10, "bold")).pack(anchor="w", padx=10, pady=(10, 0))

def main():
    log("topo-helper 启动就绪")
    _load_config()
    root.mainloop()


if __name__ == "__main__":
    main()
