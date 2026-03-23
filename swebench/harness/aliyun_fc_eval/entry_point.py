"""
Entry point for Aliyun FC container.
Provides HTTP endpoints for container operations.
"""

import sys
import os
import json
import asyncio
from aiohttp import web

# Add proto to path
sys.path.insert(0, "/proto")
sys.path.insert(0, "/")

from grpc_server import ContainerServiceServicer
import container_pb2
import container_pb2_grpc
import grpc
from concurrent import futures

# Global servicer
servicer = ContainerServiceServicer()

async def health_check(request):
    """Health check endpoint."""
    return web.json_response({"status": "ok"})

async def initialize_testbed(request):
    """Initialize testbed endpoint."""
    try:
        data = await request.json()
        # Call the synchronous method
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None,
            servicer.InitializeTestbed,
            container_pb2.InitializeRequest(
                repo=data.get("repo", ""),
                base_commit=data.get("base_commit", ""),
                instance_id=data.get("instance_id", ""),
            ),
            None
        )
        return web.json_response({"success": result.success, "testbed_path": result.testbed_path, "error": result.error})
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)

async def exec_command(request):
    """Execute command endpoint."""
    try:
        data = await request.json()
        command = data.get("command", "")
        workdir = data.get("workdir", "/testbed")

        # Run command synchronously
        loop = asyncio.get_event_loop()
        output_parts = []
        return_code = 0

        # Use executor to run subprocess
        proc = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            cwd=workdir
        )
        stdout, _ = await proc.communicate()
        output = stdout.decode('utf-8')
        return_code = proc.returncode

        return web.json_response({
            "output": output,
            "return_code": return_code,
            "eof": True
        })
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)

async def write_file(request):
    """Write file endpoint."""
    try:
        data = await request.json()
        path = data.get("path", "")
        content = data.get("content", "")
        mode = data.get("mode", "text")

        os.makedirs(os.path.dirname(path), exist_ok=True)

        if mode == "binary":
            import base64
            content = base64.b64decode(content)
            with open(path, "wb") as f:
                f.write(content)
        else:
            with open(path, "w") as f:
                f.write(content)

        return web.json_response({"success": True})
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)

async def run_evaluation(request):
    """Run full evaluation endpoint."""
    try:
        data = await request.json()
        patch = data.get("patch", "")
        eval_script = data.get("eval_script", "")
        timeout = data.get("timeout", 1800)

        # Write patch file
        patch_path = "/tmp/patch.diff"
        with open(patch_path, "w") as f:
            f.write(patch)

        # Apply patch
        import subprocess
        apply_result = subprocess.run(
            f"git apply {patch_path}",
            shell=True,
            capture_output=True,
            text=True,
            cwd="/testbed",
        )

        if apply_result.returncode != 0:
            apply_result = subprocess.run(
                f"patch --batch --fuzz=5 -p1 -i {patch_path}",
                shell=True,
                capture_output=True,
                text=True,
                cwd="/testbed",
            )

        # Write eval script
        eval_path = "/tmp/eval.sh"
        with open(eval_path, "w") as f:
            f.write(eval_script)
        os.chmod(eval_path, 0o755)

        # Run evaluation
        eval_result = subprocess.run(
            f"bash {eval_path}",
            shell=True,
            capture_output=True,
            text=True,
            cwd="/testbed",
            timeout=timeout,
        )

        # Get git diff
        diff_result = subprocess.run(
            "git diff",
            shell=True,
            capture_output=True,
            text=True,
            cwd="/testbed",
        )

        return web.json_response({
            "test_output": eval_result.stdout + eval_result.stderr,
            "return_code": eval_result.returncode,
            "git_diff": diff_result.stdout,
        })
    except subprocess.TimeoutExpired:
        return web.json_response({"error": "Timeout", "return_code": -1}, status=500)
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)

def create_app():
    """Create the aiohttp application."""
    app = web.Application()
    app.router.add_get('/health_check', health_check)
    app.router.add_post('/initialize', initialize_testbed)
    app.router.add_post('/exec', exec_command)
    app.router.add_post('/write_file', write_file)
    app.router.add_post('/run_evaluation', run_evaluation)
    return app

if __name__ == '__main__':
    port = int(os.environ.get('FC_FUNCTION_PORT', 9000))
    app = create_app()
    web.run_app(app, host='0.0.0.0', port=port, print=lambda x: None)
