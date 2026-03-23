# Plan: Run SWE-bench Evaluation on Aliyun Function Compute (FC)

## Overview

This document outlines a plan to replace local Docker-based evaluation with Aliyun Function Compute's custom container runtime. This enables serverless evaluation without requiring Docker daemon on the local machine.

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────┐
│              SWE-bench Evaluation on Aliyun FC                      │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  ┌─────────────────────┐    gRPC (bi-directional stream)          │
│  │   Host (Python)    │◀─────────────────────────────────────────▶│
│  │                     │    ┌────────────────────────────────────┐  │
│  │ - Load data        │    │   Aliyun FC Custom Container      │  │
│  │ - Serialize patch  │    │                                    │  │
│  │ - Run eval via gRPC│    │  ┌─────────────────────────────┐  │  │
│  │ - Collect results  │    │  │   Go gRPC Server           │  │  │
│  └─────────────────────┘    │  │   (fc_server on port 8089) │  │  │
│                             │  │                             │  │  │
│                             │  │  - ContainerSession (stream)│  │  │
│                             │  │  - HealthCheck              │  │  │
│                             │  │  - exec, write_file, read   │  │  │
│                             │  └─────────────────────────────┘  │  │
│                             │                                    │  │
│                             │  ┌─────────────────────────────┐  │  │
│                             │  │   SWE-bench Image           │  │  │
│                             │  │   (/testbed with repo)      │  │  │
│                             │  └─────────────────────────────┘  │  │
│                             └────────────────────────────────────┘  │
│                                    │                                │
│                                    ▼                                │
│                             ┌────────────────┐                      │
│                             │   Output       │                      │
│                             │ - Test output  │                      │
│                             │ - Report.json  │                      │
│                             │ - Logs         │                      │
│                             └────────────────┘                      │
└─────────────────────────────────────────────────────────────────────┘
```

## Key Components

### 1. Aliyun FC Runtime (`AliyunFCRuntime`)

**Location**: `swebench/harness/aliyun_fc_eval/aliyun_fc_runtime.py`

A Python class that manages the Aliyun FC function invocation via gRPC bi-directional streaming. It provides a Docker SDK-like interface:

```python
class AliyunFCRuntime:
    """Runtime for running instances in Aliyun FC custom container."""

    def __init__(self, test_spec, fc_endpoint: str, timeout: int = 1800):
        """
        Initialize the runtime.

        Args:
            test_spec: TestSpec instance
            fc_endpoint: FC endpoint (e.g., swebench-eval-xxx.cn-shanghai.fcapp.run:8089)
            timeout: Default timeout for operations in seconds
        """

    def connect(self):
        """Connect to the FC container via gRPC."""

    def health_check(self) -> bool:
        """Check if the container is healthy."""

    def write_file(self, path: str, content: str, is_binary: bool = False):
        """Write file to container via gRPC bi-directional stream."""

    def exec(self, command: str, workdir: str = "/testbed") -> tuple[str, int]:
        """Execute command in container via gRPC bi-directional stream."""

    def read_file(self, path: str, offset: int = 0, limit: int = 0) -> bytes:
        """Read file from container via gRPC stream."""

    def close(self):
        """Close gRPC connection."""
```

### 2. Go gRPC Server (`fc_server`)

**Location**: `swebench/harness/aliyun_fc_eval/main.go`

A Go-based gRPC server that runs inside the FC container, providing bi-directional streaming for stateful operations:

- **Port**: 8089
- **Protocol**: gRPC with HTTP/2
- **Transport**: TLS (SSL credentials)

```protobuf
service ContainerService {
    rpc HealthCheck(HealthCheckRequest) returns (HealthCheckResponse);
    rpc ContainerSession(stream SessionRequest) returns (stream SessionResponse);
}
```

The `ContainerSession` method uses bi-directional streaming:
- Client sends `SessionRequest` (exec, write_file, read_file)
- Server streams `SessionResponse` (output, return_code, content)
- Single persistent connection for all operations (stateful)

### 3. Docker Image for Custom Container

**Location**: `swebench/harness/aliyun_fc_eval/Dockerfile`

The image is based on a pre-built SWE-bench evaluation image which already contains the repository checked out at `base_commit` and all required dependencies.

```dockerfile
FROM swebench/sweb.eval.x86_64.sympy_1776_sympy-20590:latest
COPY fc_server /fc_server
RUN chmod +x /fc_server
```

### 4. Main Orchestration

**Location**: `swebench/harness/aliyun_fc_eval/run_evaluation_aliyun.py`

Coordinates the evaluation workflow:
1. Connect to FC via gRPC
2. Reset git state (clean container)
3. Write patch file via gRPC
4. Apply patch via gRPC exec
5. Write and execute eval script via gRPC
6. Collect test output
7. Close gRPC connection

## Implementation Steps

### Phase 1: Infrastructure Setup

1. **Install Serverless Devs**
   ```bash
   npm install -g @serverless-devs/s
   ```

2. **Configure Credentials**
   ```bash
   s config add
   ```

3. **Push Base Image to ACR**
   ```bash
   docker pull swebench/sweb.eval.x86_64.sympy_1776_sympy-20590:latest
   docker tag swebench/sweb.eval.x86_64.sympy_1776_sympy-20590:latest registry.cn-shanghai.aliyuncs.com/muwu/swebench-eval:latest
   docker push registry.cn-shanghai.aliyuncs.com/muwu/swebench-eval:latest
   ```

4. **Deploy Function**
   ```bash
   s deploy
   ```

### Phase 2: Build Proto Files

```bash
cd swebench/harness/aliyun_fc_eval
pip install grpcio-tools

