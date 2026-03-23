"""
gRPC server that runs inside the Aliyun FC container.
Provides container operations: exec, file read/write, evaluation.
"""

from concurrent import futures
import grpc
import subprocess
import os
import sys
import base64
import shutil
import tempfile
from pathlib import Path

# Import generated gRPC code
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from proto import container_pb2
from proto import container_pb2_grpc


class ContainerServiceServicer(container_pb2_grpc.ContainerServiceServicer):
    """gRPC service for container operations."""

    def __init__(self):
        self.testbed_path = "/testbed"
        self.initialized = False

    def HealthCheck(self, request, context):
        """Health check endpoint."""
        return container_pb2.HealthCheckResponse(
            healthy=True,
            message="Container is running"
        )

    def ExecCommand(self, request, context):
        """Execute command and stream output."""
        workdir = request.workdir if request.workdir else self.testbed_path

        # Ensure workdir exists
        os.makedirs(workdir, exist_ok=True)

        process = subprocess.Popen(
            request.command,
            shell=True,
            cwd=workdir,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )

        while True:
            line = process.stdout.readline()
            if not line and process.poll() is not None:
                break
            yield container_pb2.ExecResponse(
                output=line,
                return_code=process.poll(),
                eof=False
            )

        yield container_pb2.ExecResponse(
            output=b"",
            return_code=process.returncode,
            eof=True
        )

    def WriteFile(self, request, context):
        """Write file to container."""
        path = request.path
        os.makedirs(os.path.dirname(path), exist_ok=True)

        content = request.content
        if request.mode == "binary":
            content = base64.b64decode(content)
        else:
            content = content  # Already bytes from proto

        mode = "wb" if request.mode == "binary" else "w"
        with open(path, mode) as f:
            f.write(content)

        return container_pb2.WriteResponse(success=True)

    def ReadFile(self, request, context):
        """Read file from container."""
        path = request.path
        offset = request.offset or 0
        limit = request.limit or 0

        try:
            with open(path, "rb") as f:
                f.seek(offset)
                if limit > 0:
                    content = f.read(limit)
                else:
                    content = f.read()

            return container_pb2.ReadResponse(content=content)
        except FileNotFoundError:
            context.set_code(grpc.StatusCode.NOT_FOUND)
            context.set_details(f"File not found: {path}")
            return container_pb2.ReadResponse(content=b"")
        except Exception as e:
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(str(e))
            return container_pb2.ReadResponse(content=b"")

    def InitializeTestbed(self, request, context):
        """Initialize testbed: clone repo and setup environment."""
        repo = request.repo
        base_commit = request.base_commit
        instance_id = request.instance_id

        print(f"Initializing testbed for {instance_id}")
        print(f"Repo: {repo}, Commit: {base_commit}")

        try:
            # Create testbed directory
            os.makedirs(self.testbed_path, exist_ok=True)

            # Clone the repository if not already present
            repo_name = repo.split("/")[-1]
            repo_path = os.path.join(self.testbed_path, repo_name)

            if not os.path.exists(repo_path):
                print(f"Cloning {repo}...")
                # Use git clone --depth 1 for faster clone
                clone_result = subprocess.run(
                    f"git clone --depth 1 https://github.com/{repo}.git {repo_path}",
                    shell=True,
                    capture_output=True,
                    text=True,
                    cwd=self.testbed_path,
                )
                if clone_result.returncode != 0:
                    return container_pb2.InitializeResponse(
                        success=False,
                        error=f"Failed to clone repo: {clone_result.stderr}"
                    )

            # Checkout to the specific commit
            print(f"Checking out to {base_commit}...")
            checkout_result = subprocess.run(
                f"git fetch origin {base_commit} && git checkout {base_commit}",
                shell=True,
                capture_output=True,
                text=True,
                cwd=repo_path,
            )
            if checkout_result.returncode != 0:
                # Try without fetch
                checkout_result = subprocess.run(
                    f"git checkout {base_commit}",
                    shell=True,
                    capture_output=True,
                    text=True,
                    cwd=repo_path,
                )
                if checkout_result.returncode != 0:
                    return container_pb2.InitializeResponse(
                        success=False,
                        error=f"Failed to checkout: {checkout_result.stderr}"
                    )

            self.initialized = True
            self.repo_path = repo_path

            return container_pb2.InitializeResponse(
                success=True,
                testbed_path=repo_path
            )

        except Exception as e:
            return container_pb2.InitializeResponse(
                success=False,
                error=str(e)
            )

    def RunEvaluation(self, request, context):
        """Run full evaluation."""
        patch = request.patch
        eval_script = request.eval_script
        timeout = request.timeout or 1800
        instance_id = request.instance_id

        print(f"Running evaluation for {instance_id}")

        try:
            # Write patch file
            patch_path = os.path.join("/tmp", "patch.diff")
            with open(patch_path, "w") as f:
                f.write(patch)

            # Apply patch
            apply_result = subprocess.run(
                f"git apply {patch_path}",
                shell=True,
                capture_output=True,
                text=True,
                cwd=self.repo_path,
            )

            if apply_result.returncode != 0:
                # Try alternative patch method
                apply_result = subprocess.run(
                    f"patch --batch --fuzz=5 -p1 -i {patch_path}",
                    shell=True,
                    capture_output=True,
                    text=True,
                    cwd=self.repo_path,
                )

            # Write eval script
            eval_path = os.path.join("/tmp", "eval.sh")
            with open(eval_path, "w") as f:
                f.write(eval_script)
            os.chmod(eval_path, 0o755)

            # Run evaluation
            print(f"Running eval script...")
            eval_result = subprocess.run(
                f"bash {eval_path}",
                shell=True,
                capture_output=True,
                text=True,
                cwd=self.repo_path,
                timeout=timeout,
            )

            # Get git diff
            diff_result = subprocess.run(
                "git diff",
                shell=True,
                capture_output=True,
                text=True,
                cwd=self.repo_path,
            )

            return container_pb2.EvalResponse(
                test_output=eval_result.stdout + eval_result.stderr,
                return_code=eval_result.returncode,
                git_diff=diff_result.stdout,
            )

        except subprocess.TimeoutExpired:
            return container_pb2.EvalResponse(
                test_output="",
                return_code=-1,
                git_diff="",
                error=f"Evaluation timed out after {timeout} seconds"
            )
        except Exception as e:
            return container_pb2.EvalResponse(
                test_output="",
                return_code=-1,
                git_diff="",
                error=str(e)
            )


def serve(port=9000):
    """Start the gRPC server."""
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    container_pb2_grpc.add_ContainerServiceServicer_to_server(
        ContainerServiceServicer(), server
    )
    server.add_insecure_port(f'[::]:{port}')
    server.start()
    print(f"gRPC server started on port {port}")
    server.wait_for_termination()


if __name__ == '__main__':
    serve()
