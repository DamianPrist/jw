# 局域网即时通信系统 — 项目交接文档

## 项目概述

基于 Python Socket API 的 C/S 架构局域网即时通信系统（机网实践课程项目）。

**技术栈：** Python 3 标准库（socket, threading, json, tkinter）

## 文件结构

```
lanchat/
├── protocol.py    # 共享协议层：消息类型常量、pack/unpack、昵称校验
├── server.py      # 服务端：多线程（每连接一个线程）
└── client.py      # 客户端：tkinter 多窗口 GUI（登录/公聊/私聊）+ 消息路由

docs/superpowers/
├── specs/2026-05-24-lanchat-design.md   # 设计文档
└── plans/2026-05-24-lanchat.md          # 实现计划
```

## 架构

```
客户端 A ←→ TCP/JSON ←→ 服务端（多线程） ←→ TCP/JSON ←→ 客户端 B
```

- **服务端**：主线程阻塞 accept，每个客户端一个 daemon 线程处理 I/O。`threading.Lock` 保护共享状态（`{socket: nickname}` 和 `{nickname: socket}` 两个映射）
- **客户端**：4 个类——`LoginWindow`（登录）、`PublicChatWindow`（公聊主窗口 + 在线用户列表）、`PrivateChatWindow`（私聊窗口，每对象一个独立 Toplevel）、`_MessageRouter`（接收线程 → Queue → 主线程轮询分发）。GUI 线程（tkinter）+ 接收线程（socket.recv），通过 `queue.Queue` 安全传递数据
- **协议**：JSON 消息以 `\n` 分隔，pack/unpack 函数处理粘包和半包（使用 `bytearray` 缓冲区）

## 功能

| 功能 | 说明 |
|------|------|
| 登录/登出 | 昵称登录，校验唯一性和特殊字符，广播上下线通知 |
| 公聊 | 默认消息广播给所有在线用户 |
| 私聊 | 双击在线用户打开专属私聊窗口，支持多窗口并存；收到私聊消息自动弹出窗口 |
| 在线用户列表 | 登录时全量 + 后续增量推送 |

## 协议

客户端→服务端：`login`, `broadcast`, `private`, `logout`

服务端→客户端：`login_ok`, `login_fail`, `user_online`, `user_offline`, `broadcast`, `private`, `error`

## 客户端 GUI 结构

| 类 | 对应窗口 | 职责 |
|------|------|------|
| `LoginWindow` | 登录窗口 | IP/端口/昵称输入，TCP 连接，登录验证 |
| `PublicChatWindow` | 公聊主窗口 | 在线用户列表（左侧）+ 公聊消息区（右侧）+ 输入框（底部），仅发送 broadcast |
| `PrivateChatWindow` | 私聊窗口 | 一对一私聊，每对象一个独立 `Toplevel`，窗口标题 `私聊 — 对方昵称` |
| `_MessageRouter` | 无窗口 | 接收线程 → `queue.Queue` → 主线程 `after(100ms)` 轮询分发，私聊消息自动路由到对应窗口 |

**私聊发起方式：** ① 双击在线用户列表中的用户；② 收到对方私聊消息时自动弹出窗口。

## 运行方式

```bash
# 服务端（指定端口）
python lanchat/server.py 7000

# 客户端（GUI 窗口，可开多个）
python lanchat/client.py
# 端口改为 7000，填昵称，点连接
```

## 已修复的关键 Bug

1. **Windows 僵尸进程问题**：Windows 上多个 python 进程可同时绑定同一端口（SO_REUSEADDR 行为不同），导致新连接被路由到僵尸进程。解决：启动前 `taskkill /F /IM python.exe` 清理旧进程。

2. **select 兼容性问题**：原版服务端使用 `select.select()` + 非阻塞 socket，在 Windows 上不工作（select 永远不返回）。已改为阻塞 socket + 多线程方案。

3. **[连接] 不打印意味着服务端没收到连接**：如果服务端终端只打印了"服务端启动"但客户端连接后不打印"[连接]"，说明僵尸进程在抢端口。

## 测试结果

全部 7 项集成测试通过：登录、上下线通知、公聊、私聊（多窗口）、重复昵称拒绝、下线通知。

## 设计文档

详见 [docs/superpowers/specs/2026-05-24-lanchat-design.md](docs/superpowers/specs/2026-05-24-lanchat-design.md)
