package main

import (
	"context"
	"crypto/tls"
	"log"
	"time"

	pb "swebench/harness/aliyun_fc_eval/proto"

	"google.golang.org/grpc"
	"google.golang.org/grpc/credentials"
)

func main() {
	endpoint := "swebench-eval-rvtjlikkuy.cn-shanghai.fcapp.run:8089"

	// Create connection with HTTP/2 support
	conn, err := grpc.Dial(endpoint,
		grpc.WithTransportCredentials(credentials.NewTLS(&tls.Config{
			InsecureSkipVerify: true,
		})),
		grpc.WithTimeout(10*time.Second),
	)
	if err != nil {
		log.Fatalf("Failed to connect: %v", err)
	}
	defer conn.Close()

	client := pb.NewContainerServiceClient(conn)

	// Test HealthCheck
	ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
	defer cancel()

	resp, err := client.HealthCheck(ctx, &pb.HealthCheckRequest{})
	if err != nil {
		log.Fatalf("HealthCheck failed: %v", err)
	}

	log.Printf("HealthCheck Response: healthy=%v, message=%s", resp.Healthy, resp.Message)
}
