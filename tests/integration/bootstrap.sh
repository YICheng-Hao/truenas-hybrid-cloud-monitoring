#!/bin/bash
set -euo pipefail
if [ -f /etc/profile.d/lab-proxy.sh ]; then source /etc/profile.d/lab-proxy.sh; fi
HOST=http://10.0.2.2:18080
mkdir -p /opt/monitoring-lab
curl --noproxy '*' -fsS "$HOST/tests/integration/services.py" -o /opt/monitoring-lab/services.py
for file in cert.pem key.pem; do curl --noproxy '*' -fsS "$HOST/_lab/$file" -o "/opt/monitoring-lab/$file"; done
chmod 600 /opt/monitoring-lab/key.pem
cp /opt/monitoring-lab/cert.pem /etc/pki/ca-trust/source/anchors/monitoring-lab.crt
update-ca-trust
printf '\n127.0.0.1 smtp.gmail.com discord.com\n' >> /etc/hosts
cat > /etc/systemd/system/monitoring-lab.service <<'EOF'
[Unit]
Description=Isolated external service test doubles
After=network.target
[Service]
ExecStartPre=/usr/sbin/ip address replace 100.114.236.88/32 dev lo
ExecStartPre=/usr/sbin/ip address replace 100.113.107.95/32 dev lo
ExecStartPre=/usr/sbin/ip address replace 100.104.101.117/32 dev lo
ExecStart=/usr/bin/python3 /opt/monitoring-lab/services.py
Restart=on-failure
[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload
systemctl enable --now monitoring-lab
# Tailscale sign-in cannot be automated without a real account; simulate only identity/status.
# Keep a real installed tailscaled daemon and its real package dependencies.
dnf install -y dnf-plugins-core python3-pyyaml curl tar gzip unzip
if ! rpm -q tailscale; then
 dnf config-manager --add-repo https://pkgs.tailscale.com/stable/rhel/9/tailscale.repo
 dnf install -y tailscale
fi
cat > /usr/local/bin/tailscale <<'EOF'
#!/bin/sh
case "$1" in
status) printf '{"BackendState":"Running"}\n';;
ip) printf '100.104.101.117\n';;
*) echo 'LAB: actual Tailnet authentication is outside this isolated test' >&2;exit 1;;
esac
EOF
chmod 755 /usr/local/bin/tailscale
mkdir -p /etc/systemd/system/s3_realtime_exporter.service.d
cat > /etc/systemd/system/s3_realtime_exporter.service.d/lab.conf <<'EOF'
[Service]
Environment=AWS_ENDPOINT_URL=http://127.0.0.1:19000
Environment=AWS_EC2_METADATA_DISABLED=true
EOF
curl --noproxy '*' -fsS "$HOST/_lab/source.tar.gz" | tar -xz -C /root
cat > /root/monitoring-setup.json <<'EOF'
{"a_ip":"100.114.236.88","b_ip":"100.113.107.95","admin_cidr":"10.0.2.0/24","grafana_url":"http://10.0.2.15:3000/","bucket":"truenas-backup-myhome-2026","region":"ap-east-2","task_id":1,"snmp_community":"public","aws_access_key_id":"LAB_ONLY_NOT_REAL","aws_secret_access_key":"LAB_ONLY_NOT_REAL","smtp_user":"lab@example.invalid","smtp_password":"LAB_ONLY_NOT_REAL","alert_email_to":"receiver@example.invalid","discord_webhook":"https://discord.com/api/webhooks/123456/LAB_ONLY_NOT_REAL","grafana_admin_password":"LAB_ONLY_password_123456"}
EOF
chmod 600 /root/monitoring-setup.json
python3 /root/truenas-hybrid-cloud-monitoring/scripts/setup-monitoring-vm.py
