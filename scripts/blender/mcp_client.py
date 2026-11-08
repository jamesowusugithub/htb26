"""Send an explicit command to the already-running Blender MCP add-on."""
import json
import socket


def command(kind, params=None, timeout=120):
    with socket.create_connection(('127.0.0.1', 9876), timeout=10) as connection:
        connection.settimeout(timeout)
        connection.sendall(json.dumps({'type': kind, 'params': params or {}}).encode('utf-8'))
        payload = b''
        while True:
            block = connection.recv(65536)
            if not block:
                raise RuntimeError('Blender closed the socket before its response')
            payload += block
            try:
                result = json.loads(payload.decode('utf-8'))
                break
            except (json.JSONDecodeError, UnicodeDecodeError):
                continue
    if result.get('status') != 'success':
        raise RuntimeError(json.dumps(result))
    return result


if __name__ == '__main__':
    print(json.dumps(command('get_scene_info'), indent=2))
