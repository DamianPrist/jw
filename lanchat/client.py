"""局域网即时通信系统 — 客户端"""

import socket
import threading
import queue
import tkinter as tk
from tkinter import messagebox, scrolledtext

from protocol import (
    pack_message, unpack_from_buffer, is_valid_nickname,
    TYPE_LOGIN, TYPE_LOGIN_OK, TYPE_LOGIN_FAIL, TYPE_LOGOUT,
    TYPE_BROADCAST, TYPE_PRIVATE, TYPE_USER_ONLINE, TYPE_USER_OFFLINE,
    TYPE_ERROR, TYPE_DISCONNECTED,
)


class LoginWindow:
    """登录窗口：IP、端口、昵称 + 连接按钮。"""

    def __init__(self):
        self.root = tk.Tk()
        self.root.title("登录 — LAN Chat")
        self.root.resizable(False, False)
        self.chat_window = None
        self.sock = None

        frame = tk.Frame(self.root, padx=20, pady=15)
        frame.pack()

        tk.Label(frame, text="服务器 IP:").grid(row=0, column=0, sticky="e", pady=4)
        self.ip_entry = tk.Entry(frame, width=22)
        self.ip_entry.insert(0, "127.0.0.1")
        self.ip_entry.grid(row=0, column=1, pady=4)

        tk.Label(frame, text="端口:").grid(row=1, column=0, sticky="e", pady=4)
        self.port_entry = tk.Entry(frame, width=22)
        self.port_entry.insert(0, "9999")
        self.port_entry.grid(row=1, column=1, pady=4)

        tk.Label(frame, text="昵称:").grid(row=2, column=0, sticky="e", pady=4)
        self.nick_entry = tk.Entry(frame, width=22)
        self.nick_entry.grid(row=2, column=1, pady=4)

        self.connect_btn = tk.Button(frame, text="连接", width=18, command=self.do_connect)
        self.connect_btn.grid(row=3, column=1, pady=10)

        self.nick_entry.bind("<Return>", lambda e: self.do_connect())

    def do_connect(self):
        nickname = self.nick_entry.get().strip()
        valid, reason = is_valid_nickname(nickname)
        if not valid:
            messagebox.showwarning("昵称无效", reason)
            return

        host = self.ip_entry.get().strip()
        try:
            port = int(self.port_entry.get().strip())
        except ValueError:
            messagebox.showwarning("端口错误", "端口必须是整数")
            return

        try:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.sock.settimeout(5)
            self.sock.connect((host, port))
            self.sock.settimeout(None)
        except (ConnectionRefusedError, socket.timeout, OSError) as e:
            messagebox.showerror("连接失败", f"无法连接到服务器\n{e}")
            if self.sock:
                self.sock.close()
                self.sock = None
            return

        self.sock.sendall(pack_message({"type": TYPE_LOGIN, "nickname": nickname}))

        self.sock.settimeout(3)
        try:
            data = self.sock.recv(4096)
        except (socket.timeout, OSError):
            messagebox.showerror("登录超时", "服务器无响应")
            self.sock.close()
            self.sock = None
            return
        self.sock.settimeout(None)

        buf = bytearray(data)
        msgs = unpack_from_buffer(buf)
        if not msgs:
            messagebox.showerror("登录失败", "服务器返回无效数据")
            self.sock.close()
            self.sock = None
            return

        resp = msgs[0]
        if resp.get("type") == TYPE_LOGIN_OK:
            online_users = resp.get("users", [])
            self.launch_chat(nickname, online_users)
        elif resp.get("type") == TYPE_LOGIN_FAIL:
            messagebox.showerror("登录失败", resp.get("reason", "未知原因"))
            self.sock.close()
            self.sock = None
        else:
            messagebox.showerror("登录失败", "未知响应")
            self.sock.close()
            self.sock = None

    def launch_chat(self, nickname, online_users):
        self.root.withdraw()
        self.chat_window = PublicChatWindow(
            self.sock, nickname, online_users,
            on_close=self.on_chat_closed
        )

    def on_chat_closed(self):
        self.root.destroy()

    def run(self):
        self.root.mainloop()


