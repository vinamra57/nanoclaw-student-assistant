#!/usr/bin/env bash
set -euo pipefail

# Runs ON the VM (called by provision-student.sh via SSH).
# Installs NanoClaw, configures the student agent, and starts the gateway.
#
# Usage: ./setup-student.sh <DISCORD_TOKEN> <ANTHROPIC_KEY> <VIRTUAL_TA_URL> \
#                           [ED_TOKEN] [ED_COURSE_ID] [COMPOSIO_KEY]

if [[ $# -lt 3 ]]; then
  echo "Usage: $0 <DISCORD_TOKEN> <ANTHROPIC_KEY> <VIRTUAL_TA_URL> [ED_TOKEN] [ED_COURSE_ID] [COMPOSIO_KEY] [CHATCSE_AGENT_TOKEN]"
  exit 1
fi

DISCORD_TOKEN="$1"
ANTHROPIC_KEY="$2"
VIRTUAL_TA_URL="$3"
ED_TOKEN="${4:-}"
ED_COURSE_ID="${5:-}"
COMPOSIO_KEY="${6:-}"
CHATCSE_AGENT_TOKEN="${7:-}"

echo "==> Updating system packages"
sudo apt update && sudo apt upgrade -y

echo "==> Installing Node.js 22.x"
curl -fsSL https://deb.nodesource.com/setup_22.x | sudo -E bash -
sudo apt install -y nodejs

echo "==> Installing Python 3.13 and build tools"
sudo apt install -y python3 python3-pip python3-venv build-essential git curl

echo "==> Installing Docker"
for pkg in docker.io docker-doc docker-compose docker-compose-v2 podman-docker containerd runc; do
  sudo apt remove -y "$pkg" 2>/dev/null || true
done

sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg --yes
sudo chmod a+r /etc/apt/keyrings/docker.gpg

# shellcheck source=/dev/null
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu \
  $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

sudo apt update
sudo apt install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

if ! sudo systemctl is-active --quiet docker; then
  sudo systemctl start docker
fi
sudo systemctl enable --quiet docker
sudo usermod -aG docker "$USER"

echo "==> Cloning NanoClaw"
if [[ ! -d "$HOME/nanoclaw" ]]; then
  git clone https://github.com/qwibitai/nanoclaw.git "$HOME/nanoclaw"
else
  git -C "$HOME/nanoclaw" pull --rebase
fi

echo "==> Patching onboard for non-interactive setup"
SETUP_SCRIPT="$HOME/nanoclaw/scripts/docker/setup.sh"
sed -i 's|run_prestart_cli onboard --mode local --no-install-daemon|run_prestart_cli onboard --mode local --no-install-daemon --non-interactive --accept-risk --flow quickstart --auth-choice anthropic-api-key --anthropic-api-key '"$ANTHROPIC_KEY"' --secret-input-mode plaintext --skip-channels --skip-skills --skip-search --skip-health|' "$SETUP_SCRIPT"

echo "==> Running NanoClaw Docker setup"
sg docker -c "cd $HOME/nanoclaw && NANOCLAW_GATEWAY_BIND=loopback ./docker-setup.sh"

echo "==> Restoring original setup script"
git -C "$HOME/nanoclaw" checkout -- scripts/docker/setup.sh

echo "==> Adding Discord channel"
sg docker -c "cd $HOME/nanoclaw && docker compose -f docker-compose.yml run --rm nanoclaw-cli channels add --channel discord --token $DISCORD_TOKEN"

echo "==> Setting up student-assistant MCP servers"
# Clone student-assistant repo for custom MCP servers
if [[ ! -d "$HOME/student-assistant" ]]; then
  git clone https://github.com/vinamra57/nanoclaw-student-assistant.git "$HOME/student-assistant"
else
  git -C "$HOME/student-assistant" pull --rebase
fi

# Create Python venv for MCP servers
python3 -m venv "$HOME/student-assistant/.venv"
# shellcheck source=/dev/null
source "$HOME/student-assistant/.venv/bin/activate"
pip install -e "$HOME/student-assistant"
deactivate

echo "==> Writing environment file"
cat > "$HOME/student-assistant/.env" << ENVEOF
VIRTUAL_TA_URL=$VIRTUAL_TA_URL
CHATCSE_AGENT_TOKEN=$CHATCSE_AGENT_TOKEN
ED_API_TOKEN=$ED_TOKEN
ED_COURSE_ID=$ED_COURSE_ID
COMPOSIO_API_KEY=$COMPOSIO_KEY
ENVEOF
chmod 600 "$HOME/student-assistant/.env"

echo ""
echo "============================================"
echo "  Student assistant setup complete!"
echo "============================================"
echo ""
echo "The Discord bot is online. To pair:"
echo "  1. DM the bot on Discord"
echo "  2. It replies with a pairing code"
echo "  3. Run: cd ~/nanoclaw && docker compose -f docker-compose.yml run --rm nanoclaw-cli pairing approve discord <CODE>"
echo ""
