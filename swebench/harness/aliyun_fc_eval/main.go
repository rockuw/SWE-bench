package main

import (
	"context"
	"encoding/base64"
	"io"
	"log"
	"net"
	"os"
	"os/exec"
	"path/filepath"

	"google.golang.org/grpc"
	pb "swebench/harness/aliyun_fc_eval/proto"
)

const (
	port        = ":8089"
	testbedPath = "/testbed"
	tmpPath     = "/tmp"
)

type server struct {
	pb.UnimplementedContainerServiceServer
}

func (s *server) HealthCheck(ctx context.Context, req *pb.HealthCheckRequest) (*pb.HealthCheckResponse, error) {
	return &pb.HealthCheckResponse{
		Healthy: true,
		Message: "Container is running",
	}, nil
}

func (s *server) ContainerSession(stream pb.ContainerService_ContainerSessionServer) error {
	for {
		req, err := stream.Recv()
		if err == io.EOF {
			return nil
		}
		if err != nil {
			return err
		}

		switch req.RequestType {
		case "exec":
			s.handleExec(req, stream)
		case "write_file":
			s.handleWriteFile(req, stream)
		case "read_file":
			s.handleReadFile(req, stream)
		default:
			stream.Send(&pb.SessionResponse{
				Success: false,
				Error:   "unknown request type: " + req.RequestType,
			})
		}
	}
}

func (s *server) handleExec(req *pb.SessionRequest, stream pb.ContainerService_ContainerSessionServer) {
	workdir := req.Workdir
	if workdir == "" {
		workdir = testbedPath
	}

	cmd := exec.Command("bash", "-c", req.Command)
	cmd.Dir = workdir
	cmd.Stdout = &streamWriter{stream}
	cmd.Stderr = cmd.Stdout

	cmd.Run()
	stream.Send(&pb.SessionResponse{
		ReturnCode: int32(cmd.ProcessState.ExitCode()),
		Eof:        true,
	})
}

func (s *server) handleWriteFile(req *pb.SessionRequest, stream pb.ContainerService_ContainerSessionServer) {
	// Ensure directory exists
	dir := filepath.Dir(req.Path)
	if err := os.MkdirAll(dir, 0755); err != nil {
		stream.Send(&pb.SessionResponse{
			Success: false,
			Error:   "failed to create directory: " + err.Error(),
		})
		return
	}

	var content []byte
	if req.Mode == "binary" {
		content, _ = base64.StdEncoding.DecodeString(string(req.Content))
	} else {
		content = req.Content
	}

	if err := os.WriteFile(req.Path, content, 0644); err != nil {
		stream.Send(&pb.SessionResponse{
			Success: false,
			Error:   "failed to write file: " + err.Error(),
		})
		return
	}

	stream.Send(&pb.SessionResponse{
		Success: true,
	})
}

func (s *server) handleReadFile(req *pb.SessionRequest, stream pb.ContainerService_ContainerSessionServer) {
	content, err := os.ReadFile(req.Path)
	if err != nil {
		stream.Send(&pb.SessionResponse{
			Success: false,
			Error:   "failed to read file: " + err.Error(),
		})
		return
	}

	stream.Send(&pb.SessionResponse{
		Success: true,
		Content: content,
	})
}

type streamWriter struct {
	stream pb.ContainerService_ContainerSessionServer
}

func (w *streamWriter) Write(p []byte) (n int, err error) {
	err = w.stream.Send(&pb.SessionResponse{
		Output: p,
		Eof:    false,
	})
	if err != nil {
		return 0, err
	}
	return len(p), nil
}

func main() {
	// Create /tmp directory
	os.MkdirAll(tmpPath, 0755)

	lis, err := net.Listen("tcp", port)
	if err != nil {
		log.Fatalf("failed to listen: %v", err)
	}

	s := grpc.NewServer()
	pb.RegisterContainerServiceServer(s, &server{})

	log.Printf("gRPC server listening on %s", port)
	if err := s.Serve(lis); err != nil {
		log.Fatalf("failed to serve: %v", err)
	}
}
