# 局域网即时通信系统 — 设计文档

## 概述

基于 Python Socket API 的 C/S 架构局域网即时通信系统。服务端使用 `select` I/O 多路复用处理多客户端，客户端使用 tkinter + 双线程模型。通信协议采用 JSON over TCP。

## 功能清单

1. **用户登录/登出**：输入昵称登录，服务端校验唯一性；主动退出或断线时广播下线通知
2. **群发消息（公聊）**：默认消息广播给所有在线用户
3. **私聊消息**：通过 `@昵称 消息` 格式发送点对点消息
4. **在线用户列表实时更新**：登录时获取全量列表，后续服务端推送增量变化

## 架构

```
┌──────────────────┐          ┌──────────────────┐          ┌──────────────────┐
│   客户端 A        │          │   服务端           │          │   客户端 B        │
│  ┌────────────┐  │  TCP     │  ┌────────────┐  │  TCP     │  ┌────────────┐  │
│  │ GUI 线程    │  │◄───────►│  │ 主线程      │  │◄───────►│  │ GUI 线程    │  │
│  │ (tkinter)  │  │  JSON   │  │ (select     │  │  JSON   │  │ (tkinter)  │  │
│  ├────────────┤  │         │  │  多路复用)  │  │         │  ├────────────┤  │
│  │ 接收线程    │  │         │  │             │  │         │  │ 接收线程    │  │
│  │ (socket)   │  │         │  └────────────┘  │         │  │ (socket)   │  │
│  └────────────┘  │          │                  │          │  └────────────┘  │
└──────────────────┘          └──────────────────┘          └──────────────────┘
```

- **服务端**：单进程 + `select.select()` 多路复用，无多线程
- **客户端**：GUI 线程（tkinter 主循环）+ 接收线程（socket.recv 阻塞），通过 `queue.Queue` 安全传递数据
- **通信**：TCP，JSON 消息以 `\n` 分隔

## 通信协议

客户端→服务端：

| 类型   | JSON                                     |
|--------|------------------------------------------|
| 登录   | `{"type":"login","nickname":"Alice"}`    |
| 公聊   | `{"type":"broadcast","content":"hello"}` |
| 私聊   | `{"type":"private","to":"Bob","content":"hi"}` |
| 登出   | `{"type":"logout"}`                      |

服务端→客户端：

| 类型       | JSON                                                       |
|------------|------------------------------------------------------------|
| 登录成功   | `{"type":"login_ok","users":["Alice","Bob"]}`              |
| 登录失败   | `{"type":"login_fail","reason":"昵称已存在"}`               |
| 上线通知   | `{"type":"user_online","nickname":"Alice"}`                |
| 下线通知   | `{"type":"user_offline","nickname":"Alice"}`               |
| 公聊消息   | `{"type":"broadcast","from":"Alice","content":"hello"}`    |
| 私聊消息   | `{"type":"private","from":"Alice","content":"hi"}`         |
| 错误提示   | `{"type":"error","reason":"用户不在线"}`                     |

## 文件结构

```
lanchat/
├── server.py      # 服务端
├── client.py      # 客户端
└── protocol.py    # 共享常量和消息构造/解析辅助函数
```

## 模块设计

### protocol.py

共享常量（消息类型字符串）和 `pack_message()` / `unpack_message()` 辅助函数。pack 负责 JSON 序列化 + 追加 `\n`，unpack 负责按 `\n` 分割和 JSON 解析。

**消息边界处理**：服务端和客户端各自维护一个 `bytearray` 接收缓冲区。每次 `recv` 后将数据追加到缓冲区，循环查找 `b'\n'` 切分出完整 JSON 字符串解析，剩余不完整数据保留在缓冲区等待后续数据到达。这样同时解决了粘包和半包问题。

### server.py

- **启动**：绑定 `0.0.0.0:<port>`，`listen(10)`，进入 `select` 事件循环
- **数据结构**：`{socket: nickname}` 映射，`{nickname: socket}` 反向映射
- **登录处理**：校验昵称非空、不重复、不含空格/`@`/换行符等特殊字符 → 添加映射 → 发送 login_ok → 广播 user_online。未登录的 socket 发来的非 `login` 消息直接忽略；已登录的 socket 重复发送 `login` 也忽略
- **公聊处理**：遍历所有在线 socket 转发 broadcast 消息（跳过发送者）
- **私聊处理**：通过昵称查找目标 socket，仅发送给目标；目标不存在则返回错误
- **断线处理**：`select` 只监听可读事件，对可读 socket 执行 `recv`，返回空或抛出异常（`ConnectionResetError` 等）即视为断开 → 移除映射 → 广播 user_offline → 关闭 socket
- **消息边界**：使用缓冲区累积接收数据，按 `\n` 分割出完整 JSON

### client.py

- **GUI 线程**：
  - 登录窗口：IP 地址、端口、昵称输入框 + 连接按钮
  - 聊天窗口：消息展示区（只读 Text）+ 在线用户列表（Listbox）+ 消息输入框 + 发送按钮
  - 定时器 `after(100, poll_queue)` 从队列取消息更新 UI
- **接收线程**：
  - 循环 `recv` 数据 → 按 `\n` 分割 → JSON 解析 → `queue.put(msg)`
  - 异常或 `recv` 返回空 → 连接断开 → `queue.put({"type":"disconnected"})`
- **发送**：GUI 线程直接 `send`（写入短 JSON 不会阻塞）
- **私聊处理**：检测输入以 `@` 开头 → 解析目标昵称 → 发送 private 消息
- **退出处理**：关闭窗口时发送 logout → 关闭 socket → 等待接收线程结束

## 并发模型

```
客户端:
  socket.connect()
  recv_thread = Thread(target=receive_loop)
  recv_thread.daemon = True   # 主线程退出时自动终止
  recv_thread.start()
  root.mainloop()             # GUI 主循环（阻塞）
  # 窗口关闭后整理
  socket.send(pack({"type":"logout"}))
  socket.close()
```

线程间仅通过 `queue.Queue` 传递数据，GUI 线程不直接操作 socket 的 recv，接收线程不操作 tkinter 组件。

## 错误与边界

- 昵称为空或重复 → 服务端拒绝，客户端弹窗提示
- 服务端不可达 → 客户端连接超时提示
- 消息过大（> 64KB）→ 协议层限制，超过则截断或拒绝
- 连接断开 → 接收线程推送 `disconnected`，GUI 在输入区域显示"已断开"
- 私聊目标不存在 → 服务端返回错误消息 `{"type":"error","reason":"用户不在线"}`
