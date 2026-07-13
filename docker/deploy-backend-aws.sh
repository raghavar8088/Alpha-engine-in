#!/usr/bin/env bash
# Deploy the TradingAI backend to AWS ECS Fargate, behind a public ALB.
# Run from the TradingAI/ repo root. Requires: aws CLI v2 configured
# (`aws configure`), Docker Desktop running, and the secrets from
# create-secrets-aws.sh already created.
#
# Idempotent: safe to re-run. Steps that already exist are skipped/updated
# rather than failing.
set -euo pipefail

REGION="ap-south-1"                     # Mumbai — lowest latency to NSE/Dhan
REPO="tradingai-backend"
CLUSTER="tradingai-cluster"
SERVICE="tradingai-backend-svc"
FAMILY="tradingai-backend"
CONTAINER_NAME="backend"
CONTAINER_PORT=8080

ACCOUNT_ID="$(aws sts get-caller-identity --query Account --output text --region "$REGION")"
IMAGE_URI="${ACCOUNT_ID}.dkr.ecr.${REGION}.amazonaws.com/${REPO}"

echo "== Account ${ACCOUNT_ID} / region ${REGION} =="

# ---------------------------------------------------------------------------
# 1. One-time: ECR repo
# ---------------------------------------------------------------------------
aws ecr describe-repositories --repository-names "$REPO" --region "$REGION" >/dev/null 2>&1 \
  || aws ecr create-repository --repository-name "$REPO" --region "$REGION"

aws ecr get-login-password --region "$REGION" \
  | docker login --username AWS --password-stdin "${ACCOUNT_ID}.dkr.ecr.${REGION}.amazonaws.com"

# ---------------------------------------------------------------------------
# 2. One-time: CloudWatch log group
# ---------------------------------------------------------------------------
LOG_GROUP="/ecs/${FAMILY}"
aws logs describe-log-groups --log-group-name-prefix "$LOG_GROUP" --region "$REGION" \
  --query "logGroups[?logGroupName=='${LOG_GROUP}']" --output text | grep -q "$LOG_GROUP" \
  || aws logs create-log-group --log-group-name "$LOG_GROUP" --region "$REGION"

# ---------------------------------------------------------------------------
# 3. One-time: ECS task execution role (pulls image, writes logs, reads secrets)
# ---------------------------------------------------------------------------
EXEC_ROLE_NAME="tradingaiEcsExecutionRole"
if ! aws iam get-role --role-name "$EXEC_ROLE_NAME" >/dev/null 2>&1; then
  aws iam create-role --role-name "$EXEC_ROLE_NAME" --assume-role-policy-document '{
    "Version": "2012-10-17",
    "Statement": [{"Effect": "Allow", "Principal": {"Service": "ecs-tasks.amazonaws.com"}, "Action": "sts:AssumeRole"}]
  }'
  aws iam attach-role-policy --role-name "$EXEC_ROLE_NAME" \
    --policy-arn arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy
  aws iam put-role-policy --role-name "$EXEC_ROLE_NAME" --policy-name tradingaiSecretsAccess --policy-document '{
    "Version": "2012-10-17",
    "Statement": [{"Effect": "Allow", "Action": "secretsmanager:GetSecretValue", "Resource": "arn:aws:secretsmanager:'"$REGION"':'"$ACCOUNT_ID"':secret:tradingai/*"}]
  }'
  echo "Created ${EXEC_ROLE_NAME} — waiting 10s for IAM propagation..."
  sleep 10
fi
EXEC_ROLE_ARN="arn:aws:iam::${ACCOUNT_ID}:role/${EXEC_ROLE_NAME}"

# ---------------------------------------------------------------------------
# 4. One-time: ECS cluster
# ---------------------------------------------------------------------------
aws ecs describe-clusters --clusters "$CLUSTER" --region "$REGION" \
  --query "clusters[?status=='ACTIVE']" --output text | grep -q ACTIVE \
  || aws ecs create-cluster --cluster-name "$CLUSTER" --region "$REGION"

