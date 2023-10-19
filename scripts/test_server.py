import socket
import threading
from time import sleep
from typing import List

from tej_protoc import protocol
from tej_protoc.callbacks import ResponseCallback
from tej_protoc.file import File
from tej_protoc.protocol import StatusCode

from tej_protoc.server import TPServer


def ping(self):
    while True:
        try:
            self.send(protocol.BytesBuilder(StatusCode.PING).bytes())
        except Exception as e:
            print(e)
            break

        sleep(3)


class MessageCallback(ResponseCallback):
    def connected(self, client: socket.socket):
        print('Client connected')
        builder = protocol.BytesBuilder(20)
        builder.add_file('a.txt', b'10' * 1000)
        builder.add_file('b.txt', b'10' * 1000)
        builder.set_message('Hey'.encode()).bytes()
        protocol.send(client, builder.bytes())

        # PING
        threading.Thread(target=ping, args=(self,)).start()

    def received(self, files: List[File], message_data: bytes):
        if message_data:
            print('Message:', message_data.decode())

        if files:
            print('Received file')


print('Server is running...')
server = TPServer('localhost', 8000, MessageCallback, timeout=5)
server.add_sock_opt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
server.add_sock_opt(socket.IPPROTO_TCP, socket.TCP_KEEPIDLE, 60)
server.add_sock_opt(socket.IPPROTO_TCP, socket.TCP_KEEPCNT, 1)
server.add_sock_opt(socket.IPPROTO_TCP, socket.TCP_KEEPINTVL, 15)
server.listen(run_background=True)
