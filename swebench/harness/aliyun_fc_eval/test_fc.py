#!/usr/bin/env python3
"""
Test script to verify Aliyun FC evaluation setup.
Run this after deploying the function to verify it works.
"""

import argparse
import json
import sys


def main():
    parser = argparse.ArgumentParser(description="Test Aliyun FC evaluation")
    parser.add_argument(
        "--fc-endpoint",
        type=str,
        required=True,
        help="FC gRPC endpoint (e.g., swebench-eval.cn-hangzhou.fcapp.run:8089)",
    )
    parser.add_argument(
        "--instance-id",
        type=str,
        default="sympy__sympy-20590",
        help="Instance ID to test",
    )
    args = parser.parse_args()

    # Import after adding to path
    sys.path.insert(0, "/home/rockuw/freeman/SWE-bench")
    from swebench.harness.aliyun_fc_eval import AliyunFCRuntime
    from swebench.harness.test_spec.test_spec import make_test_spec
    from swebench.harness.utils import load_swebench_dataset
    from swebench.harness.constants import KEY_INSTANCE_ID, KEY_PREDICTION

    print(f"Testing Aliyun FC evaluation")
    print(f"Endpoint: {args.fc_endpoint}")
    print(f"Instance: {args.instance_id}")

    # Load dataset and get the instance
    print(f"\nLoading dataset...")
    dataset = load_swebench_dataset("princeton-nlp/SWE-bench_Lite", "test", [args.instance_id])

    if not dataset:
        print(f"Error: Instance {args.instance_id} not found in dataset")
        return 1

    instance = dataset[0]
    test_spec = make_test_spec(instance)

    # Get gold patch
    gold_patch = instance.get("patch", "")
    print(f"Gold patch loaded ({len(gold_patch)} bytes)")

    # Create runtime and test
    print(f"\nConnecting to FC container...")
    runtime = AliyunFCRuntime(test_spec, args.fc_endpoint, timeout=1800)

    with runtime:
        # Health check
        print(f"Running health check...")
        if not runtime.health_check():
            print("Error: Container health check failed")
            return 1
        print("Container is healthy!")

        # Note: Repo is already in the image at /testbed
        testbed_path = "/testbed"
        print(f"Using testbed at: {testbed_path}")

        # Apply patch
        print(f"\nApplying patch...")
        patch_file = "/tmp/patch.diff"
        runtime.write_file(patch_file, gold_patch)
        output, rc = runtime.exec(f"git apply {patch_file}", workdir=testbed_path)
        print(f"Apply result: rc={rc}")
        if rc != 0:
            print(f"Output: {output}")

        # Run eval script
        print(f"\nRunning eval script...")
        eval_file = "/tmp/eval.sh"
        runtime.write_file(eval_file, test_spec.eval_script)
        output, rc = runtime.exec(f"bash {eval_file}", workdir=testbed_path)
        print(f"Eval result: rc={rc}")
        print(f"Output length: {len(output)} bytes")

        # Show first 500 chars of output
        print(f"\nOutput preview:")
        print(output[:500])

    print("\n✓ Test completed successfully!")
    return 0


if __name__ == "__main__":
    sys.exit(main())