# ---------------------------------------------------------------------------
# 5. One-time: default VPC, public subnets, security groups, ALB
# ---------------------------------------------------------------------------
VPC_ID="$(aws ec2 describe-vpcs --filters Name=isDefault,Values=true --region "$REGION" --query 'Vpcs[0].VpcId' --output text)"
SUBNET_IDS="$(aws ec2 describe-subnets --filters Name=vpc-id,Values="$VPC_ID" --region "$REGION" --query 'Subnets[].SubnetId' --output text | tr '\t' ',')"
echo "VPC ${VPC_ID}, subnets ${SUBNET_IDS}"

ALB_SG_NAME="tradingai-alb-sg"
ALB_SG_ID="$(aws ec2 describe-security-groups --filters Name=group-name,Values="$ALB_SG_NAME" Name=vpc-id,Values="$VPC_ID" --region "$REGION" --query 'SecurityGroups[0].GroupId' --output text 2>/dev/null || echo "None")"
if [ "$ALB_SG_ID" = "None" ]; then
  ALB_SG_ID="$(aws ec2 create-security-group --group-name "$ALB_SG_NAME" --description "TradingAI ALB" --vpc-id "$VPC_ID" --region "$REGION" --query 'GroupId' --output text)"
  aws ec2 authorize-security-group-ingress --group-id "$ALB_SG_ID" --protocol tcp --port 80 --cidr 0.0.0.0/0 --region "$REGION"
fi

TASK_SG_NAME="tradingai-task-sg"
TASK_SG_ID="$(aws ec2 describe-security-groups --filters Name=group-name,Values="$TASK_SG_NAME" Name=vpc-id,Values="$VPC_ID" --region "$REGION" --query 'SecurityGroups[0].GroupId' --output text 2>/dev/null || echo "None")"
if [ "$TASK_SG_ID" = "None" ]; then
  TASK_SG_ID="$(aws ec2 create-security-group --group-name "$TASK_SG_NAME" --description "TradingAI backend task" --vpc-id "$VPC_ID" --region "$REGION" --query 'GroupId' --output text)"
  aws ec2 authorize-security-group-ingress --group-id "$TASK_SG_ID" --protocol tcp --port "$CONTAINER_PORT" --source-group "$ALB_SG_ID" --region "$REGION"
fi

TG_NAME="tradingai-backend-tg"
TG_ARN="$(aws elbv2 describe-target-groups --names "$TG_NAME" --region "$REGION" --query 'TargetGroups[0].TargetGroupArn' --output text 2>/dev/null || echo "None")"
if [ "$TG_ARN" = "None" ]; then
  TG_ARN="$(aws elbv2 create-target-group --name "$TG_NAME" --protocol HTTP --port "$CONTAINER_PORT" \
    --vpc-id "$VPC_ID" --target-type ip --health-check-path /health --region "$REGION" \
    --query 'TargetGroups[0].TargetGroupArn' --output text)"
fi

ALB_NAME="tradingai-backend-alb"
ALB_ARN="$(aws elbv2 describe-load-balancers --names "$ALB_NAME" --region "$REGION" --query 'LoadBalancers[0].LoadBalancerArn' --output text 2>/dev/null || echo "None")"
if [ "$ALB_ARN" = "None" ]; then
  ALB_ARN="$(aws elbv2 create-load-balancer --name "$ALB_NAME" --subnets ${SUBNET_IDS//,/ } \
    --security-groups "$ALB_SG_ID" --scheme internet-facing --type application --region "$REGION" \
    --query 'LoadBalancers[0].LoadBalancerArn' --output text)"
  aws elbv2 create-listener --load-balancer-arn "$ALB_ARN" --protocol HTTP --port 80 \
    --default-actions Type=forward,TargetGroupArn="$TG_ARN" --region "$REGION"
fi
ALB_DNS="$(aws elbv2 describe-load-balancers --load-balancer-arns "$ALB_ARN" --region "$REGION" --query 'LoadBalancers[0].DNSName' --output text)"

