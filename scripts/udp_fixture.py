"""Bounded loopback-only fixture peer. Test driver owns this process and stdin."""
import json
import select
import socket
import sys
import time


def emit(value):
    print(json.dumps(value), flush=True)


def main():
    config = json.loads(sys.stdin.readline())
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(('127.0.0.1', 0))
    sock.setblocking(False)
    emit({'ready': True, 'port': sock.getsockname()[1]})
    messages = [bytes.fromhex(x) for x in config.get('messages', [])]
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        readable, _, _ = select.select([sys.stdin, sock], [], [], 0.02)
        if sys.stdin in readable:
            line = sys.stdin.readline()
            if not line:
                break
            command = json.loads(line)
            if command['op'] == 'stop':
                break
            if command['op'] == 'send':
                for frame in command['packets']:
                    sock.sendto(bytes.fromhex(frame), ('127.0.0.1', command['port']))
                emit({'sent': len(command['packets'])})
            elif command['op'] == 'flood':
                end = time.monotonic() + min(command['seconds'], 1)
                count = 0
                data = bytes.fromhex(command['packet'])
                while time.monotonic() < end and count < 100000:
                    sock.sendto(data, ('127.0.0.1', command['port']))
                    count += 1
                    # Sustained traffic without consuming an unbounded CPU core.
                    if count % 16 == 0:
                        time.sleep(0.0001)
                emit({'sent': count})
        if sock in readable:
            data, peer = sock.recvfrom(65507)
            emit({'request': data.hex(), 'peer_port': peer[1]})
            if config.get('drop') or len(data) != 20:
                continue
            first = int.from_bytes(data[10:18], 'big')
            count = int.from_bytes(data[18:20], 'big')
            if not 1 <= count <= 128 or not 1 <= first <= len(messages):
                continue
            count = min(count, config.get('partial', 128), len(messages) - first + 1)
            chosen = messages[first - 1:first - 1 + count]
            reply = data[:18] + count.to_bytes(2, 'big') + b''.join(len(x).to_bytes(2, 'big') + x for x in chosen)
            sock.sendto(reply, peer)
    sock.close()


if __name__ == '__main__':
    main()
