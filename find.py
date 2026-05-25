"""
发现磁盘上的 .topo 文件

用法:
  python find_topo.py                 扫描当前目录及子目录
  python find_topo.py D:\path         扫描指定目录及子目录
"""

import os
import sys
import time

# 不用进去的目录
SKIP = {
    "windows", "system32", "program files", "program files (x86)",
    "$recycle.bin", "system volume information", "node_modules",
    ".git", "__pycache__", "appdata",
}


def scan_dir(root: str) -> list[str]:
    """用 os.scandir 递归扫描，返回所有 .topo 文件的绝对路径"""
    result = []

    try:
        with os.scandir(root) as entries:
            for entry in entries:
                if entry.is_dir():
                    if entry.name.lower() in SKIP:
                        continue
                    result.extend(scan_dir(entry.path))
                elif entry.is_file() and entry.name.endswith(".topo"):
                    result.append(entry.path)
    except PermissionError:
        pass
    except OSError:
        pass

    return result


def show_result(files: list[str], elapsed: float):
    """打印扫描结果"""
    if not files:
        print("未发现 .topo 文件")
    else:
        print(f"\n发现 {len(files)} 个 .topo 文件:\n")
        for i, path in enumerate(files, 1):
            print(f"  [{i}] {path}")
    print(f"\n扫描耗时: {elapsed:.2f} 秒")


def main():
    start = time.time()
    root = os.getcwd() if len(sys.argv) <= 1 else sys.argv[1]
    print(f"正在扫描: {os.path.abspath(root)}\n")
    files = scan_dir(root)
    show_result(files, time.time() - start)


if __name__ == "__main__":
    main()
