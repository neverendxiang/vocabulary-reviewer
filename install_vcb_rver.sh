#!/usr/bin/env bash
set -euo pipefail

SERVICE_NAME="vcb_rver"
APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SERVICE_USER="${SERVICE_USER:-${SUDO_USER:-$(id -un)}}"
PYTHON_BIN="${PYTHON_BIN:-$(command -v python3 || true)}"
ENV_FILE="/etc/default/${SERVICE_NAME}"
UNIT_FILE="/etc/systemd/system/${SERVICE_NAME}.service"

if [[ "$(id -u)" -ne 0 ]]; then
  echo "Run this installer with sudo:"
  echo "  sudo bash ./install_vcb_rver.sh"
  exit 1
fi

if [[ -z "${PYTHON_BIN}" ]]; then
  echo "python3 was not found. Install it first:"
  echo "  sudo apt update && sudo apt install python3"
  exit 1
fi

if [[ ! -f "${APP_DIR}/server.py" ]]; then
  echo "server.py was not found in ${APP_DIR}"
  echo "Run this script from the cloned vocabulary reviewer project."
  exit 1
fi

if [[ ! -f "${APP_DIR}/organized_vocabulary_notes.xlsx" ]]; then
  echo "organized_vocabulary_notes.xlsx was not found in ${APP_DIR}"
  echo "Copy the workbook into the project before starting the service."
  exit 1
fi

if [[ ! -f "${ENV_FILE}" ]]; then
  cat > "${ENV_FILE}" <<EOF
# vcb_rver settings
VOCAB_HOST=0.0.0.0
VOCAB_PORT=8000

# Optional local dictionary paths on this Ubuntu server.
# Uncomment and edit these after copying the .mdx files to the server.
# LOCAL_OXFORD_MDX=${APP_DIR}/dictionaries/oxford/Oxford_ALD_9th_En-En.mdx
# LOCAL_LONGMAN_MDX=${APP_DIR}/dictionaries/longman/longman_dictionary_of_contemporary_english_6th_edition.mdx
# LOCAL_LONGMAN_PHRASAL_MDX=${APP_DIR}/dictionaries/longman/Longman_Phrasal_Verbs.mdx

# Optional Oxford API credentials.
# OXFORD_APP_ID=
# OXFORD_APP_KEY=
EOF
fi

systemd_quote() {
  local value="${1//\\/\\\\}"
  value="${value//\"/\\\"}"
  printf '"%s"' "${value}"
}

cat > "${UNIT_FILE}" <<EOF
[Unit]
Description=Vocabulary Reviewer
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=${SERVICE_USER}
WorkingDirectory=$(systemd_quote "${APP_DIR}")
EnvironmentFile=-${ENV_FILE}
ExecStart=${PYTHON_BIN} $(systemd_quote "${APP_DIR}/server.py")
Restart=always
RestartSec=3
NoNewPrivileges=true

[Install]
WantedBy=multi-user.target
EOF

chown -R "${SERVICE_USER}:${SERVICE_USER}" "${APP_DIR}"
systemctl daemon-reload
systemctl enable "${SERVICE_NAME}"
systemctl restart "${SERVICE_NAME}"

echo "${SERVICE_NAME} is installed and running."
echo "Status: sudo systemctl status ${SERVICE_NAME}"
echo "Logs:   journalctl -u ${SERVICE_NAME} -f"
echo "Open:   http://<server-ip>:$(grep -E '^VOCAB_PORT=' "${ENV_FILE}" | cut -d= -f2)"
