import socket
from typing import List

from tej_protoc.client import TPClient
from tej_protoc import callbacks, protocol
from tej_protoc.file import File
from tej_protoc.ping import Ping


class ClientCallback(callbacks.ResponseCallback):
    def connected(self, client: socket.socket):
        self.socket_timeout = None

        print('Connected to server...')
        # ping = Ping(self.client, 3)
        # ping.start()
        protocol.send(self.client, protocol.BytesBuilder().add_file('s', b'1' * 1000 * 1000).bytes())

    def ping_received(self, files: List[File], message_data: bytes):
        print('Ping received from server')

    def received(self, files, message):
        print('---- Received in client ----')
        print('Custom status: ', self.custom_status)

        for file in files:
            print(file.name)

        print('Message: ', message.decode())
        print('---------------------------------')


def test_client():
    try:
        client = TPClient('localhost', 8000, ClientCallback, timeout=3)
        client.listen()
    except Exception as e:
        raise e


test_client()
