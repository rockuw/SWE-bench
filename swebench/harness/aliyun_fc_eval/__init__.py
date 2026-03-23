"""
Aliyun FC Evaluation Module.

This module provides functionality to run SWE-bench evaluations
using Aliyun Function Compute (FC) with custom container runtime.

Usage:
1. Build and deploy the function:
   cd swebench/harness/aliyun_fc_eval
   s deploy

2. Run evaluation with gold predictions:
   python -m swebench.harness.run_evaluation \
       --predictions_path gold \
       --max_workers 1 \
       --instance_ids sympy__sympy-20590 \
       --run_id validate-gold-fc \
       --aliyun_fc true \
       --fc_endpoint <fc-endpoint>
"""

# Import generated gRPC code
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from proto import container_pb2
from proto import container_pb2_grpc

from aliyun_fc_runtime import AliyunFCRuntime
from run_evaluation_aliyun import (
    run_instance_aliyun,
    run_instances_aliyun,
    get_fc_endpoint,
)

__all__ = [
    "AliyunFCRuntime",
    "run_instance_aliyun",
    "run_instances_aliyun",
    "get_fc_endpoint",
    "container_pb2",
    "container_pb2_grpc",
]
