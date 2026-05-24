"""局域网即时通信系统 — 服务端（多线程版）"""

import socket
import threading
import sys
from protocol import (
    pack_message, unpack_from_buffer, is_valid_nickname,
    TYPE_LOGIN, TYPE_LOGIN_OK, TYPE_LOGIN_FAIL, TYPE_LOGOUT,
    TYPE_BROADCAST, TYPE_PRIVATE, TYPE_USER_ONLINE, TYPE_USER_OFFLINE,
    TYPE_ERROR,
)

# 共享状态 + 锁
clients = {}       # {socket: nickname}
nick_to_sock = {}  # {nickname: socket}
lock = threading.Lock()


def broadcast(clients, msg, exclude_sock=None):
    """向所有已登录客户端广播消息，可排除指定 socket。"""
    data = pack_message(msg)
    for sock in clients:
        if sock is not exclude_sock:
            try:
                sock.sendall(data)
            except OSError:
                pass


def handle_login(sock, msg):
    """处理登录请求。"""
    nickname = msg.get("nickname", "").strip()
    valid, reason = is_valid_nickname(nickname)
    if not valid:
        try:
            sock.sendall(pack_message({"type": TYPE_LOGIN_FAIL, "reason": reason}))
        except OSError:
            pass
        return False

    with lock:
        if nickname in nick_to_sock:
            try:
                sock.sendall(pack_message({"type": TYPE_LOGIN_FAIL, "reason": "昵称已存在"}))
            except OSError:
                pass
            return False

        clients[sock] = nickname
        nick_to_sock[nickname] = sock
        online_users = list(nick_to_sock.keys())

    try:
        sock.sendall(pack_message({"type": TYPE_LOGIN_OK, "users": online_users}))
    except OSError:
        return False

    with lock:
        broadcast(clients, {"type": TYPE_USER_ONLINE, "nickname": nickname}, exclude_sock=sock)

    print(f"[+] {nickname} 上线，当前在线: {online_users}", flush=True)
    return True


def handle_broadcast(sock, msg):
    """处理公聊消息转发。"""
    with lock:
        sender = clients.get(sock)
        if sender:
            forward = {"type": TYPE_BROADCAST, "from": sender, "content": msg.get("content", "")}
            broadcast(clients, forward, exclude_sock=sock)
            print(f"[公聊] {sender}: {msg.get('content', '')}", flush=True)


def handle_private(sock, msg):
    """处理私聊消息转发。"""
    with lock:
        sender = clients.get(sock)
        if not sender:
            return
        target = msg.get("to", "")
        content = msg.get("content", "")
        target_sock = nick_to_sock.get(target)

    if target_sock is None:
        try:
            sock.sendall(pack_message({"type": TYPE_ERROR, "reason": f"用户 {target} 不在线"}))
        except OSError:
            pass
        return

    forward = {"type": TYPE_PRIVATE, "from": sender, "content": content}
    try:
        target_sock.sendall(pack_message(forward))
    except OSError:
        pass
    print(f"[私聊] {sender} -> {target}: {content}", flush=True)


def disconnect_sock(sock):
    """断开连接并清理资源。"""
    with lock:
        nickname = clients.pop(sock, None)
        if nickname:
            del nick_to_sock[nickname]
            broadcast(clients, {"type": TYPE_USER_OFFLINE, "nickname": nickname})
            print(f"[-] {nickname} 下线", flush=True)
    try:
        sock.close()
    except OSError:
        pass


def handle_client(sock, addr):
    """每个客户端一个线程，循环接收并处理消息。"""
    print(f"[连接] {addr}", flush=True)
    buf = bytearray()
    authenticated = False

    try:
        while True:
            try:
                data = sock.recv(4096)
            except (ConnectionResetError, ConnectionAbortedError, OSError):
                data = b""

            if not data:
                break

            buf.extend(data)
            messages = unpack_from_buffer(buf)

            for msg in messages:
                msg_type = msg.get("type", "")

                if not authenticated:
                    if msg_type == TYPE_LOGIN:
                        authenticated = handle_login(sock, msg)
                    continue

                if msg_type == TYPE_LOGIN:
                    continue
                elif msg_type == TYPE_LOGOUT:
                    return
                elif msg_type == TYPE_BROADCAST:
                    handle_broadcast(sock, msg)
                elif msg_type == TYPE_PRIVATE:
                    handle_private(sock, msg)
    finally:
        disconnect_sock(sock)


def main(host="0.0.0.0", port=9999):
    serversock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    serversock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    serversock.bind((host, port))
    serversock.listen(10)
    print(f"服务端启动: {host}:{port}", flush=True)

    try:
        while True:
            try:
                conn, addr = serversock.accept()
            except KeyboardInterrupt:
                break

            t = threading.Thread(target=handle_client, args=(conn, addr), daemon=True)
            t.start()
    except KeyboardInterrupt:
        pass

    print("\n服务端关闭", flush=True)

    with lock:
        for sock in list(clients.keys()):
            try:
                sock.close()
            except OSError:
                pass
    serversock.close()


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 9999
    main(port=port)
