"""
Aliyun FC Runtime - provides Docker SDK-like interface using gRPC.
"""

import grpc
import ssl
import base64
import logging
from typing import Optional

# Add proto to path
import sys
sys.path.insert(0, '/home/rockuw/freeman/SWE-bench/swebench/harness/aliyun_fc_eval/proto')
import container_pb2
import container_pb2_grpc

logger = logging.getLogger(__name__)


class AliyunFCRuntime:
    """
    Runtime that provides Docker SDK-like interface using gRPC.
    Uses bi-directional streaming for persistent connection.
    """

    def __init__(
        self,
        test_spec,
        fc_endpoint: str,
        timeout: int = 1800,
    ):
        """
        Initialize the runtime.

        Args:
            test_spec: TestSpec instance
            fc_endpoint: FC endpoint (e.g., swebench-eval-xxx.cn-shanghai.fcapp.run:8089)
            timeout: Default timeout for operations in seconds
        """
        self.test_spec = test_spec
        self.fc_endpoint = fc_endpoint
        self.timeout = timeout
        self.channel = None
        self.stub = None
        self.session = None

    def _create_channel(self):
        """Create gRPC channel with TLS."""
        # Use default SSL credentials - this should work with Aliyun's valid cert
        credentials = grpc.ssl_channel_credentials()

        self.channel = grpc.secure_channel(
            self.fc_endpoint,
            credentials,
            options=[
                ('grpc.http2.enable', True),
            ]
        )
        self.stub = container_pb2_grpc.ContainerServiceStub(self.channel)

    def connect(self):
        """Connect to the FC container."""
        logger.info(f"Connecting to FC endpoint: {self.fc_endpoint}")
        self._create_channel()
        logger.info("FC connection established")

    def health_check(self) -> bool:
        """Check if the container is healthy."""
        logger.info("Running health check...")
        try:
            response = self.stub.HealthCheck(container_pb2.HealthCheckRequest())
            logger.info(f"Health check response: healthy={response.healthy}, message={response.message}")
            return response.healthy
        except grpc.RpcError as e:
            logger.error(f"Health check failed: {e.code()}: {e.details()}")
            return False

    def write_file(self, path: str, content: str, is_binary: bool = False) -> None:
        """
        Write file to container (like docker.utils.copy_to_container).

        Args:
            path: Destination path in container
            content: File content
            is_binary: Whether content is binary
        """
        mode = "binary" if is_binary else "text"
        logger.info(f"Writing file: {path} (mode={mode}, size={len(content)} bytes)")

        if is_binary:
            content_bytes = content
        else:
            content_bytes = content.encode('utf-8')

        request = container_pb2.SessionRequest(
            request_type="write_file",
            path=path,
            content=content_bytes,
            mode=mode,
        )

        # Send request and get response
        # For write_file, we use a simple request-response pattern
        # The server should handle it and return response
        # We'll need to use a stream for this
        for response in self.stub.ContainerSession(iter([request])):
            if response.success:
                return
            else:
                raise Exception(f"Failed to write file: {response.error}")

    def exec(
        self,
        command: str,
        workdir: Optional[str] = None,
    ) -> tuple[str, int]:
        """
        Execute command in container (like container.exec_run).

        Args:
            command: Command to execute
            workdir: Working directory

        Returns:
            Tuple of (output, return_code)
        """
        if workdir is None:
            workdir = "/testbed"

        logger.info(f"Executing command: {command} (workdir={workdir})")

        request = container_pb2.SessionRequest(
            request_type="exec",
            command=command,
            workdir=workdir,
        )

        output = []
        return_code = 0

        for response in self.stub.ContainerSession(iter([request])):
            if response.output:
                output.append(response.output.decode('utf-8'))
            if response.eof:
                return_code = response.return_code
                break

        logger.info(f"Command completed: return_code={return_code}, output_size={len(''.join(output))} bytes")

        return "".join(output), return_code

    def read_file(self, path: str, offset: int = 0, limit: int = 0) -> bytes:
        """
        Read file from container.

        Args:
            path: File path
            offset: Byte offset to start reading from
            limit: Maximum bytes to read (0 = read all)

        Returns:
            File content
        """
        logger.info(f"Reading file: {path}")
        request = container_pb2.SessionRequest(
            request_type="read_file",
            path=path,
        )

        for response in self.stub.ContainerSession(iter([request])):
            if response.success:
                logger.info(f"Read file success: {path} ({len(response.content)} bytes)")
                return response.content
            else:
                raise Exception(f"Failed to read file: {response.error}")

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def close(self):
        """Close gRPC connection."""
        if self.channel:
            logger.info("Closing gRPC connection")
            self.channel.close()
