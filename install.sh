#!/usr/bin/env bash
set -euo pipefail
useradd --system --no-create-home --shell /sbin/nologin snmp_exporter 2>/dev/null || true
useradd --system --no-create-home --shell /sbin/nologin cloudwatch_exporter 2>/dev/null || true
useradd --system --no-create-home --shell /sbin/nologin cloudsync-monitor 2>/dev/null || true
useradd --system --no-create-home --shell /sbin/nologin prometheus 2>/dev/null || true

install -d -m 750 -o cloudwatch_exporter -g cloudwatch_exporter /etc/cloudwatch_exporter
install -d -m 755 /opt/cloudsync-monitor
install -d -m 750 -o cloudsync-monitor -g cloudsync-monitor /var/lib/cloudsync-monitor
install -d -m 755 /etc/prometheus
install -d -m 755 -o prometheus -g prometheus /var/lib/prometheus

install -m 755 exporters/s3_realtime_exporter.py /usr/local/bin/s3_realtime_exporter.py
install -m 755 exporters/cloudsync_success_receiver.py /opt/cloudsync-monitor/cloudsync_success_receiver.py
cp configs/s3-exporter.env.example /etc/s3-exporter.env
chown root:cloudwatch_exporter /etc/s3-exporter.env && chmod 640 /etc/s3-exporter.env

MONITOR_TS_IP=$(tailscale ip -4 | head -n 1 || echo "127.0.0.1")
NEW_TOKEN=$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')
cat << ENV > /etc/cloudsync-monitor.env
CLOUDSYNC_BIND=${MONITOR_TS_IP}
CLOUDSYNC_PORT=9108
CLOUDSYNC_TOKEN=${NEW_TOKEN}
CLOUDSYNC_STATE=/var/lib/cloudsync-monitor/last_success.json
ENV
chown root:cloudsync-monitor /etc/cloudsync-monitor.env && chmod 640 /etc/cloudsync-monitor.env

cp configs/prometheus.yml /etc/prometheus/prometheus.yml
chown root:prometheus /etc/prometheus/prometheus.yml && chmod 640 /etc/prometheus/prometheus.yml
cp systemd/*.service /etc/systemd/system/
systemctl daemon-reload
echo "部署完成！您的 Post-script Token 為: ${NEW_TOKEN}"
