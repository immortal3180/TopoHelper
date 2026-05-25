import re, socket, tkinter as tk
from threading import Thread

ip = "127.0.0.1"
sock = None
timer = None


def scan():
    global ip
    ip = inp.get().strip() or "127.0.0.1"
    btn.config(state="disabled")
    txt.delete("1.0", "end")
    txt.insert("end", f"扫描 {ip}:2000-2099 ...\n\n")

    def _s():
        n = 0
        for p in range(2000, 2100):
            try:
                s = socket.create_connection((ip, p), timeout=0.2)
            except:
                continue
            try:
                s.settimeout(1); s.sendall(b"\r\n"); s.recv(4096)
                d = s.recv(4096); s.close()
                m = None
                for enc in ("gb2312", "gbk", "utf-8"):
                    try:
                        m = re.search(r"[<\[](\S+)[>\]]", d.decode(enc))
                        if m: break
                    except:
                        continue
                txt.insert("end", f"  {p:5d}  {m.group(1) if m else '?'}\n")
                n += 1
            except:
                try: s.close()
                except: pass
        txt.insert("end", f"\n{n} 台  — 双击设备行打开终端\n")
        btn.config(state="normal")
    Thread(target=_s, daemon=True).start()


def d_encode(data: bytes) -> str:
    """自适应解码 VR 响应"""
    for enc in ("gb2312", "gbk", "utf-8"):
        try:
            return data.decode(enc)
        except:
            pass
    return data.decode("latin-1")  # 无损兜底，至少能看


def shell(port: int):
    global sock, timer
    disconnect()

    try:
        sock = socket.create_connection((ip, port), timeout=3)
        sock.settimeout(0.15)
    except:
        return

    win = tk.Toplevel(root)
    win.title(f"{ip}:{port}")
    win.geometry("680x500")

    out = tk.Text(win, font=("Consolas", 12), bg="#11111b", fg="#cdd6f4",
                  insertbackground="#cdd6f4", state="disabled")
    out.pack(fill="both", expand=True)

    def write(text: str, tag=None):
        out.config(state="normal")
        if tag:
            out.insert("end", text, tag)
        else:
            out.insert("end", text)
        out.see("end")
        out.config(state="disabled")

    def recv():
        global sock, timer
        if not sock:
            return
        try:
            data = sock.recv(4096)
            if not data:
                disconnect(); win.destroy(); return
            text = d_encode(data)
            if "---- More ----" in text:
                text = text.replace("---- More ----", "")
                try: sock.sendall(b" \r\n")
                except: pass
            write(text)
        except socket.timeout:
            pass
        except:
            disconnect(); win.destroy(); return
        timer = root.after(150, recv)

    def send(event=None):
        global sock
        if not sock:
            return
        cmd = inp_cmd.get()
        inp_cmd.delete(0, "end")
        try:
            sock.sendall(f"{cmd}\r\n".encode())
        except:
            disconnect(); win.destroy(); return
        # 吃掉 echo —— 设备会原样返回刚发出的命令
        old = sock.gettimeout()
        sock.settimeout(0.5)
        try:
            sock.recv(4096)  # 丢弃 echo
        except:
            pass
        sock.settimeout(old)

    def on_close():
        disconnect(); win.destroy()

    win.protocol("WM_DELETE_WINDOW", on_close)

    inp_cmd = tk.Entry(win, font=("Consolas", 12), bg="#313244", fg="#cdd6f4",
                        insertbackground="#cdd6f4")
    inp_cmd.pack(side="bottom", fill="x")
    inp_cmd.bind("<Return>", send)
    inp_cmd.focus()

    recv()


def disconnect():
    global sock, timer
    if timer:
        root.after_cancel(timer); timer = None
    if sock:
        try: sock.close()
        except: pass
        sock = None


def click(e):
    line = txt.get(f"{txt.index(f'@{e.x},{e.y}').split('.')[0]}.0", "end")
    m = re.search(r"\b(\d{4})\b", line)
    if m:
        shell(int(m.group(1)))


root = tk.Tk()
root.title("设备扫描器")
root.geometry("440x400")
tk.Label(root, text="IP 地址").pack()
inp = tk.Entry(root, width=30); inp.pack(); inp.insert(0, ip)
btn = tk.Button(root, text="扫描", command=scan, width=10); btn.pack()
txt = tk.Text(root, font=("Consolas", 11), bg="#1e1e1e", fg="#a6e3a1")
txt.pack(fill="both", expand=True, padx=5, pady=5)
txt.bind("<Double-Button-1>", click)
root.mainloop()
