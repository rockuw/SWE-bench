"""
Aliyun FC Runtime - provides Docker SDK-like interface using HTTP.
"""

import base64
import json
import subprocess
import time
from typing import Optional

import requests
from requests.exceptions import RequestException


class AliyunFCRuntime:
    """
    Runtime that provides Docker SDK-like interface using HTTP.
    Uses 's invoke' to communicate with the FC function.
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
            fc_endpoint: Not used directly, we use s invoke
            timeout: Default timeout for operations in seconds
        """
        self.test_spec = test_spec
        self.fc_endpoint = fc_endpoint
        self.timeout = timeout

        # Track initialization state
        self.initialized = False
        self.testbed_path = None

    def _invoke_fc(self, payload: dict, path: str = "/") -> dict:
        """
        Invoke the FC function using 's invoke'.

        Args:
            payload: Request payload as dict
            path: Path to invoke (default: /)

        Returns:
            Response as dict
        """
        # Convert payload to JSON string and base64 encode
        payload_json = json.dumps(payload)
        payload_b64 = base64.b64encode(payload_json.encode()).decode()

        # Path to the s.yaml file
        s_yaml_path = "/home/rockuw/freeman/SWE-bench/swebench/harness/aliyun_fc_eval"

        # Use s invoke to call the function
        cmd = [
            "s", "invoke",
            "swebench-eval",
            "--region", "cn-shanghai",
            "--event", payload_b64,
        ]

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=self.timeout + 60,
                cwd=s_yaml_path,
            )

            # Parse the output
            if result.returncode != 0:
                raise Exception(f"s invoke failed: {result.stderr}")

            # The output contains the response - extract it
            # s invoke output contains log lines, find the JSON response
            output = result.stdout.strip()

            # Find JSON in output (starts with { and ends with })
            json_start = output.find('{')
            json_end = output.rfind('}') + 1

            if json_start >= 0 and json_end > json_start:
                json_str = output[json_start:json_end]
                try:
                    return json.loads(json_str)
                except json.JSONDecodeError:
                    pass

            # Return as plain text response
            return {"output": output, "raw": True}

        except subprocess.TimeoutExpired:
            raise Exception("FC invocation timed out")
        except Exception as e:
            raise Exception(f"FC invocation failed: {e}")

    def health_check(self) -> bool:
        """Check if the container is healthy."""
        # Retry a few times to handle cold starts
        max_retries = 5
        for attempt in range(max_retries):
            try:
                response = self._invoke_fc({}, path="/health_check")
                if response.get("status") == "ok":
                    return True
                print(f"Health check attempt {attempt + 1} returned: {response}")
            except Exception as e:
                print(f"Health check attempt {attempt + 1} failed: {e}")
                if attempt < max_retries - 1:
                    import time
                    time.sleep(2)  # Wait before retry
        return False

    def initialize_testbed(self, repo: str, base_commit: str) -> str:
        """
        Initialize the testbed by cloning the repo and checking out the commit.

        Args:
            repo: Repository name (e.g., 'sympy/sympy')
            base_commit: Git commit SHA

        Returns:
            Path to the testbed

        Raises:
            Exception: If initialization fails
        """
        request = {
            "repo": repo,
            "base_commit": base_commit,
            "instance_id": self.test_spec.instance_id,
        }

        response = self._invoke_fc(request, path="/initialize")

        if not response.get("success"):
            raise Exception(f"Failed to initialize testbed: {response.get('error')}")

        self.initialized = True
        self.testbed_path = response.get("testbed_path")
        return self.testbed_path

    def write_file(self, path: str, content: str, is_binary: bool = False) -> None:
        """
        Write file to container (like docker.utils.copy_to_container).

        Args:
            path: Destination path in container
            content: File content
            is_binary: Whether content is binary
        """
        mode = "binary" if is_binary else "text"

        if is_binary:
            content_encoded = base64.b64encode(content).decode('utf-8')
        else:
            content_encoded = content

        request = {
            "path": path,
            "content": content_encoded,
            "mode": mode,
        }

        response = self._invoke_fc(request, path="/write_file")
        if not response.get("success"):
            raise Exception(f"Failed to write file: {response.get('error')}")

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
        request = {
            "command": command,
            "workdir": workdir or "/testbed",
        }

        response = self._invoke_fc(request, path="/exec")

        output = response.get("output", "")
        return_code = response.get("return_code", 0)

        return output, return_code

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
        # This method may not be needed for current use cases
        raise NotImplementedError("read_file not implemented for HTTP runtime")

    def run_evaluation(
        self,
        patch: str,
        eval_script: str,
        timeout: Optional[int] = None,
    ) -> dict:
        """
        Run the full evaluation in one call.

        Args:
            patch: The patch to apply
            eval_script: Evaluation script to run
            timeout: Timeout in seconds

        Returns:
            Dict with test_output, return_code, git_diff
        """
        timeout = timeout or self.timeout

        request = {
            "instance_id": self.test_spec.instance_id,
            "patch": patch,
            "eval_script": eval_script,
            "timeout": timeout,
        }

        response = self._invoke_fc(request, path="/run_evaluation")

        return {
            "test_output": response.get("test_output", ""),
            "return_code": response.get("return_code", 0),
            "git_diff": response.get("git_diff", ""),
            "error": response.get("error"),
        }

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def close(self):
        """Close the runtime (no-op for HTTP)."""
        pass
