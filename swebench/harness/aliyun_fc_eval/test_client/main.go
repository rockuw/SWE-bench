package main

import (
	"context"
	"log"
	"time"

	"google.golang.org/grpc"
	"google.golang.org/grpc/credentials/insecure"
	pb "swebench/harness/aliyun_fc_eval/proto"
)

func main() {
	endpoint := "swebench-eval.fcv3.1237050315505682.cn-shanghai.fc.devsapp.net:8089"

	// Create connection
	conn, err := grpc.NewClient(endpoint,
		grpc.WithTransportCredentials(insecure.NewCredentials()),
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