# Generate Python gRPC code
python -m grpc_tools.protoc -I./proto \
    --python_out=. --grpc_python_out=. \
    ./proto/container.proto
```

### Phase 3: Client-Side Implementation

1. Implement `AliyunFCRuntime` class with gRPC client
2. Implement `run_instance_aliyun()` and `run_instances_aliyun()`
3. Add `--aliyun-fc` CLI flag to `run_evaluation.py`

## TODO: Steps to Run Gold Test on Aliyun FC

### 1. Create gRPC Server in FC Container

- [x] Write `main.go` with gRPC server that implements `ContainerSession` bi-directional streaming
- [x] Implement `HealthCheck` method
- [x] Implement exec command handler (run shell command, stream output)
- [x] Implement write file handler
- [x] Implement read file handler
- [x] Create `go.mod` with dependencies
- [x] Build Go binary: `GOOS=linux GOARCH=amd64 go build -o fc_server`
- [x] Test gRPC server locally

### 2. Create Docker Image

- [x] Update Dockerfile to copy `fc_server` binary
- [x] Build Docker image locally and test
- [x] Push image to ACR: `registry.cn-shanghai.aliyuncs.com/muwu/swebench-eval:fc-go`

### 3. Deploy FC Function

- [x] Write `s.yaml` for FC 3.0 custom-container runtime
- [x] Configure custom-container to use ACR image
- [x] Configure `customContainerConfig.port: 8089` for gRPC
- [x] Deploy: `s deploy`
- [x] Test gRPC server with `grpcurl` or Go client

**FC Endpoint**: `swebench-eval-xxx.cn-shanghai.fcapp.run:8089`

### 4. Implement Python gRPC Client

- [x] Write `aliyun_fc_runtime.py`
- [x] Implement `health_check()` method
- [x] Implement `write_file()` method using stream
- [x] Implement `exec()` method using stream
- [x] Implement `read_file()` method using stream
- [x] Implement connection pooling/context management

### 5. Integrate with SWE-bench

- [x] Add `--aliyun-fc` CLI flag
- [x] Add `--fc-endpoint` flag
- [x] Implement `run_instance_aliyun()` to use `AliyunFCRuntime`
- [x] Implement gold test workflow: write patch → apply patch → run eval → get results
- [ ] Test with single instance: `sympy__sympy-20590`

### 6. Verify Gold Test

- [x] Run gold test on Aliyun FC
- [x] Compare results with local Docker gold test
- [x] Debug any issues

## Detailed Evaluation Steps (Gold Test Example)

### Standard Docker Gold Test Workflow

```
┌─────────────────────────────────────────────────────────────┐
│ Step 1: Load predictions (gold = actual patch from dataset)│
└─────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────┐
│ Step 2: (Skip) Image build - image already exists           │
└─────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────┐
│ Step 3: Run instance evaluation                             │
└─────────────────────────────────────────────────────────────┘
         ↓
   ┌────────────────────────────────────────────────────┐
   │ 3.1 Create container (from existing image)         │
   │ 3.2 Copy patch to container                        │
   │ 3.3 Apply patch                                    │
   │ 3.4 Copy eval script to container                  │
   │ 3.5 Run evaluation                                 │
   │ 3.6 Grade results                                  │
   │ 3.7 Cleanup container                              │
   └────────────────────────────────────────────────────┘
```

### Aliyun FC Gold Test Workflow

The Aliyun FC evaluation uses a pre-deployed function with the same pre-built image:

```
┌─────────────────────────────────────────────────────────────┐
│ Step 1: Load predictions                                    │
└─────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────┐
│ Step 2: (Skip) Image build/FC deploy - already done        │
└─────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────┐
│ Step 3: Run instance evaluation via FC                      │
└─────────────────────────────────────────────────────────────┘
         ↓
   ┌────────────────────────────────────────────────────┐
   │ 3.1 Connect to gRPC endpoint (may cold start)      │
   │ 3.2 Write patch to container                      │
   │ 3.3 Apply patch                                   │
   │ 3.4 Write eval script to container                │
   │ 3.5 Run evaluation                                │
   │ 3.6 Grade results                                 │
   │ 3.7 Close gRPC connection                         │
   └────────────────────────────────────────────────────┘
