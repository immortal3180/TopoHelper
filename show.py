"""
浏览器查看 .topo —— 利用 XML 原生渲染，自动折叠展开

用法:
  python show.py file.topo
"""

import os
import shutil
import sys
import tempfile
import webbrowser


def main():
    if len(sys.argv) < 2:
        print("用法: python show.py file.topo")
        return

    path = sys.argv[1]
    if not os.path.isfile(path):
        print(f"文件不存在: {path}")
        return

    tmp = tempfile.NamedTemporaryFile(suffix=".xml", delete=False)
    tmp.close()
    shutil.copy(path, tmp.name)
    webbrowser.open(tmp.name)
    print(f"○ {os.path.basename(path)}")


if __name__ == "__main__":
    main()
