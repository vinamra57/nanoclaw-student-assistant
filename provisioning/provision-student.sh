#!/usr/bin/env bash
set -euo pipefail

# Provision a GCP VM for a student's NanoClaw agent.
# Extends the base NanoClaw provisioning with student-assistant-specific setup.
#
# Usage:
#   ./provision-student.sh \
#     --project <GCP_PROJECT> \
#     --zone <GCP_ZONE> \
#     --service-account <SA_EMAIL> \
#     --vm-name <VM_NAME> \
#     --discord-token <DISCORD_BOT_TOKEN> \
#     --anthropic-key <ANTHROPIC_API_KEY> \
#     --virtual-ta-url <VIRTUAL_TA_MCP_URL> \
#     [--ed-token <ED_API_TOKEN>] \
#     [--ed-course-id <ED_COURSE_ID>] \
#     [--composio-key <COMPOSIO_API_KEY>] \
#     [--machine-type <TYPE>] \
#     [--disk-size <GB>]

PROJECT=""
ZONE=""
SERVICE_ACCOUNT=""
VM_NAME=""
DISCORD_TOKEN=""
ANTHROPIC_KEY=""
VIRTUAL_TA_URL=""
CHATCSE_AGENT_TOKEN=""
ED_TOKEN=""
ED_COURSE_ID=""
COMPOSIO_KEY=""
MACHINE_TYPE="e2-medium"
DISK_SIZE="20"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --project) PROJECT="$2"; shift 2 ;;
    --zone) ZONE="$2"; shift 2 ;;
    --service-account) SERVICE_ACCOUNT="$2"; shift 2 ;;
    --vm-name) VM_NAME="$2"; shift 2 ;;
    --discord-token) DISCORD_TOKEN="$2"; shift 2 ;;
    --anthropic-key) ANTHROPIC_KEY="$2"; shift 2 ;;
    --virtual-ta-url) VIRTUAL_TA_URL="$2"; shift 2 ;;
    --chatcse-agent-token) CHATCSE_AGENT_TOKEN="$2"; shift 2 ;;
    --ed-token) ED_TOKEN="$2"; shift 2 ;;
    --ed-course-id) ED_COURSE_ID="$2"; shift 2 ;;
    --composio-key) COMPOSIO_KEY="$2"; shift 2 ;;
    --machine-type) MACHINE_TYPE="$2"; shift 2 ;;
    --disk-size) DISK_SIZE="$2"; shift 2 ;;
    *) echo "Unknown option: $1"; exit 1 ;;
  esac
done

# Validate required args
missing=()
[[ -z "$PROJECT" ]] && missing+=("--project")
[[ -z "$ZONE" ]] && missing+=("--zone")
[[ -z "$SERVICE_ACCOUNT" ]] && missing+=("--service-account")
[[ -z "$VM_NAME" ]] && missing+=("--vm-name")
[[ -z "$DISCORD_TOKEN" ]] && missing+=("--discord-token")
[[ -z "$ANTHROPIC_KEY" ]] && missing+=("--anthropic-key")
[[ -z "$VIRTUAL_TA_URL" ]] && missing+=("--virtual-ta-url")

if [[ ${#missing[@]} -gt 0 ]]; then
  echo "Missing required arguments: ${missing[*]}"
  echo ""
  echo "Usage: $0 \\"
  echo "  --project <GCP_PROJECT> \\"
  echo "  --zone <GCP_ZONE> \\"
  echo "  --service-account <SA_EMAIL> \\"
  echo "  --vm-name <VM_NAME> \\"
  echo "  --discord-token <DISCORD_BOT_TOKEN> \\"
  echo "  --anthropic-key <ANTHROPIC_API_KEY> \\"
  echo "  --virtual-ta-url <VIRTUAL_TA_MCP_URL> \\"
  echo "  [--ed-token <ED_API_TOKEN>] \\"
  echo "  [--ed-course-id <ED_COURSE_ID>] \\"
  echo "  [--composio-key <COMPOSIO_API_KEY>] \\"
  echo "  [--machine-type <TYPE>]    (default: e2-medium) \\"
  echo "  [--disk-size <GB>]         (default: 20)"
  exit 1
fi

echo "==> Creating VM: $VM_NAME"
gcloud compute instances create "$VM_NAME" \
  --project="$PROJECT" \
  --zone="$ZONE" \
  --machine-type="$MACHINE_TYPE" \
  --network-interface=network-tier=PREMIUM,stack-type=IPV4_ONLY,subnet=default \
  --metadata=enable-osconfig=TRUE \
  --maintenance-policy=MIGRATE \
  --provisioning-model=STANDARD \
  --service-account="$SERVICE_ACCOUNT" \
  --scopes=https://www.googleapis.com/auth/devstorage.read_only,https://www.googleapis.com/auth/logging.write,https://www.googleapis.com/auth/monitoring.write,https://www.googleapis.com/auth/service.management.readonly,https://www.googleapis.com/auth/servicecontrol,https://www.googleapis.com/auth/trace.append \
  --create-disk=auto-delete=yes,boot=yes,device-name="$VM_NAME",image=projects/ubuntu-os-cloud/global/images/ubuntu-minimal-2404-noble-amd64-v20260325,mode=rw,size="$DISK_SIZE",type=pd-balanced \
  --no-shielded-secure-boot \
  --shielded-vtpm \
  --shielded-integrity-monitoring \
  --reservation-affinity=any

echo "==> Waiting for SSH to be ready..."
for i in $(seq 1 30); do
  if gcloud compute ssh "$VM_NAME" --project="$PROJECT" --zone="$ZONE" --command="echo ready" 2>/dev/null; then
    break
  fi
  echo "  Attempt $i/30 — waiting..."
  sleep 10
done

echo "==> Copying setup script to VM"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
gcloud compute scp "$SCRIPT_DIR/setup-student.sh" "$VM_NAME":~ --project="$PROJECT" --zone="$ZONE"

echo "==> Running setup (this takes 5-10 minutes)"
gcloud compute ssh "$VM_NAME" --project="$PROJECT" --zone="$ZONE" -- \
  "chmod +x ~/setup-student.sh && ~/setup-student.sh \
    '$DISCORD_TOKEN' '$ANTHROPIC_KEY' '$VIRTUAL_TA_URL' \
    '$ED_TOKEN' '$ED_COURSE_ID' '$COMPOSIO_KEY' '$CHATCSE_AGENT_TOKEN'"

echo ""
echo "============================================"
echo "  VM '$VM_NAME' is ready!"
echo "============================================"
echo ""
echo "To SSH in:  gcloud compute ssh $VM_NAME --project=$PROJECT --zone=$ZONE"
echo "To stop:    gcloud compute instances stop $VM_NAME --project=$PROJECT --zone=$ZONE"
echo "To start:   gcloud compute instances start $VM_NAME --project=$PROJECT --zone=$ZONE"
echo ""
echo "Next: Pair the student's Discord account (see docs/onboarding.md)"
echo ""
