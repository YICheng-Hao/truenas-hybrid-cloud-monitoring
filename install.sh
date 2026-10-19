#!/usr/bin/env bash
# 全新 Rocky Linux 9 VM 安裝入口；保護既有未受管監控 VM。
set -euo pipefail
if [[ $(id -u) -ne 0 ]]; then
  echo '請先執行 sudo -i，再執行本腳本。' >&2
  exit 1
fi
PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
dnf install -y python3 python3-pyyaml
exec python3 "${PROJECT_DIR}/scripts/setup-monitoring-vm.py" "$@"