# ---------------------------------------------------------------------------
# 6. Build + push image (build context = repo root; see Dockerfile.backend)
# ---------------------------------------------------------------------------
docker build -f docker/Dockerfile.backend -t "${IMAGE_URI}:latest" .
docker push "${IMAGE_URI}:latest"

# ---------------------------------------------------------------------------
# 7. Register task definition, wiring secrets from Secrets Manager by ARN
# ---------------------------------------------------------------------------
secret_arn() { aws secretsmanager describe-secret --secret-id "$1" --region "$REGION" --query ARN --output text; }

cat > /tmp/tradingai-task-def.json <<EOF
{
  "family": "${FAMILY}",
  "networkMode": "awsvpc",
  "requiresCompatibilities": ["FARGATE"],
  "cpu": "512",
  "memory": "1024",
  "executionRoleArn": "${EXEC_ROLE_ARN}",
  "containerDefinitions": [{
    "name": "${CONTAINER_NAME}",
    "image": "${IMAGE_URI}:latest",
    "portMappings": [{"containerPort": ${CONTAINER_PORT}, "protocol": "tcp"}],
    "environment": [
      {"name": "ENABLE_LIVE_TRADING", "value": "false"},
      {"name": "DHAN_BASE_URL", "value": "https://api.dhan.co/v2"}
    ],
    "secrets": [
      {"name": "MONGO_URL", "valueFrom": "$(secret_arn tradingai/mongo-url)"},
      {"name": "BROKER_ENCRYPTION_KEY", "valueFrom": "$(secret_arn tradingai/broker-encryption-key)"},
      {"name": "GROQ_API_KEY", "valueFrom": "$(secret_arn tradingai/groq-key)"},
      {"name": "DHAN_CLIENT_ID", "valueFrom": "$(secret_arn tradingai/dhan-client-id)"},
      {"name": "DHAN_PIN", "valueFrom": "$(secret_arn tradingai/dhan-pin)"},
      {"name": "DHAN_TOTP_SECRET", "valueFrom": "$(secret_arn tradingai/dhan-totp-secret)"}
    ],
    "logConfiguration": {
      "logDriver": "awslogs",
      "options": {
        "awslogs-group": "${LOG_GROUP}",
        "awslogs-region": "${REGION}",
        "awslogs-stream-prefix": "backend"
      }
    }
  }]
}
EOF
aws ecs register-task-definition --cli-input-json file:///tmp/tradingai-task-def.json --region "$REGION" >/dev/null
rm -f /tmp/tradingai-task-def.json

# ---------------------------------------------------------------------------
# 8. Create or update the ECS service
# ---------------------------------------------------------------------------
if aws ecs describe-services --cluster "$CLUSTER" --services "$SERVICE" --region "$REGION" \
    --query "services[?status=='ACTIVE']" --output text | grep -q ACTIVE; then
  aws ecs update-service --cluster "$CLUSTER" --service "$SERVICE" \
    --task-definition "$FAMILY" --force-new-deployment --region "$REGION" >/dev/null
  echo "Updated existing service — rolling deploy in progress."
else
  aws ecs create-service --cluster "$CLUSTER" --service-name "$SERVICE" \
    --task-definition "$FAMILY" --desired-count 1 --launch-type FARGATE \
    --network-configuration "awsvpcConfiguration={subnets=[${SUBNET_IDS}],securityGroups=[${TASK_SG_ID}],assignPublicIp=ENABLED}" \
    --load-balancers "targetGroupArn=${TG_ARN},containerName=${CONTAINER_NAME},containerPort=${CONTAINER_PORT}" \
    --region "$REGION" >/dev/null
  echo "Created new service."
fi

echo ""
echo "Deployed. Backend will be reachable at: http://${ALB_DNS}"
echo "(HTTP only for now — add an ACM cert + HTTPS listener once you point a domain at this ALB.)"
echo "Health check: http://${ALB_DNS}/health"
