# Infrastructure README

This folder contains notes and helper files for deploying the NASWA AI Apprenticeship Matcher to AWS using Amazon ECS Express Mode.

The current deployment flow is intentionally CLI-driven and lightweight. It supports two common workflows:

1. Creating a new ECS Express Mode service from scratch
2. Building, pushing, and deploying a new container image to an existing ECS Express Mode service

## Folder layout

Recommended structure:

```text
infra/
├── README.md
└── iam/
    ├── ecs-tasks-trust-policy.json
    ├── ecs-express-infrastructure-trust-policy.json
    └── bedrock-invoke-policy.json
```

The IAM JSON files are not secrets. They are safe to commit.

## Application assumptions

The app is a FastAPI app that listens on port `8000`.

The Docker image should start the app with something equivalent to:

```bash
uvicorn server:app --host 0.0.0.0 --port 8000
```

ECS Express Mode should be configured with:

```text
containerPort: 8000
health check path: /health
```

The app uses AWS Bedrock through the Strands Agents SDK. In ECS, the app should use an IAM task role for Bedrock access. Do not deploy AWS access keys as container environment variables.

The deployed container currently receives these non-secret runtime environment variables:

```
AWS_DEFAULT_REGION
AWS_REGION
CHAT_MODEL_NAME
SCORING_MODEL_NAME
```

The deployed container should not receive:

```
AWS_ACCESS_KEY_ID
AWS_SECRET_ACCESS_KEY
AWS_SESSION_TOKEN
AWS_PROFILE
```

## Local prerequisites

Install and configure:

```text
Docker
AWS CLI
AWS credentials/profile with permissions for ECR, ECS, IAM, and Bedrock
```

Confirm your AWS CLI identity:

```bash
aws sts get-caller-identity --profile your-profile-name
```

For AWS SSO profiles, run:

```bash
aws sso login --profile your-profile-name
```

Set common environment variables:

```bash
export AWS_PROFILE=your-profile-name
export AWS_REGION=us-east-1
export AWS_ACCOUNT_ID=$(aws sts get-caller-identity \
  --profile "$AWS_PROFILE" \
  --query Account \
  --output text)

export APP_NAME=naswa-ai-apprenticeship-matcher
export ECR_REPO=$APP_NAME
export IMAGE_TAG=latest
export IMAGE_URI="$AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com/$ECR_REPO:$IMAGE_TAG"
```

## Case 1: Create a new ECS Express Mode service

Use this flow when creating a brand new deployed application.

### 1. Create the ECR repository

Create the repository:

```bash
aws ecr create-repository \
  --repository-name "$ECR_REPO" \
  --region "$AWS_REGION" \
  --profile "$AWS_PROFILE"
```

If the repository already exists, this command will fail with a repository already exists error. That is okay; skip to the next step.

### 2. Log Docker in to ECR

```bash
aws ecr get-login-password \
  --region "$AWS_REGION" \
  --profile "$AWS_PROFILE" \
  | docker login \
    --username AWS \
    --password-stdin "$AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com"
```

### 3. Build and push the container image

For an Apple Silicon Mac, build for `linux/amd64` unless the ECS service is explicitly configured for ARM.

```bash
docker buildx build \
  --platform linux/amd64 \
  -t "$IMAGE_URI" \
  --push \
  .
```

Confirm the image exists:

```bash
aws ecr describe-images \
  --repository-name "$ECR_REPO" \
  --region "$AWS_REGION" \
  --profile "$AWS_PROFILE"
```

### 4. Create IAM roles

ECS Express Mode uses multiple IAM roles:

```text
Execution role:
  Used by ECS to pull the container image and write logs.

Infrastructure role:
  Used by ECS Express Mode to create/manage supporting infrastructure.

Task role:
  Used by the running application code inside the container.
  This app needs a task role so it can call AWS Bedrock.
```

Create the ECS task execution role:

