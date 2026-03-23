#!/usr/bin/env python3
"""Test Python gRPC client."""

import sys
sys.path.insert(0, '/home/rockuw/freeman/SWE-bench/swebench/harness/aliyun_fc_eval')
from aliyun_fc_runtime import AliyunFCRuntime

# Mock test_spec
class MockTestSpec:
    instance_id = "sympy__sympy-20590"

endpoint = "swebench-eval-rvtjlikkuy.cn-shanghai.fcapp.run:8089"

print(f"Testing connection to {endpoint}...")

with AliyunFCRuntime(MockTestSpec(), endpoint) as runtime:
    # Test health check
    print("Testing health_check...")
    healthy = runtime.health_check()
    print(f"Health check: {healthy}")

    if healthy:
        # Test exec
        print("Testing exec...")
        output, rc = runtime.exec("echo hello")
        print(f"Exec output: {output.strip()}, return_code: {rc}")

        # Test write_file
        print("Testing write_file...")
        runtime.write_file("/tmp/test.txt", "hello world")
        print("Write file success")

        # Test read_file
        print("Testing read_file...")
        content = runtime.read_file("/tmp/test.txt")
        print(f"Read file: {content}")

print("All tests passed!")
