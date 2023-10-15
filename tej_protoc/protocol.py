from typing import Tuple, Optional, List, Any
import socket

from .callbacks import ResponseCallback
from .exceptions import InvalidStatusCode, InvalidProtocolVersion, ConnectionClosed, ProtocolException
from .file import File


def send(client: socket.socket, data: bytes) -> None:
    """ Use this function to automatically raise `ConnectionClosed` exception when client is disconnected. """

    try:
        sent_bytes = client.send(data)

        if sent_bytes == 0:  # Connection broken
            raise ConnectionClosed()

    except Exception:
        raise ConnectionClosed()


class SocReader:
    def __init__(self, max_buffer_size: Optional[int] = None):
        self.max_buffer_size = max_buffer_size

        if not max_buffer_size:
            # Default maximum buffer size is 8 kb
            self.max_buffer_size = 8 * 1024

    def read_bytes(self, client: socket.socket, size: int) -> bytes:
        """ Read bytes of given size from socket client. """

        # Create maximum bytearray of given size. Declaring size initially helps to reduce memory copying.
        data = bytearray(size)
        # Create a memory view on the data bytearray to prevent copying bytes
        memory_view = memoryview(data)

        bytes_in: int = 0
        buffer_size: int = min(size, self.max_buffer_size)

        while bytes_in != size:
            remaining_size = size - bytes_in
            max_read = min(remaining_size, buffer_size)
            chunk = client.recv(max_read)

            if not chunk:  # Connection broken
                raise ConnectionClosed()

            # Assign the chunk to the appropriate slice in the memory view
            memory_view[bytes_in:bytes_in + len(chunk)] = chunk
            bytes_in += len(chunk)

        return bytes(data)


class FrameReader:
    def __init__(self, timeout: Optional[int] = None, **kwargs: Any):
        self.timeout = timeout  # Raises ConnectionClosed if data not received in given period

        # Kwargs for `FrameReader` class
        self.soc_reader = kwargs.get('soc_reader')
        self.max_buffer_size = kwargs.get('max_buffer_size')

        if not self.soc_reader:
            self.soc_reader = SocReader(self.max_buffer_size)

    def read_status(self, client: socket.socket) -> Tuple[int, int]:
        """ Reads first byte from the dataframe. """

        first_byte = self.soc_reader.read_bytes(client, 1)
        status = ord(first_byte) >> 7  # Extract MSB from dataframe
        custom_status = ord(first_byte) & 0b01111111  # Extract remaining 7 bits
        return status, custom_status

    def read_protocol_version(self, client: socket.socket) -> int:
        """ See `BytesBuilder` class for more information. """

        return ord(self.soc_reader.read_bytes(client, 1))

    def count_number_of_files(self, client: socket.socket) -> int:
        """ See `BytesBuilder` class for more information. """

        return int.from_bytes(self.soc_reader.read_bytes(client, 8), byteorder='big')

    def read_file(self, client: socket.socket) -> Tuple[str, bytes, int]:
        """ See `BytesBuilder` class for more information. """

        # Extract filename
        filename_length = int.from_bytes(self.soc_reader.read_bytes(client, 2), byteorder='big')
        filename = self.soc_reader.read_bytes(client, filename_length).decode()

        # Extract file data
        file_length = int.from_bytes(self.soc_reader.read_bytes(client, 8), byteorder='big')
        file_data = self.soc_reader.read_bytes(client, file_length)
        return filename, file_data, file_length

    def read_files(self, client: socket.socket) -> List[File]:
        """ Read all the files from socket client. """

        files_count = self.count_number_of_files(client)
        files: List[File] = []

        for e in range(files_count):
            filename, file_data, file_size = self.read_file(client)
            files.append(File(filename, file_data))

        return files

    def read_message(self, client: socket.socket) -> Optional[bytes]:
        """ Read message from the dataframe. """

        message_length: int = int.from_bytes(self.soc_reader.read_bytes(client, 8), byteorder='big')

        if message_length == 0:
            return None

        return self.soc_reader.read_bytes(client, message_length)

    def read(self, client: socket.socket, callback: ResponseCallback) -> None:
        """ Read dataframes and handle response with callback. """

        status, custom_status = self.read_status(client)
        if status != 1:
            print('Invalid starting bit. Received: ', bin(status)[2:])
            raise ProtocolException()  # First bit must be 1 to be valid

        if self.timeout:
            # Once first data is received, listen incoming data with timeout to close bad network connection
            client.settimeout(self.timeout)

        # For every read, update the status and protocol version
        callback.custom_status = custom_status
        callback.protocol_version = self.read_protocol_version(client)

        # Read files and message received
        files = self.read_files(client)
        message = self.read_message(client)

        if self.timeout:
            client.settimeout(None)  # Make connection to listen forever

        # Send read files and message to callback method
        callback.received(files, message)


