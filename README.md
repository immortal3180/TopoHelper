# TopoHelper

自然语言 → 网络配置，一键部署到 eNSP / H3C Cloud Lab / Packet Tracer。

## 快速开始

```bash
# 安装
pip install -e .

# 启动 GUI
topo-helper
```

或使用打包好的 `.exe`（无需安装任何依赖）：

```bash
release/topo-helper.exe
```

## 功能

1. 加载 `.topo` 文件，自动扫描在线设备
2. 输入配置要求，LLM 生成每台设备的 CLI 命令
3. 人工确认后一键批量部署到路由器/交换机
4. 自动连通性验证 + 失败重试
5. 全流程日志记录

## 项目结构

```
topo_helper.py   —— 主程序（GUI + 全流程逻辑）
find.py          —— 磁盘扫描器，发现 .topo 文件
show.py          —— 浏览器查看 .topo（XML 原生渲染）
deploy.py        —— 独立 Telnet 终端工具
pyproject.toml   —— 打包配置
```

## 依赖

- Python ≥ 3.10
- openai ≥ 1.0
- tkinter（Python 自带）

## 开发

```bash
git clone ...
pip install -e .
python topo_helper.py
```
