# Serial/SSH Terminal Tool 使用说明 (中文 / English)

## 中文说明

### 1. 功能简介
这是一个基于 Tkinter 的串口/SSH 终端工具，支持以下能力：
- Serial / SSH 连接二选一
- 串口参数配置：端口、波特率、数据位、停止位、奇偶校验、流控（RTS/CTS、XON/XOFF、DSR/DTR）
- SSH 参数配置：主机、端口、用户名、密码或私钥
- 终端交互输入输出（支持发送、接收、HEX 发送）
- 日志显示与保存（手动保存、自动保存）
- 关键字高亮（每个关键字可独立颜色）
- 关键字触发“停止记录日志”
- Resume log 后自动生成新的日志文件
- 字体大小调节
- 配置文件自动保存/加载（serial_tool_config.json）

### 2. 环境要求
- Python 3.8+
- GUI 环境（Tkinter）

依赖库：
- pyserial（串口功能）
- paramiko（SSH 功能）

安装示例：
```bash
pip3 install --user pyserial paramiko
```

如果使用 sudo 运行，可使用：
```bash
sudo python3 Console.py
```
程序已内置对 sudo 场景下用户 site-packages 的兼容处理。

### 3. 启动方式
在当前目录执行：
```bash
python3 Console.py
```

### 4. 基本使用流程
1. 在 Configuration 区域选择模式：Serial 或 SSH。
2. 填写对应参数。
3. 点击 Connect 建立连接。
4. 在 Terminal 输入框中输入命令并发送。
5. 需要记录日志时：
   - 勾选 Auto save（自动追加保存）
   - 点击 Choose log file 选择基础文件名（程序会自动加时间后缀）
   - 或点击 Save log now 立即保存当前缓存

### 5. 日志文件命名规则
选择日志文件后，实际写入文件名会自动加上时间戳后缀：
- 格式：`基础名_YYYYMMDD_HHMMSS.扩展名`
- 示例：`test_20260409_171756.log`

当关键字触发 Stop log 后，点击 Resume log：
- 会恢复日志记录状态
- 会自动切换到一个新的时间戳日志文件继续记录

### 6. 关键字高亮与停止日志
在 Keyword Highlight 区域：
1. 输入关键字
2. 选择颜色
3. 可选勾选 Stop log on match
4. 点击 Add

说明：
- 关键字命中时会高亮显示
- 如果该关键字启用了 Stop log on match，则命中后会停止写入日志文件与内存缓冲
- 触发停止的那一行会被保存；后续行不再记录，直到点击 Resume log

### 7. 配置文件
程序会在同目录读写配置文件：
- `serial_tool_config.json`

保存内容包括：
- 连接模式与参数
- 自动保存开关
- 日志基础路径
- 终端字体大小
- 关键字列表（含颜色与 stop_log 选项）

### 8. 常见问题
- Linux 串口权限不足：请确认当前用户在 `dialout` 或 `uucp` 组。
- 缺少 tkinter：安装系统 Tk 组件（不同发行版命令不同）。
- 缺少 pyserial/paramiko：按上方 pip 命令安装。

---

## English Guide

### 1. Overview
This is a Tkinter-based Serial/SSH terminal tool with:
- Serial or SSH mode (mutually exclusive)
- Serial settings: port, baud rate, data bits, stop bits, parity, flow control
- SSH settings: host, port, username, password or private key
- Interactive terminal I/O (send/receive, HEX send)
- Log display and save (manual save + auto save)
- Keyword highlight with per-keyword color
- Keyword-triggered stop logging
- New log file generation when Resume log is clicked
- Adjustable terminal font size
- Config auto load/save (`serial_tool_config.json`)

### 2. Requirements
- Python 3.8+
- GUI environment with Tkinter

Dependencies:
- pyserial (for Serial)
- paramiko (for SSH)

Install:
```bash
pip3 install --user pyserial paramiko
```

If you run with sudo:
```bash
sudo python3 Console.py
```
The app includes compatibility handling for user site-packages under sudo.

### 3. Run
```bash
python3 Console.py
```

### 4. Quick Start
1. Select mode in Configuration: Serial or SSH.
2. Fill in mode-specific settings.
3. Click Connect.
4. Type in the Terminal input and send.
5. For logging:
   - Enable Auto save
   - Click Choose log file to pick a base filename (timestamp suffix will be added automatically)
   - Or click Save log now to save current buffer immediately

### 5. Log Filename Rule
When a log file is selected, the actual output filename is:
- `base_YYYYMMDD_HHMMSS.ext`
- Example: `test_20260409_171756.log`

After Stop log is triggered by a keyword, clicking Resume log:
- Re-enables logging
- Switches to a newly timestamped log file

### 6. Keyword Highlight + Stop Logging
In Keyword Highlight panel:
1. Enter keyword
2. Pick color
3. Optionally check Stop log on match
4. Click Add

Behavior:
- Matched keywords are highlighted
- If Stop log on match is enabled for that keyword, logging to buffer/file stops after match
- The trigger line is still saved; subsequent lines are not logged until Resume log

### 7. Config File
The app reads/writes:
- `serial_tool_config.json`

Stored items include:
- Connection mode and settings
- Auto-save option
- Log base path
- Terminal font size
- Keywords (with color and stop_log flag)

### 8. Troubleshooting
- Linux serial permission: ensure your user is in `dialout` or `uucp`.
- Missing tkinter: install system Tk package for your distro.
- Missing pyserial/paramiko: install with pip command above.
