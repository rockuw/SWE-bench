package main

import (
	"context"
	"encoding/base64"
	"encoding/json"
	"fmt"
	"io"
	"log"
	"net/http"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"time"
)

const (
	port              = ":9000"
	testbedPath       = "/testbed"
	tmpPath           = "/tmp"
)

var (
	initialized  bool
	testbedPath_ string
	repoPath     string
)

// Request/Response types
type InitializeRequest struct {
	Repo        string `json:"repo"`
	BaseCommit  string `json:"base_commit"`
	InstanceID  string `json:"instance_id"`
}

type InitializeResponse struct {
	Success    bool   `json:"success"`
	TestbedPath string `json:"testbed_path,omitempty"`
	Error      string `json:"error,omitempty"`
}

type ExecRequest struct {
	Command string `json:"command"`
	Workdir string `json:"workdir"`
}

type ExecResponse struct {
	Output     string `json:"output"`
	ReturnCode int    `json:"return_code"`
	EOF        bool   `json:"eof"`
	Error      string `json:"error,omitempty"`
}

type WriteRequest struct {
	Path    string `json:"path"`
	Content string `json:"content"`
	Mode    string `json:"mode"` // "text" or "binary"
}

type WriteResponse struct {
	Success bool   `json:"success"`
	Error   string `json:"error,omitempty"`
}

type EvalRequest struct {
	InstanceID string `json:"instance_id"`
	Patch      string `json:"patch"`
	EvalScript string `json:"eval_script"`
	Timeout    int    `json:"timeout"`
}

type EvalResponse struct {
	TestOutput string `json:"test_output"`
	ReturnCode int    `json:"return_code"`
	GitDiff    string `json:"git_diff"`
	Error      string `json:"error,omitempty"`
}

type HealthResponse struct {
	Status  string `json:"status"`
	Message string `json:"message"`
}

// Handlers
func healthCheckHandler(w http.ResponseWriter, r *http.Request) {
	json.NewEncoder(w).Encode(HealthResponse{
		Status:  "ok",
		Message: "Container is running",
	})
}

func initializeHandler(w http.ResponseWriter, r *http.Request) {
	var req InitializeRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		json.NewEncoder(w).Encode(InitializeResponse{
			Success: false,
			Error:   err.Error(),
		})
		return
	}

	log.Printf("Initializing testbed for %s, repo: %s, commit: %s", req.InstanceID, req.Repo, req.BaseCommit)

	// Create testbed directory
	if err := os.MkdirAll(testbedPath, 0755); err != nil {
		json.NewEncoder(w).Encode(InitializeResponse{
			Success: false,
			Error:   fmt.Sprintf("Failed to create testbed dir: %v", err),
		})
		return
	}

	repoName := strings.Split(req.Repo, "/")[1]
	repoPath = filepath.Join(testbedPath, repoName)

	// Clone repository if not exists
	if _, err := os.Stat(repoPath); os.IsNotExist(err) {
		log.Printf("Cloning repository %s...", req.Repo)
		cmd := exec.Command("git", "clone", "--depth", "1", fmt.Sprintf("https://github.com/%s.git", req.Repo), repoPath)
		cmd.Dir = testbedPath
		output, err := cmd.CombinedOutput()
		if err != nil {
			json.NewEncoder(w).Encode(InitializeResponse{
				Success: false,
				Error:   fmt.Sprintf("Failed to clone repo: %v, output: %s", err, string(output)),
			})
			return
		}
	}

	// Checkout to specific commit
	log.Printf("Checking out to %s...", req.BaseCommit)
	cmd := exec.Command("git", "checkout", req.BaseCommit)
	cmd.Dir = repoPath
	output, err := cmd.CombinedOutput()
	if err != nil {
		// Try with fetch
		cmd = exec.Command("git", "fetch", "origin", req.BaseCommit, "&&", "git", "checkout", req.BaseCommit)
		cmd.Dir = repoPath
		output, err = cmd.CombinedOutput()
		if err != nil {
			json.NewEncoder(w).Encode(InitializeResponse{
				Success: false,
				Error:   fmt.Sprintf("Failed to checkout: %v, output: %s", err, string(output)),
			})
			return
		}
	}

	initialized = true
	testbedPath_ = repoPath

	json.NewEncoder(w).Encode(InitializeResponse{
		Success:    true,
		TestbedPath: repoPath,
	})
}

func execHandler(w http.ResponseWriter, r *http.Request) {
	var req ExecRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		json.NewEncoder(w).Encode(ExecResponse{
			ReturnCode: -1,
			Error:      err.Error(),
		})
		return
	}

	workdir := req.Workdir
	if workdir == "" {
		workdir = testbedPath_
	}

	// Run command
	ctx, cancel := context.WithTimeout(context.Background(), 3600*time.Second)
	defer cancel()

	cmd := exec.CommandContext(ctx, "bash", "-c", req.Command)
	cmd.Dir = workdir

	output, _ := cmd.CombinedOutput()

	json.NewEncoder(w).Encode(ExecResponse{
		Output:     string(output),
		ReturnCode: cmd.ProcessState.ExitCode(),
		EOF:       true,
	})
}

