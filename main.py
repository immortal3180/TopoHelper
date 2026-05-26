"""
TopoHelper GUI — 布局 + 事件绑定
调用 llm / telnet / config 模块完成业务逻辑
"""

import os
import re
import shutil
import socket
import subprocess
import sys as _sys
import time
import tkinter as tk
from datetime import datetime
from pathlib import Path
from threading import Thread
from tkinter import filedialog, messagebox

from config import CONFIG_FILE, save as cfg_save, load as cfg_load
from llm import generate_config, generate_verification, fix_config
from telnet import (d_encode, scan_port, is_port_open, deploy_commands,
                     exec_verification, get_device_port, is_pc, get_all_devices)

# ── 全局状态 ──────────────────────────────────────────────

topo_path = ""
topo_xml = ""
log_lines = []
sock = None
generated_config: dict[str, list[str]] = {}
current_ip = "127.0.0.1"
retry_count = 0
MAX_RETRIES = 2


def log(msg: str):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    log_lines.append(line)
    root.after(0, lambda: _log_to_ui(line))


def _log_to_ui(line: str):
    log_text.insert("end", line + "\n")
    log_text.see("end")
    try:
        with open("topo_helper.log", "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


# ── 步骤 2: 加载 .topo ─────────────────────────────────────

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
        for enc in ("gb2312", "gbk", "gb18030", "utf-8"):
            try:
                topo_xml = raw.decode(enc)
                break
            except Exception:
                continue
        else:
            topo_xml = raw.decode("utf-8", errors="replace")
        log(f"已加载: {path}")
        scan_devices()
    except Exception as e:
        log(f"加载失败: {e}")


# ── 步骤 5: 扫描设备 ───────────────────────────────────────

def scan_devices():
    global current_ip
    current_ip = ip_var.get().strip() or "127.0.0.1"
    device_list.delete(0, "end")
    device_list.insert("end", "扫描中...")
    btn_scan.config(state="disabled")

    def _s():
        devices = get_all_devices(topo_xml)
        online_ports = []
        # 检查在线
        for name, model, port in devices:
            if port > 0:
                if is_port_open(current_ip, port):
                    online_ports.append(port)

        root.after(0, lambda: device_list.delete(0, "end"))
        for name, model, port in devices:
            status = "在线" if port > 0 and port in online_ports else ("离线" if port > 0 else "无Telnet")
            display = f"{name:8s} {model:10s} {current_ip}:{port}  {status}"
            root.after(0, lambda d=display: device_list.insert("end", d))

        log(f"扫描完成: {len(devices)} 台, {len(online_ports)} 在线")
        root.after(0, lambda: btn_scan.config(state="normal"))

    Thread(target=_s, daemon=True).start()


# ── 步骤 3: LLM 生成配置 ───────────────────────────────────

def gen_config():
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
        api_key = os.getenv("OPENAI_API_KEY", "")
    if not api_key:
        messagebox.showwarning("提示", "请填写 API Key")
        return

    btn_gen.config(state="disabled", text="生成中...")
    log("正在调用 LLM 生成配置...")

    def _g():
        try:
            global generated_config
            generated_config = generate_config(api_key, base_url, model, topo_xml, requirement)
            root.after(0, _show_preview)
        except Exception as e:
            log(f"LLM 调用失败: {e}")
            root.after(0, lambda: btn_gen.config(state="normal", text="生成配置"))

    Thread(target=_g, daemon=True).start()


def _show_preview():
    preview_text.delete("1.0", "end")
    for dev, cmds in generated_config.items():
        preview_text.insert("end", f"── {dev} ──\n")
        for c in cmds:
            preview_text.insert("end", f"  {c}\n")
        preview_text.insert("end", "\n")
    log(f"配置生成完成: {len(generated_config)} 台设备")
    cfg_save(key_var.get().strip(), url_var.get().strip(), model_var.get().strip())
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
            port = get_device_port(topo_xml, dev_name)
            if port is None or port == 0:
                if is_pc(topo_xml, dev_name):
                    log(f"  {dev_name}: PC 设备，请根据生成的配置手动设置 IP")
                    ok += 1
                else:
                    log(f"  {dev_name}: 无 com_port, 跳过")
                    fail += 1
                continue
            if not is_port_open(current_ip, port):
                log(f"  {dev_name}: 设备不在线 ({current_ip}:{port})")
                fail += 1
                continue
            if deploy_commands(current_ip, port, cmds):
                log(f"  {dev_name}: {len(cmds)} 条下发完成")
                ok += 1
            else:
                log(f"  {dev_name}: 部署异常（Error/Incomplete/Unrecognized）")
                fail += 1
        log(f"部署完成: {ok} 成功, {fail} 失败")
        root.after(0, lambda: btn_deploy.config(state="normal", text="部署"))
        if fail == 0:
            log("→ 进入连通性验证")
            root.after(500, verify_connectivity)

    Thread(target=_d, daemon=True).start()


# ── 步骤 7+8: 连通性验证 ───────────────────────────────────

def verify_connectivity():
    global retry_count
    log("连通性验证: 生成测试命令...")
    requirement = req_text.get("1.0", "end").strip()
    api_key = key_var.get().strip() or os.getenv("OPENAI_API_KEY", "")
    model = model_var.get().strip() or "gpt-4o"
    base_url = url_var.get().strip() or None

    def _v():
        global retry_count
        try:
            test_cmds = generate_verification(api_key, base_url, model, topo_xml, requirement)
        except Exception as e:
            log(f"验证命令生成失败: {e}")
            return
        if not test_cmds:
            log("无验证命令生成，跳过")
            return
        log(f"→ 执行 {len(test_cmds)} 条测试命令")
        failures = []
        for dev_name, cmd in test_cmds:
            port = get_device_port(topo_xml, dev_name)
            if not port:
                continue
            success, out = exec_verification(current_ip, port, cmd)
            status = "✓" if success else "✗"
            log(f"  {dev_name}:{cmd}  {status}")
            if not success:
                failures.append((dev_name, cmd, out[:200]))
        if not failures:
            log("✓ 全连通性测试通过")
            retry_count = 0
            return
        retry_count += 1
        log(f"✗ {len(failures)} 项测试失败 (第{retry_count}次)")
        if retry_count > MAX_RETRIES:
            log(f"已达最大重试次数 {MAX_RETRIES}，请手动排查")
            retry_count = 0
            return
        log("→ 正在分析失败原因...")
        try:
            global generated_config
            generated_config = fix_config(api_key, base_url, model, topo_xml, requirement, failures)
            log(f"修正完成: {len(generated_config)} 台 → 重新部署")
            _redeploy_and_verify()
        except Exception as e:
            log(f"修正失败: {e}")
            retry_count = 0

    Thread(target=_v, daemon=True).start()


def _redeploy_and_verify():
    def _rd():
        ok, fail = 0, 0
        for dev_name, cmds in generated_config.items():
            port = get_device_port(topo_xml, dev_name)
            if not port:
                continue
            if deploy_commands(current_ip, port, cmds):
                log(f"  修正: {dev_name} {len(cmds)}条 ✓")
                ok += 1
            else:
                log(f"  修正: {dev_name} 失败")
                fail += 1
        log("修正部署完成, 重新验证...")
        root.after(500, verify_connectivity)
    Thread(target=_rd, daemon=True).start()


# ── 双击设备行 → 打开终端 ─────────────────────────────────

def _open_terminal(event=None):
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
    if _sys.platform == "win32":
        os.system(f"start telnet {ip} {port}")
    elif _sys.platform == "darwin":
        subprocess.Popen(["osascript", "-e", f'tell app "Terminal" to do script "telnet {ip} {port}"'])
    else:
        for term in ["x-terminal-emulator", "gnome-terminal", "konsole", "xfce4-terminal"]:
            if shutil.which(term):
                subprocess.Popen([term, "-e", f"telnet {ip} {port}"])
                break
        else:
            subprocess.Popen(["telnet", ip, port])


# ── 侧边栏伸缩 ─────────────────────────────────────────────

right_visible = True

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


# ── GUI 布局 ───────────────────────────────────────────────

root = tk.Tk()
root.title("TopoHelper")
root.geometry("900x650")

container = tk.Frame(root)
container.pack(fill="both", expand=True)

left = tk.Frame(container, bg="#1e1e2e")
left.pack(side="left", fill="both", expand=True)

right_wrapper = tk.Frame(container, bg="#45475a")
right_wrapper.pack(side="right", fill="y")

toggle_bar = tk.Frame(right_wrapper, bg="#45475a", width=6)
toggle_bar.pack(side="left", fill="y")
toggle_label = tk.Label(toggle_bar, text="◀", bg="#45475a", fg="#cdd6f4",
                         font=("", 8), cursor="hand2")
toggle_label.pack(expand=True)
toggle_label.bind("<Button-1>", lambda e: _toggle_log())

right = tk.Frame(right_wrapper, bg="#181825", width=300)
right.pack(side="left", fill="both", expand=True)

# ── 左侧面板 ──

tk.Label(left, text=".topo 文件", bg="#1e1e2e", fg="#cdd6f4",
         font=("", 10, "bold")).pack(anchor="w", padx=10, pady=(10, 0))
f1 = tk.Frame(left, bg="#1e1e2e")
f1.pack(fill="x", padx=10)
topo_file_var = tk.StringVar(value="未选择")
tk.Entry(f1, textvariable=topo_file_var, state="readonly", width=35,
         bg="#313244", fg="#cdd6f4").pack(side="left")
tk.Button(f1, text="浏览", command=browse_topo, width=6,
          bg="#45475a", fg="#cdd6f4").pack(side="left", padx=5)

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

tk.Label(left, text="配置要求", bg="#1e1e2e", fg="#cdd6f4",
         font=("", 10, "bold")).pack(anchor="w", padx=10, pady=(10, 0))
req_text = tk.Text(left, height=4, bg="#11111b", fg="#cdd6f4", font=("", 10),
                    insertbackground="#cdd6f4")
req_text.pack(fill="x", padx=10)

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

f6 = tk.Frame(left, bg="#1e1e2e")
f6.pack(fill="x", padx=10, pady=10)
btn_gen = tk.Button(f6, text="生成配置", command=gen_config,
                     bg="#89b4fa", fg="#1e1e2e", font=("", 10, "bold"), width=12)
btn_gen.pack(side="left")
btn_deploy = tk.Button(f6, text="部署", command=deploy_all, state="disabled",
                        bg="#a6e3a1", fg="#1e1e2e", font=("", 10, "bold"), width=8)
btn_deploy.pack(side="left", padx=5)

tk.Label(left, text="配置预览", bg="#1e1e2e", fg="#cdd6f4",
         font=("", 10, "bold")).pack(anchor="w", padx=10, pady=(5, 0))
preview_text = tk.Text(left, bg="#11111b", fg="#a6e3a1",
                        font=("Consolas", 9), state="normal")
preview_text.pack(fill="both", expand=True, padx=10, pady=(0, 10))

# ── 右侧面板: 日志 ──

tk.Label(right, text="执行日志", bg="#181825", fg="#cdd6f4",
         font=("", 10, "bold")).pack(anchor="w", padx=10, pady=(10, 0))
log_text = tk.Text(right, bg="#11111b", fg="#cdd6f4", font=("Consolas", 9),
                    state="normal")
log_text.pack(fill="both", expand=True, padx=10, pady=(0, 10))


def _startup():
    data = cfg_load()
    if data.get("key"):
        key_var.set(data["key"])
    if data.get("url"):
        url_var.set(data["url"])
    if data.get("model"):
        model_var.set(data["model"])
    log("TopoHelper 启动就绪")


def main():
    _startup()
    root.mainloop()


if __name__ == "__main__":
    main()
