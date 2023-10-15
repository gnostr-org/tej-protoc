import socket
from typing import List

from tej_protoc import protocol
from tej_protoc.callbacks import ResponseCallback
from tej_protoc.file import File

from tej_protoc.server import TPServer


class MessageCallback(ResponseCallback):
    def connected(self, client: socket.socket):
        print('Client connected')
        builder = protocol.BytesBuilder(20)
        builder.add_file('a.txt', b'10' * 1000)
        builder.add_file('b.txt', b'10' * 1000)
        builder.set_message('Hey'.encode()).bytes()
        self.send(builder.bytes())

    def received(self, files: List[File], message_data: bytes):
        print('Message:', message_data.decode())


print('Server is running...')
server = TPServer('localhost', 8000, MessageCallback, timeout=5)
server.listen(run_background=True)