func writeFileHandler(w http.ResponseWriter, r *http.Request) {
	var req WriteRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		json.NewEncoder(w).Encode(WriteResponse{
			Success: false,
			Error:   err.Error(),
		})
		return
	}

	// Ensure directory exists
	dir := filepath.Dir(req.Path)
	if err := os.MkdirAll(dir, 0755); err != nil {
		json.NewEncoder(w).Encode(WriteResponse{
			Success: false,
			Error:   fmt.Sprintf("Failed to create directory: %v", err),
		})
		return
	}

	var content []byte
	if req.Mode == "binary" {
		content, _ = base64.StdEncoding.DecodeString(req.Content)
	} else {
		content = []byte(req.Content)
	}

	if err := os.WriteFile(req.Path, content, 0644); err != nil {
		json.NewEncoder(w).Encode(WriteResponse{
			Success: false,
			Error:   fmt.Sprintf("Failed to write file: %v", err),
		})
		return
	}

	json.NewEncoder(w).Encode(WriteResponse{
		Success: true,
	})
}

func runEvaluationHandler(w http.ResponseWriter, r *http.Request) {
	var req EvalRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		json.NewEncoder(w).Encode(EvalResponse{
			Error: err.Error(),
		})
		return
	}

	timeout := req.Timeout
	if timeout == 0 {
		timeout = 1800
	}

	log.Printf("Running evaluation for %s", req.InstanceID)

	// Write patch file
	patchPath := filepath.Join(tmpPath, "patch.diff")
	if err := os.WriteFile(patchPath, []byte(req.Patch), 0644); err != nil {
		json.NewEncoder(w).Encode(EvalResponse{
			Error: fmt.Sprintf("Failed to write patch: %v", err),
		})
		return
	}

	// Apply patch
	cmd := exec.Command("git", "apply", patchPath)
	cmd.Dir = repoPath
	cmd.Run()

	if cmd.ProcessState.ExitCode() != 0 {
		// Try patch command
		cmd = exec.Command("patch", "--batch", "--fuzz=5", "-p1", "-i", patchPath)
		cmd.Dir = repoPath
		cmd.Run()
	}

	// Write eval script
	evalPath := filepath.Join(tmpPath, "eval.sh")
	if err := os.WriteFile(evalPath, []byte(req.EvalScript), 0755); err != nil {
		json.NewEncoder(w).Encode(EvalResponse{
			Error: fmt.Sprintf("Failed to write eval script: %v", err),
		})
		return
	}

	// Run evaluation
	ctx, cancel := context.WithTimeout(context.Background(), time.Duration(timeout)*time.Second)
	defer cancel()

	cmd = exec.CommandContext(ctx, "bash", evalPath)
	cmd.Dir = repoPath
	evalOutput, _ := cmd.CombinedOutput()

	// Get git diff
	cmd = exec.Command("git", "diff")
	cmd.Dir = repoPath
	gitDiff, _ := cmd.CombinedOutput()

	json.NewEncoder(w).Encode(EvalResponse{
		TestOutput: string(evalOutput),
		ReturnCode: cmd.ProcessState.ExitCode(),
		GitDiff:    string(gitDiff),
	})
}

// InvokeHandler handles /invoke path for s CLI invocations
// Routes to appropriate handler based on payload keys
func invokeHandler(w http.ResponseWriter, r *http.Request) {
	log.Printf("Received invoke request: %s %s", r.Method, r.URL.Path)
	body, _ := io.ReadAll(r.Body)
	log.Printf("Raw Body: %s", string(body))

	// Decode base64 if needed (s invoke sends base64 encoded event)
	decodedBody := body
	if len(body) > 0 {
		decoded, err := base64.StdEncoding.DecodeString(string(body))
		if err == nil {
			decodedBody = decoded
			log.Printf("Decoded body: %s", string(decodedBody))
		}
	}

	// Try to parse the body as JSON
	var req map[string]interface{}
	if err := json.Unmarshal(decodedBody, &req); err != nil {
		json.NewEncoder(w).Encode(map[string]string{
			"error": "Invalid JSON: " + err.Error(),
		})
		return
	}

	// Check which handler to route to based on keys in the payload
	if _, hasCommand := req["command"]; hasCommand {
		// Reconstruct ExecRequest and call execHandler
		execReq := ExecRequest{
			Command: req["command"].(string),
		}
		if w, ok := req["workdir"]; ok {
			execReq.Workdir = w.(string)
		}
		// Create a new request with the exec body
		execReqJSON, _ := json.Marshal(execReq)
		r.Body = io.NopCloser(strings.NewReader(string(execReqJSON)))
		r.ContentLength = int64(len(execReqJSON))
		execHandler(w, r)
		return
	}

	if _, hasPath := req["path"]; hasPath {
		// Write file request
		writeFileHandler(w, r)
		return
	}

	if _, hasRepo := req["repo"]; hasRepo {
		// Initialize request
		initializeHandler(w, r)
		return
	}

	if _, hasPatch := req["patch"]; hasPatch {
		// Run evaluation request
		runEvaluationHandler(w, r)
		return
	}

	// Default to health check
	healthCheckHandler(w, r)
}

func main() {
	// Create /tmp directory
	os.MkdirAll(tmpPath, 0755)

	// Setup routes
	http.HandleFunc("/", func(w http.ResponseWriter, r *http.Request) {
		log.Printf("Received request: %s %s", r.Method, r.URL.Path)
		body, _ := io.ReadAll(r.Body)
		log.Printf("Body: %s", string(body))
		fmt.Fprintf(w, "FC Server running. Path: %s, Body: %s\n", r.URL.Path, string(body))
	})
	http.HandleFunc("/invoke", invokeHandler)
	http.HandleFunc("/health_check", healthCheckHandler)
	http.HandleFunc("/initialize", initializeHandler)
	http.HandleFunc("/exec", execHandler)
	http.HandleFunc("/write_file", writeFileHandler)
	http.HandleFunc("/run_evaluation", runEvaluationHandler)

	log.Printf("Starting server on port %s", port)
	if err := http.ListenAndServe(port, nil); err != nil {
		log.Fatalf("Server failed: %v", err)
	}
}
