"""
Run SWE-bench evaluation using Aliyun FC.
"""

import json
import time
import traceback
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from swebench.harness.aliyun_fc_eval.aliyun_fc_runtime import AliyunFCRuntime
from swebench.harness.constants import (
    APPLY_PATCH_FAIL,
    APPLY_PATCH_PASS,
    RUN_EVALUATION_LOG_DIR,
)
from swebench.harness.docker_build import setup_logger
from swebench.harness.grading import get_eval_report
from swebench.harness.test_spec.test_spec import TestSpec
from swebench.harness.utils import EvaluationError


# gRPC default port for FC custom container
DEFAULT_FC_PORT = 9000


@dataclass
class TestOutput:
    instance_id: str
    test_output: str
    report_json_str: str
    run_instance_log: str
    patch_diff: str
    log_dir: Path
    errored: bool


def get_fc_endpoint(
    region: str,
    function_name: str,
    use_https: bool = True,
    custom_domain: Optional[str] = None,
) -> str:
    """
    Get the FC gRPC endpoint.

    Args:
        region: Aliyun region (e.g., 'cn-hangzhou')
        function_name: Function name
        use_https: Whether to use HTTPS
        custom_domain: Custom domain if configured

    Returns:
        gRPC endpoint URL
    """
    if custom_domain:
        host = custom_domain
    else:
        host = f"{function_name}.{region}.fc.aliyuncs.com"

    scheme = "https" if use_https else "http"
    port = 443 if use_https else 9000

    return f"{host}:{port}"


def get_log_dir(pred: dict, run_id: str, instance_id: str) -> Path:
    """Get the log directory for an instance."""
    model_name_or_path = pred.get("model_name_or_path", "None").replace("/", "__")
    return RUN_EVALUATION_LOG_DIR / run_id / model_name_or_path / instance_id


def run_instance_aliyun(
    test_spec: TestSpec,
    pred: dict,
    run_id: str,
    fc_endpoint: str,
    timeout: Optional[int] = None,
) -> TestOutput:
    """
    Run a single instance with the given prediction using Aliyun FC.

    Args:
        test_spec: TestSpec instance
        pred: Prediction dict with patch
        run_id: Run ID
        fc_endpoint: gRPC endpoint for FC function
        timeout: Timeout for running tests

    Returns:
        TestOutput with results
    """
    instance_id = test_spec.instance_id
    log_dir = get_log_dir(pred, run_id, instance_id)
    log_dir.mkdir(parents=True, exist_ok=True)

    log_file = log_dir / "run_instance.log"
    logger = setup_logger(instance_id, log_file, add_stdout=True)

    patch_diff = pred.get("patch", "")

    try:
        # Connect to FC container via gRPC
        logger.info(f"Connecting to FC endpoint: {fc_endpoint}")
        runtime = AliyunFCRuntime(test_spec, fc_endpoint, timeout or 1800)

        # Check health
        if not runtime.health_check():
            raise Exception("Container health check failed")

        # Initialize testbed
        logger.info(f"Initializing testbed for {instance_id}")
        logger.info(f"Repo: {test_spec.repo}, Commit: {test_spec.base_commit}")

        testbed_path = runtime.initialize_testbed(
            test_spec.repo,
            test_spec.base_commit,
        )
        logger.info(f"Testbed initialized at: {testbed_path}")

        # Write patch file
        patch_file = "/tmp/patch.diff"
        runtime.write_file(patch_file, patch_diff)

        # Apply patch
        apply_output, returncode = runtime.exec(
            f"git apply {patch_file}",
            workdir=testbed_path,
        )

        if returncode != 0:
            logger.info(f"Failed to apply patch with git apply, trying patch command...")
            apply_output, returncode = runtime.exec(
                f"patch --batch --fuzz=5 -p1 -i {patch_file}",
                workdir=testbed_path,
            )

            if returncode != 0:
                logger.info(f"{APPLY_PATCH_FAIL}:\n{apply_output}")
                raise EvaluationError(
                    instance_id,
                    f"{APPLY_PATCH_FAIL}:\n{apply_output}",
                    logger,
                )
            else:
                logger.info(f"{APPLY_PATCH_PASS}:\n{apply_output}")
        else:
            logger.info(f"{APPLY_PATCH_PASS}:\n{apply_output}")

        # Get git diff before running eval script
        git_diff_before, _ = runtime.exec("git diff", workdir=testbed_path)
        logger.info(f"Git diff before:\n{git_diff_before}")

        # Write eval script
        eval_file = "/tmp/eval.sh"
        eval_script = test_spec.eval_script
        runtime.write_file(eval_file, eval_script)

        # Run evaluation
        start_time = time.time()
        test_output, returncode = runtime.exec(
            f"bash {eval_file}",
            workdir=testbed_path,
        )
        total_runtime = time.time() - start_time

        # Write test output to log
        test_output_path = log_dir / "test_output.txt"
        logger.info(f"Test runtime: {total_runtime:_.2f} seconds")
        with open(test_output_path, "w") as f:
            f.write(test_output)
            logger.info(f"Test output for {instance_id} written to {test_output_path}")

        # Get git diff after running eval script
        git_diff_after, _ = runtime.exec("git diff", workdir=testbed_path)
        logger.info(f"Git diff after:\n{git_diff_after}")

        if git_diff_after != git_diff_before:
            logger.info("Git diff changed after running eval script")

        # Get report from test output
        logger.info(f"Grading answer for {instance_id}...")
        report = get_eval_report(
            test_spec=test_spec,
            prediction=pred,
            test_log_path=test_output_path,
            include_tests_status=True,
        )
        logger.info(
            f"report: {report}\n"
            f"Result for {instance_id}: resolved: {report[instance_id]['resolved']}"
        )

        # Close the runtime
        runtime.close()

        return TestOutput(
            instance_id=instance_id,
            test_output=test_output,
            report_json_str=json.dumps(report, indent=4),
            run_instance_log=log_file.read_text(),
            patch_diff=patch_diff,
            log_dir=log_dir,
            errored=False,
        )

    except EvaluationError:
        error_msg = traceback.format_exc()
        logger.info(error_msg)
        return TestOutput(
            instance_id=instance_id,
            test_output="",
            report_json_str="",
            run_instance_log=log_file.read_text(),
            patch_diff=patch_diff,
            log_dir=log_dir,
            errored=True,
        )
    except Exception as e:
        error_msg = (
            f"Error in evaluating model for {instance_id}: {e}\n"
            f"{traceback.format_exc()}\n"
            f"Check ({log_file}) for more information."
        )
        logger.error(error_msg)
        return TestOutput(
            instance_id=instance_id,
            test_output="",
            report_json_str="",
            run_instance_log=log_file.read_text(),
            patch_diff=patch_diff,
            log_dir=log_dir,
            errored=True,
        )