class _MessageRouter:
    """消息路由：接收线程 → 队列 → 定时轮询，分发给公聊窗口和所有私聊窗口。"""

    def __init__(self, sock, public_window):
        self.sock = sock
        self.public_window = public_window
        self.msg_queue = queue.Queue()
        self.running = True
        self.recv_thread = threading.Thread(target=self._receive_loop, daemon=True)

    def start(self):
        self.recv_thread.start()
        self._poll_queue()

    def _receive_loop(self):
        buf = bytearray()
        while self.running:
            try:
                data = self.sock.recv(4096)
            except (ConnectionResetError, ConnectionAbortedError, OSError):
                data = b""
            if not data:
                self.msg_queue.put({"type": TYPE_DISCONNECTED})
                break
            buf.extend(data)
            for msg in unpack_from_buffer(buf):
                self.msg_queue.put(msg)

    def _poll_queue(self):
        try:
            while True:
                msg = self.msg_queue.get_nowait()
                self._dispatch(msg)
        except queue.Empty:
            pass
        if self.running:
            self.public_window.root.after(100, self._poll_queue)

    def _dispatch(self, msg):
        msg_type = msg.get("type", "")

        if msg_type == TYPE_PRIVATE:
            sender = msg.get("from", "")
            self.public_window.route_private_msg(sender, msg["content"])

        elif msg_type == TYPE_BROADCAST:
            self.public_window.append_message(f"[公聊] {msg['from']}: {msg['content']}")

        elif msg_type == TYPE_USER_ONLINE:
            nickname = msg["nickname"]
            self.public_window.user_listbox.insert(tk.END, nickname)
            self.public_window.append_message(f"[系统] {nickname} 上线了")

        elif msg_type == TYPE_USER_OFFLINE:
            nickname = msg["nickname"]
            self.public_window.remove_user_from_list(nickname)
            self.public_window.append_message(f"[系统] {nickname} 下线了")

        elif msg_type == TYPE_ERROR:
            self.public_window.append_message(f"[系统] 错误: {msg.get('reason', '')}")

        elif msg_type == TYPE_DISCONNECTED:
            self.public_window.append_message("[系统] 与服务器断开连接")
            self.public_window.set_disconnected()

    def stop(self):
        self.running = False


class PublicChatWindow:
    """公聊窗口：消息显示 + 在线用户列表 + 输入框（仅发送公聊消息）。"""

    def __init__(self, sock, nickname, online_users, on_close):
        self.sock = sock
        self.nickname = nickname
        self.on_close = on_close
        self.private_windows = {}  # {target_nickname: PrivateChatWindow}

        self.root = tk.Toplevel()
        self.root.title(f"公聊 — {nickname}")
        self.root.protocol("WM_DELETE_WINDOW", self.do_close)

        # --- 左侧在线用户列表 ---
        left_frame = tk.LabelFrame(self.root, text="在线用户（双击发起私聊）", padx=4, pady=4)
        left_frame.pack(side=tk.LEFT, fill=tk.Y, padx=4, pady=4)

        self.user_listbox = tk.Listbox(left_frame, width=16, height=20)
        self.user_listbox.pack(fill=tk.BOTH, expand=True)
        for user in online_users:
            self.user_listbox.insert(tk.END, user)
        self.user_listbox.bind("<Double-Button-1>", self._on_user_double_click)

        # --- 右侧消息区 ---
        right_frame = tk.Frame(self.root)
        right_frame.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True, padx=4, pady=4)

        self.msg_display = scrolledtext.ScrolledText(
            right_frame, width=50, height=20, state=tk.DISABLED, wrap=tk.WORD
        )
        self.msg_display.pack(fill=tk.BOTH, expand=True)

        # --- 底部输入区 ---
        bottom_frame = tk.Frame(self.root)
        bottom_frame.pack(side=tk.BOTTOM, fill=tk.X, padx=4, pady=4)

        self.input_entry = tk.Entry(bottom_frame)
        self.input_entry.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.input_entry.bind("<Return>", lambda e: self.send_message())
        self.input_entry.focus_set()

        send_btn = tk.Button(bottom_frame, text="发送", width=8, command=self.send_message)
        send_btn.pack(side=tk.RIGHT, padx=(4, 0))

        # 启动消息路由（接收线程 + 轮询）
        self.router = _MessageRouter(sock, self)
        self.router.start()

    def append_message(self, text):
        self.msg_display.config(state=tk.NORMAL)
        self.msg_display.insert(tk.END, text + "\n")
        self.msg_display.see(tk.END)
        self.msg_display.config(state=tk.DISABLED)

    def send_message(self):
        content = self.input_entry.get()
        if not content:
            return
        self.input_entry.delete(0, tk.END)

        msg = {"type": TYPE_BROADCAST, "content": content}
        self.append_message(f"[公聊] 我: {content}")

        try:
            self.sock.sendall(pack_message(msg))
        except OSError:
            self.append_message("[系统] 发送失败，连接已断开")
            self.set_disconnected()

    def remove_user_from_list(self, nickname):
        for i in range(self.user_listbox.size()):
            if self.user_listbox.get(i) == nickname:
                self.user_listbox.delete(i)
                break

    def set_disconnected(self):
        self.router.running = False
        self.input_entry.config(state=tk.DISABLED)
        try:
            self.sock.close()
        except OSError:
            pass
        self.append_message("[系统] 已断开连接")

    def _on_user_double_click(self, event):
        selection = self.user_listbox.curselection()
        if not selection:
            return
        target = self.user_listbox.get(selection[0])
        if target == self.nickname:
            return
        self.open_private_chat(target)

    def open_private_chat(self, target):
        """打开或激活与指定用户的私聊窗口。"""
        if target in self.private_windows:
            pw = self.private_windows[target]
            if pw.root.winfo_exists():
                pw.root.deiconify()
                pw.root.lift()
                pw.input_entry.focus_set()
                return
            else:
                del self.private_windows[target]

        pw = PrivateChatWindow(
            self.sock, self.nickname, target,
            on_close=lambda t=target: self._on_private_closed(t)
        )
        self.private_windows[target] = pw

    def route_private_msg(self, sender, content):
        """将收到的私聊消息路由到对应的私聊窗口（如不存在则创建）。"""
        if sender not in self.private_windows or not self.private_windows[sender].root.winfo_exists():
            self.open_private_chat(sender)
        self.private_windows[sender].receive_message(sender, content)

    def _on_private_closed(self, target):
        if target in self.private_windows:
            del self.private_windows[target]

    def do_close(self):
        self.router.stop()
        # 关闭所有私聊窗口
        for pw in list(self.private_windows.values()):
            try:
                pw.root.destroy()
            except Exception:
                pass
        self.private_windows.clear()
        try:
            self.sock.sendall(pack_message({"type": TYPE_LOGOUT}))
        except OSError:
            pass
        try:
            self.sock.close()
        except OSError:
            pass
        self.root.destroy()
        self.on_close()