```

### Docker Operations → Aliyun FC Mapping

| Docker Operation | Standard SWE-bench | Aliyun FC (gRPC) |
|------------------|-------------------|------------------|
| **Run container** | `client.containers.create()` + `.start()` | Connect to gRPC endpoint |
| **Copy files** | `copy_to_container()` | `runtime.write_file()` |
| **Execute commands** | `container.exec_run()` | `runtime.exec()` |
| **Health check** | N/A | `runtime.health_check()` |
| **Cleanup container** | `cleanup_container()` | Close gRPC channel |

### Communication Flow (gRPC Streaming)

```
Host (Python)                          Aliyun FC Container (Go)
     │                                        │
     │  1. gRPC connect (persistent)          │
     ├───────────────────────────────────────▶│
     │                                        │
     ├───────────────────────────────────────▶│  WriteFile("/tmp/patch.diff")
     │◀───────────────────────────────────────┤
     │                                        │
     ├───────────────────────────────────────▶│  ExecCommand("git apply...")
     │◀───────────────────────────────────────│
     │                                        │
     ├───────────────────────────────────────▶│  WriteFile("/tmp/eval.sh")
     │  ... (multiple requests)              │  ExecCommand("bash eval.sh")
     │                                        │
     │  4. Close connection                  │
     ├───────────────────────────────────────▶│
```

## Configuration

### Function Configuration (s.yaml)

```yaml
edition: 3.0.0
name: swebench-evaluation
access: "default"

vars:
  region: "cn-shanghai"
  acr_image: "registry.cn-shanghai.aliyuncs.com/muwu/swebench-eval:fc-go"

resources:
  swebench-eval:
    component: fc3
    props:
      region: ${vars.region}
      functionName: "swebench-eval"
      description: "SWE-bench evaluation using custom container"
      runtime: "custom-container"
      memorySize: 16384
      timeout: 1800
      customContainerConfig:
        port: 8089
        image: ${vars.acr_image}
        command:
          - /fc_server
        args: ""
      environmentVariables:
        PYTHONPATH: /testbed
      instanceConcurrency: 1
      instanceType: e1
      triggers:
        - triggerName: httpTrigger
          triggerType: http
          triggerConfig:
            authType: anonymous
            methods:
              - GET
              - POST
            path: /*
            qualifier: LATEST
```

## Challenges and Solutions

### 1. Stateful Execution

**Challenge**: FC is stateless, but evaluation needs to persist state between steps.

**Solution**: Use gRPC bi-directional streaming - container stays alive between operations.

### 2. Large Output Files

**Challenge**: Test output can be very large (hundreds of MB).

**Solution**: Stream output via gRPC in chunks.

### 3. Cold Start

**Challenge**: FC cold starts can be slow.

**Solution**: gRPC connection triggers container start once; subsequent operations reuse same container.

### 4. Parallel Execution

**Challenge**: Need to run multiple evaluations in parallel.

**Solution**: Create multiple FC function instances (one per parallel evaluation).

## File Structure

```
swebench/harness/aliyun_fc_eval/
├── aliyun_fc_runtime.py   # Python gRPC client
├── run_evaluation_aliyun.py  # Main orchestration
├── s.yaml                 # Serverless Devs configuration
├── main.go                # Go gRPC server (runs in FC container)
├── go.mod                 # Go module file
├── Dockerfile             # Container image
├── proto/
│   ├── container.proto    # gRPC service definition
│   ├── container.pb.go    # Generated Go code
│   └── container_grpc.pb.go
```

## gRPC Proto Definition

```protobuf
// proto/container.proto
syntax = "proto3";

package swebench;

service ContainerService {
    rpc HealthCheck(HealthCheckRequest) returns (HealthCheckResponse);
    rpc ContainerSession(stream SessionRequest) returns (stream SessionResponse);
}

message HealthCheckRequest {}
message HealthCheckResponse {
    bool healthy = 1;
    string message = 2;
}

message SessionRequest {
    string request_type = 1;  // "exec", "write_file", "read_file"
    string command = 2;
    string workdir = 3;
    string path = 4;
    bytes content = 5;
    string mode = 6;
}

message SessionResponse {
    bool success = 1;
    string error = 2;
    bytes output = 3;
    int32 return_code = 4;
    bool eof = 5;
    bytes content = 6;
}
```

## Testing with Gold Predictions

```bash
# Deploy the function
cd swebench/harness/aliyun_fc_eval
s deploy

# Run evaluation with gold predictions
python3 -m swebench.harness.run_evaluation \
    -p gold \
    --max_workers 1 \
    -i sympy__sympy-20590 \
    -id validate-gold-fc \
    --aliyun-fc true \
    --fc-endpoint <http-trigger-url-from-deploy-result>:8089
```

## Cost Estimation

Based on Aliyun FC pricing (cn-shanghai region):

- **Compute**: ~¥0.0002 per GB-second × 16GB × 1800s = ~¥5.76 per instance
- **Invocation**: ~¥0.2 per 1M invocations

For 100 instances: ~¥576 (approximately $80 USD)

Note: Actual costs may vary based on actual execution time and region.