class BytesBuilder:
    """
    Constructs bytes for TEJ protocol. In short, this class creates the compatible bytes array for sending data
    with tcp socket. Bytes array are created when `build()` method is called.
    """

    def __init__(self, status_code: int = 0):
        # Validate custom status code value based on range
        in_range = (status_code >= 0 or status_code <= 0b01111111)
        if not in_range:
            raise InvalidStatusCode('The allowed range is 0 to 127')

        self._status_code: int = status_code
        self._protocol_version: int = 1

        # Optional attributes
        self._files: List[File] = []
        self._message: Optional[bytes] = None

    def set_protocol_version(self, version: int) -> 'BytesBuilder':
        """ Add protocol version information to dataframe. The version ranges from 0 to 256 integer. """

        # Check version range from 0 to 256
        if not (version >= 0 or version <= 256):
            raise InvalidProtocolVersion('The allowed range is 0 to 256')

        self._protocol_version = version
        return self

    def add_file(self, filename: str, data: bytes):
        """ Constructs file bytes with filename and data to the dataframe. """

        self._files.append(File(filename, data))
        return self

    def set_message(self, message: bytes):
        """ Sets message bytes to the dataframe. """

        self._message = message
        return self

    def __add_status__(self, dataframe: bytearray) -> None:
        """
        Adds 8 bits status information to the dataframe. It can be accessed while reading first 8bits data from
        the socket. The MSB is a status bit which should be always 1 and the remaining 7 bits are custom bits.
        If the MSB from the first byte is not 1, it will raise `ProtocolException` in both Server and Client.
        """

        status_byte = self._status_code | 0b10000000  # Set 1 to MSB
        dataframe.append(status_byte)

    def __add_protocol_version__(self, dataframe: bytearray) -> None:
        """ Adds 8 bits protocol version to the dataframe. Protocol is a integer range"""

        dataframe.append(self._protocol_version)

    def __add_files__(self, dataframe: bytearray) -> None:
        """
        Adds file count number to the dataframe along with the file information. The file information
        includes filename and file data.

        Here's the sequence:
        # Add files count information (64 bits)
        # Add 'n' filename length (16 bits)
        # Add 'n' filename text (varies)
        # Add 'n' file size length (64 bits)
        # Add 'n' file data (varies)
        """

        # Count the number of files present and add it to the dataframe.
        files_count = len(self._files)
        dataframe += files_count.to_bytes(8, byteorder='big')

        # Now, add an actual file information to the dataframe
        for file in self._files:
            # Add file length information to dataframe
            filename_length = len(file.name)
            dataframe += filename_length.to_bytes(2, byteorder='big')

            # Convert filename to bytes
            dataframe += bytes(file.name, 'utf-8')
            file_size = len(file.data)

            # Add filename length information in 64 bytes and append to dataframe
            file_length = file_size.to_bytes(8, byteorder='big')
            dataframe += file_length

            # Finally append file data to the dataframe
            dataframe += file.data

    def __add_message__(self, dataframe: bytearray) -> None:
        """
        Adds message length and actual message to the dataframe.
        Even if there is no message is None, 64 bits message length must be added to the dataframe.
        """

        # By default set message length to zero
        message_length: int = 0

        if self._message:
            message_length = len(self._message)

        # Message length 64 bit
        message_length_bytes = message_length.to_bytes(8, byteorder='big')
        dataframe += message_length_bytes

        if self._message:
            # Add actual message
            dataframe += self._message

    def bytes(self) -> bytes:
        """ Construct final bytes with the supplied information in the builder. """

        dataframe = bytearray()

        # Keep in this order to read the dataframes
        self.__add_status__(dataframe)
        self.__add_protocol_version__(dataframe)
        self.__add_files__(dataframe)
        self.__add_message__(dataframe)

        return bytes(dataframe)  # Returns constructed bytes