class PrivateChatWindow:
    """私聊窗口：与单个用户的一对一聊天。"""

    def __init__(self, sock, my_nickname, target, on_close):
        self.sock = sock
        self.my_nickname = my_nickname
        self.target = target
        self.on_close = on_close

        self.root = tk.Toplevel()
        self.root.title(f"私聊 — {target}")
        self.root.protocol("WM_DELETE_WINDOW", self._do_close)

        # 消息显示区
        self.msg_display = scrolledtext.ScrolledText(
            self.root, width=50, height=18, state=tk.DISABLED, wrap=tk.WORD
        )
        self.msg_display.pack(fill=tk.BOTH, expand=True, padx=4, pady=(4, 0))

        # 底部输入区
        bottom_frame = tk.Frame(self.root)
        bottom_frame.pack(side=tk.BOTTOM, fill=tk.X, padx=4, pady=4)

        self.input_entry = tk.Entry(bottom_frame)
        self.input_entry.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.input_entry.bind("<Return>", lambda e: self.send_message())
        self.input_entry.focus_set()

        send_btn = tk.Button(bottom_frame, text="发送", width=8, command=self.send_message)
        send_btn.pack(side=tk.RIGHT, padx=(4, 0))

    def append_message(self, text):
        self.msg_display.config(state=tk.NORMAL)
        self.msg_display.insert(tk.END, text + "\n")
        self.msg_display.see(tk.END)
        self.msg_display.config(state=tk.DISABLED)

    def receive_message(self, sender, content):
        """接收一条私聊消息并显示。"""
        self.append_message(f"{sender}: {content}")

    def send_message(self):
        content = self.input_entry.get()
        if not content:
            return
        self.input_entry.delete(0, tk.END)

        self.append_message(f"我: {content}")

        msg = {"type": TYPE_PRIVATE, "to": self.target, "content": content}
        try:
            self.sock.sendall(pack_message(msg))
        except OSError:
            self.append_message("[系统] 发送失败，连接已断开")

    def _do_close(self):
        self.root.destroy()
        self.on_close()


def main():
    login = LoginWindow()
    login.run()


if __name__ == "__main__":
    main()