```bash
aws iam create-role \
  --role-name ecsTaskExecutionRole \
  --assume-role-policy-document file://infra/iam/ecs-tasks-trust-policy.json \
  --profile "$AWS_PROFILE"
```

Attach the ECS task execution managed policy:

```bash
aws iam attach-role-policy \
  --role-name ecsTaskExecutionRole \
  --policy-arn arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy \
  --profile "$AWS_PROFILE"
```

Create the ECS Express infrastructure role:

```bash
aws iam create-role \
  --role-name ecsInfrastructureRoleForExpressServices \
  --assume-role-policy-document file://infra/iam/ecs-express-infrastructure-trust-policy.json \
  --profile "$AWS_PROFILE"
```

Attach the ECS Express infrastructure managed policy:

```bash
aws iam attach-role-policy \
  --role-name ecsInfrastructureRoleForExpressServices \
  --policy-arn arn:aws:iam::aws:policy/service-role/AmazonECSInfrastructureRoleforExpressGatewayServices \
  --profile "$AWS_PROFILE"
```

Create the application task role:

```bash
aws iam create-role \
  --role-name naswaMatcherTaskRole \
  --assume-role-policy-document file://infra/iam/ecs-tasks-trust-policy.json \
  --profile "$AWS_PROFILE"
```

Attach the Bedrock policy to the task role:

```bash
aws iam put-role-policy \
  --role-name naswaMatcherTaskRole \
  --policy-name BedrockInvokeModels \
  --policy-document file://infra/iam/bedrock-invoke-policy.json \
  --profile "$AWS_PROFILE"
```

If any role already exists, skip the corresponding `create-role` command and continue with the attach/get-role commands.

### 5. Export role ARNs

```bash
export EXECUTION_ROLE_ARN=$(aws iam get-role \
  --role-name ecsTaskExecutionRole \
  --query 'Role.Arn' \
  --output text \
  --profile "$AWS_PROFILE")

export INFRASTRUCTURE_ROLE_ARN=$(aws iam get-role \
  --role-name ecsInfrastructureRoleForExpressServices \
  --query 'Role.Arn' \
  --output text \
  --profile "$AWS_PROFILE")

export TASK_ROLE_ARN=$(aws iam get-role \
  --role-name naswaMatcherTaskRole \
  --query 'Role.Arn' \
  --output text \
  --profile "$AWS_PROFILE")
```

### 6. Create the ECS Express Mode service

```bash
aws ecs create-express-gateway-service \
  --service-name "$APP_NAME" \
  --execution-role-arn "$EXECUTION_ROLE_ARN" \
  --infrastructure-role-arn "$INFRASTRUCTURE_ROLE_ARN" \
  --task-role-arn "$TASK_ROLE_ARN" \
  --primary-container "{\"image\":\"$IMAGE_URI\",\"containerPort\":8000,\"environment\":[{\"name\":\"AWS_DEFAULT_REGION\",\"value\":\"$AWS_REGION\"},{\"name\":\"AWS_REGION\",\"value\":\"$AWS_REGION\"},{\"name\":\"CHAT_MODEL_NAME\",\"value\":\"sonnet-4.6\"},{\"name\":\"SCORING_MODEL_NAME\",\"value\":\"sonnet-4.6\"}]}" \
  --health-check-path "/health" \
  --monitor-resources \
  --region "$AWS_REGION" \
  --profile "$AWS_PROFILE"
```

If AWS reports that a role cannot be found or assumed, wait a minute and rerun the command. IAM role creation can take a short time to propagate.

When the command completes, save the returned service ARN:

```bash
export SERVICE_ARN=arn:aws:ecs:...
```

You can inspect the service later with:

```bash
aws ecs describe-express-gateway-service \
  --service-arn "$SERVICE_ARN" \
  --region "$AWS_REGION" \
  --profile "$AWS_PROFILE"
```

The deployed application URL should look similar to:

```text
https://<service-name>.ecs.<region>.on.aws/
```

## Case 2: Build, push, and deploy a new container image

