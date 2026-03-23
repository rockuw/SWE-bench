#!/usr/bin/env python3
"""Test gRPC connection to Aliyun FC using HTTP/2."""

import grpc
import sys
sys.path.insert(0, '/home/rockuw/freeman/SWE-bench/swebench/harness/aliyun_fc_eval/proto')
import container_pb2
import container_pb2_grpc

def test_health_check():
    endpoint = "swebench-eval.fcv3.1237050315505682.cn-shanghai.fc.devsapp.net:8089"

    # Create channel with HTTP/2
    channel = grpc.insecure_channel(
        endpoint,
        options=[
            ('grpc.http2.max_concurrent_streams', 100),
            ('grpc.http2.enable_huffman_compression', True),
        ]
    )
    stub = container_pb2_grpc.ContainerServiceStub(channel)

    # Test health check
    try:
        response = stub.HealthCheck(container_pb2.HealthCheckRequest())
        print(f"Health Check Response: healthy={response.healthy}, message={response.message}")
        return True
    except grpc.RpcError as e:
        print(f"Health Check Failed: {e.code()}: {e.details()}")
        return False
    finally:
        channel.close()

if __name__ == "__main__":
    success = test_health_check()
    sys.exit(0 if success else 1)