def run_instances_aliyun(
    predictions: dict,
    instances: list,
    full_dataset: list,
    run_id: str,
    fc_endpoint: str,
    timeout: int,
):
    """
    Run all instances for the given predictions on Aliyun FC.

    Args:
        predictions: Predictions dict
        instances: List of instances
        full_dataset: Full dataset
        run_id: Run ID
        fc_endpoint: gRPC endpoint for FC function
        timeout: Timeout for running tests
    """
    from swebench.harness.reporting import make_run_report
    from swebench.harness.test_spec.test_spec import make_test_spec

    test_specs = list(map(make_test_spec, instances))

    # Run test specs
    for test_spec in test_specs:
        log_dir = get_log_dir(
            predictions[test_spec.instance_id],
            run_id,
            test_spec.instance_id,
        )

        # Check if already run
        if (log_dir / "report.json").exists():
            print(f"Skipping {test_spec.instance_id} - already run")
            continue

        print(f"Running {test_spec.instance_id}...")

        result = run_instance_aliyun(
            test_spec=test_spec,
            pred=predictions[test_spec.instance_id],
            run_id=run_id,
            fc_endpoint=fc_endpoint,
            timeout=timeout,
        )

        # Save logs locally
        log_dir.mkdir(parents=True, exist_ok=True)
        with open(log_dir / "run_instance.log", "w") as f:
            f.write(result.run_instance_log)
        with open(log_dir / "test_output.txt", "w") as f:
            f.write(result.test_output)
        with open(log_dir / "patch.diff", "w") as f:
            f.write(result.patch_diff)
        with open(log_dir / "report.json", "w") as f:
            try:
                report_json = json.loads(result.report_json_str)
                json.dump(report_json, f, indent=4)
            except Exception:
                print(f"{result.instance_id}: no report.json")

    # Make run report
    make_run_report(predictions, full_dataset, run_id)