Use this flow when the ECS Express Mode service already exists and you want to deploy a new version of the app.

### 1. Set environment variables

```bash
export AWS_PROFILE=your-profile-name
export AWS_REGION=us-east-1
export AWS_ACCOUNT_ID=$(aws sts get-caller-identity \
  --profile "$AWS_PROFILE" \
  --query Account \
  --output text)

export APP_NAME=naswa-ai-apprenticeship-matcher
export ECR_REPO=$APP_NAME

# Prefer a unique tag for deployments so it is easy to see what is running.
export IMAGE_TAG=$(git rev-parse --short HEAD)
export IMAGE_URI="$AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com/$ECR_REPO:$IMAGE_TAG"

# Use the service ARN returned by create-express-gateway-service.
export SERVICE_ARN=arn:aws:ecs:...
```

### 2. Log Docker in to ECR

```bash
aws ecr get-login-password \
  --region "$AWS_REGION" \
  --profile "$AWS_PROFILE" \
  | docker login \
    --username AWS \
    --password-stdin "$AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com"
```

### 3. Build and push the new image

```bash
docker buildx build \
  --platform linux/amd64 \
  -t "$IMAGE_URI" \
  --push \
  .
```

Confirm the image was pushed:

```bash
aws ecr describe-images \
  --repository-name "$ECR_REPO" \
  --region "$AWS_REGION" \
  --profile "$AWS_PROFILE"
```

### 4. Update the ECS Express Mode service

Update the service to use the new image:

```bash
aws ecs update-express-gateway-service \
  --service-arn "$SERVICE_ARN" \
  --primary-container "{\"image\":\"$IMAGE_URI\",\"containerPort\":8000,\"environment\":[{\"name\":\"AWS_DEFAULT_REGION\",\"value\":\"$AWS_REGION\"},{\"name\":\"AWS_REGION\",\"value\":\"$AWS_REGION\"},{\"name\":\"CHAT_MODEL_NAME\",\"value\":\"sonnet-4.6\"},{\"name\":\"SCORING_MODEL_NAME\",\"value\":\"sonnet-4.6\"}]}" \
  --monitor-resources \
  --region "$AWS_REGION" \
  --profile "$AWS_PROFILE"
```

This creates a new service revision and deploys it.

### 5. Check service status

```bash
aws ecs describe-express-gateway-service \
  --service-arn "$SERVICE_ARN" \
  --region "$AWS_REGION" \
  --profile "$AWS_PROFILE"
```

You can also monitor an existing service deployment:

```bash
aws ecs monitor-express-gateway-service \
  --service-arn "$SERVICE_ARN" \
  --region "$AWS_REGION" \
  --profile "$AWS_PROFILE"
```

## Environment variables

For ECS, this app should usually only need non-secret runtime config:

```text
AWS_DEFAULT_REGION
AWS_REGION
CHAT_MODEL_NAME
SCORING_MODEL_NAME
```

Do not set these in ECS:

```text
AWS_ACCESS_KEY_ID
AWS_SECRET_ACCESS_KEY
AWS_SESSION_TOKEN
AWS_PROFILE
```

The app should use the ECS task role for AWS Bedrock access.

For local Docker testing only, it is okay to use a local `.env` file with either:

```text
AWS_PROFILE + mounted ~/.aws directory
```

or temporary/local access keys.

## Useful commands

List ECR images:

```bash
aws ecr describe-images \
  --repository-name "$ECR_REPO" \
  --region "$AWS_REGION" \
  --profile "$AWS_PROFILE"
```

Describe Express service:

```bash
aws ecs describe-express-gateway-service \
  --service-arn "$SERVICE_ARN" \
  --region "$AWS_REGION" \
  --profile "$AWS_PROFILE"
```

Monitor Express service:

```bash
aws ecs monitor-express-gateway-service \
  --service-arn "$SERVICE_ARN" \
  --region "$AWS_REGION" \
  --profile "$AWS_PROFILE"
```
