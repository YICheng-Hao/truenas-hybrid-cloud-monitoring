# 第七章　Rocky Linux 9 監控 VM 從零建置

目前預設 Dashboard 的兩個容量面板已還原為既有 hrStorage 根掛載點統計；其餘健康／採集面板維持。下列 zfs USED／AVAILABLE 採集與容量告警為完整建置流程的一部分，但現場既有 NAS 尚未確認成功切換該命令。既有主機只需恢復容量顯示時，匯入目前 JSON 即可，不需重跑本指南。口徑與限制詳見 dashboard-panels.md 開頭。

本文件整合本專案實作及 2026-10-19 的修正。全新 VM 依序執行一次即可；既有 VM 更新參閱 [zfs-failure-test.md](zfs-failure-test.md)，不要將兩種流程混用。

既有主機遇到容量空白且 deploy-zfs-members.py 因缺少成員指標而還原時，改用該文件的「既有 VM：容量更新被成員檢查阻擋」流程與 deploy-zfs-capacity.py。不要為了修容量而重建 Grafana 或重新載入全部告警。

## 7.1 架構、版本與必填參數

本流程重現既有 SNMP Exporter 0.26.0、Prometheus 2.54.1 設定；Grafana 由官方 RPM 套件庫安裝。這是專案版本基準，不宣稱是最新版。VM 為 Rocky Linux 9 x86-64，可 SSH 登入並 sudo；監控流量透過 Tailscale，VM 本身仍需有可用的對外路由／DNS 下載套件。

| 項目 | 本專案範例 | 重建時需處理 |
|---|---|---|
| A 站 | 100.114.236.88，mainpool、boot-pool | 位址或名稱不同時修改 configs/prometheus.yml、告警與面板選取條件 |
| B 站 | 100.113.107.95，backuppool、boot-pool | 同上 |
| 監控 VM 管理 IP | 192.168.23.158 | 以新 VM 實際位址為準 |
| 監控 VM Tailscale IP | 安裝後動態取得 | 更新 Prometheus 的 cloudsync_success 目標與 A 站 Post-script |
| SNMP Community | public | 本專案沿用；若修改也需更新 Exporter public_v2 認證 |
| S3 bucket／Region | truenas-backup-myhome-2026／ap-east-2 | 對應 IAM、環境檔與面板 |
| Cloud Sync task_id | 1 | TrueNAS 實際任務 ID 不同時修改告警及面板 |
| Prometheus UID | cg15oru9k9clcd | 本流程用 provisioning 固定，告警依賴此 UID |
| 管理網段 | 192.168.23.0/24 | 修改防火牆來源與 Grafana root_url |

| 服務 | 監聽位置 | 用途 |
|---|---|---|
| SNMP Exporter | 127.0.0.1:9116 | Prometheus 透過它向兩站送出 SNMP 查詢 |
| S3 清單 Exporter | 127.0.0.1:9107 | 物件容量、數量與單一費率估算 |
| Cloud Sync Receiver | 監控 VM Tailscale IP:9108 | /success 接收成功回報，/metrics 提供最後成功時間 |
| Prometheus | :9090 | 四個採集工作 |
| Grafana | :3000 | 十面板與 Discord／Email 告警 |

## 7.2 基礎套件、時間與儲存庫

以具 sudo 權限的管理員登入後執行 sudo -i，後續範例皆在 root shell 執行；不需要為此開放 SSH root 密碼登入。

```bash
dnf update -y
dnf install -y dnf-plugins-core git curl wget tar unzip vim jq \
  python3 python3-pyyaml net-snmp-utils firewalld chrony
systemctl enable --now chronyd firewalld
timedatectl set-timezone Asia/Taipei
timedatectl status
ip -br addr
ip route
getent hosts github.com

git clone https://github.com/YICheng-Hao/truenas-hybrid-cloud-monitoring.git \
  /root/truenas-hybrid-cloud-monitoring
```

私有儲存庫需使用有讀取權限的 GitHub 認證。後續命令固定使用此目錄，執行前不需猜測目前工作目錄。

若 Cockpit 已啟用，先釋放 Prometheus 使用的 9090：

```bash
ss -lntp | grep ':9090' || true
systemctl disable --now cockpit.socket cockpit.service 2>/dev/null || true
```

## 7.3 Tailscale 與 TrueNAS SNMP

```bash
dnf config-manager --add-repo https://pkgs.tailscale.com/stable/rhel/9/tailscale.repo
dnf install -y tailscale
systemctl enable --now tailscaled
tailscale up
tailscale status
tailscale ip -4
tailscale ping -c 3 100.114.236.88
tailscale ping -c 3 100.113.107.95
```

完成瀏覽器登入／節點核准後，分別在 TrueNAS A、B【System ➔ Services ➔ SNMP】啟用 SNMP、設定 Community，並勾選開機自動啟動。附屬參數保留其他必要內容，下列兩個名稱各出現一次：

```text
extend zfs /usr/sbin/zpool status -P
extend zfs_capacity /usr/sbin/zfs list -Hp -o name,used,available
```

儲存並重新啟動兩站 SNMP。zfs 提供完整成員狀態；zfs_capacity 提供根資料集 USED／AVAILABLE，已取代舊版 zpool list 的原始物理容量。

```bash
for NAS_TS_IP in 100.114.236.88 100.113.107.95; do
  snmpget -v2c -c public -t 5 -r 1 "$NAS_TS_IP" 1.3.6.1.2.1.1.1.0
  snmpget -v2c -c public -t 5 -r 1 "$NAS_TS_IP" \
    1.3.6.1.4.1.8072.1.3.2.3.1.2.3.122.102.115
  snmpget -v2c -c public -t 5 -r 1 "$NAS_TS_IP" \
    1.3.6.1.4.1.8072.1.3.2.3.1.2.12.122.102.115.95.99.97.112.97.99.105.116.121
done
```

先確認兩站均回傳資料。No Such Instance 表示 extend 未生效，不是正常磁碟的回覆。

## 7.4 安裝 SNMP Exporter 並合併 ZFS 模組

```bash
id snmp_exporter >/dev/null 2>&1 || useradd --system --no-create-home --shell /sbin/nologin snmp_exporter
cd /tmp
curl -fLO https://github.com/prometheus/snmp_exporter/releases/download/v0.26.0/snmp_exporter-0.26.0.linux-amd64.tar.gz
tar -xzf snmp_exporter-0.26.0.linux-amd64.tar.gz
install -m 755 snmp_exporter-0.26.0.linux-amd64/snmp_exporter /usr/local/bin/snmp_exporter
install -d -m 755 /etc/snmp_exporter
install -m 644 snmp_exporter-0.26.0.linux-amd64/snmp.yml /etc/snmp_exporter/snmp.yml

python3 - <<'PY'
from pathlib import Path
import yaml
p = Path('/etc/snmp_exporter/snmp.yml')
config = yaml.safe_load(p.read_text())
extra = yaml.safe_load(Path('/root/truenas-hybrid-cloud-monitoring/configs/snmp-zfs-modules.yml').read_text())
config['modules'].update(extra['modules'])
required = {'if_mib', 'hrStorage', 'hrDevice', 'hrSystem', 'truenas_zfs'}
assert required.issubset(config['modules']), '缺少標準 SNMP 模組'
assert 'public_v2' in config['auths'], '缺少 public_v2 認證'
p.write_text(yaml.safe_dump(config, sort_keys=False, allow_unicode=True))
PY

/usr/local/bin/snmp_exporter --config.file=/etc/snmp_exporter/snmp.yml --dry-run
cp /root/truenas-hybrid-cloud-monitoring/systemd/snmp_exporter.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now snmp_exporter

for NAS_TS_IP in 100.114.236.88 100.113.107.95; do
  curl -fsS --max-time 25 \
    "http://127.0.0.1:9116/snmp?target=${NAS_TS_IP}&auth=public_v2&module=truenas_zfs" \
    | grep -E '^(zpoolHealthStr|zfsMemberFault|zfsStatusCommandExit|zfsUsablePool)'
done
```

正常成員指標為 0、指令退出碼為 0；異常成員可為 1。容量應有 UsedBytes 與 AvailableBytes，不能只驗證池 ONLINE。

## 7.5 AWS CLI 與專用監控憑證

監控 IAM 帳號使用 aws-iam/s3-monitoring-policy.json，僅授權目標 bucket 的 s3:ListBucket。使用監控帳號自己的金鑰，不要誤貼第六章具有上傳權限的備份帳號金鑰。

安裝 AWS CLI v2 Linux x86-64：

```bash
cd /tmp
curl -fLo awscliv2.zip https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip
unzip -q awscliv2.zip
./aws/install
aws --version

id cloudwatch_exporter >/dev/null 2>&1 || useradd --system --no-create-home --shell /sbin/nologin cloudwatch_exporter
install -d -m 750 -o cloudwatch_exporter -g cloudwatch_exporter /etc/cloudwatch_exporter
install -m 600 -o cloudwatch_exporter -g cloudwatch_exporter \
  /root/truenas-hybrid-cloud-monitoring/configs/credentials.example \
  /etc/cloudwatch_exporter/credentials
vi /etc/cloudwatch_exporter/credentials
```

在檔案內把兩個 YOUR_IAM_MONITORING 欄位換成監控帳號的實際金鑰，再驗證：

```bash
su -s /bin/bash -c \
  'AWS_SHARED_CREDENTIALS_FILE=/etc/cloudwatch_exporter/credentials AWS_DEFAULT_REGION=ap-east-2 /usr/local/bin/aws s3 ls s3://truenas-backup-myhome-2026/ --recursive --summarize' \
  cloudwatch_exporter | tail -5
```

不要將此檔案提交到 GitHub。

## 7.6 S3 清單與費率估算服務

```bash
install -m 755 /root/truenas-hybrid-cloud-monitoring/exporters/s3_realtime_exporter.py /usr/local/bin/s3_realtime_exporter.py
install -m 640 -o root -g cloudwatch_exporter \
  /root/truenas-hybrid-cloud-monitoring/configs/s3-exporter.env.example /etc/s3-exporter.env
vi /etc/s3-exporter.env
cp /root/truenas-hybrid-cloud-monitoring/systemd/s3_realtime_exporter.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now s3_realtime_exporter
curl -fsS --max-time 150 http://127.0.0.1:9107/metrics
```

依實際 bucket、region 與費率修改環境檔。health_status=1 只表示清單 API 成功；月費是單一費率儲存估算，不是 AWS 實際帳單。這個服務不使用 CloudWatch API。

## 7.7 Cloud Sync 成功回報 Receiver

```bash
id cloudsync-monitor >/dev/null 2>&1 || useradd --system --no-create-home --shell /sbin/nologin cloudsync-monitor
install -d -m 755 /opt/cloudsync-monitor
install -d -m 750 -o cloudsync-monitor -g cloudsync-monitor /var/lib/cloudsync-monitor
install -m 755 /root/truenas-hybrid-cloud-monitoring/exporters/cloudsync_success_receiver.py /opt/cloudsync-monitor/cloudsync_success_receiver.py

python3 - <<'PY'
import secrets, subprocess
from pathlib import Path
p = Path('/etc/cloudsync-monitor.env')
if p.exists():
    raise SystemExit('已有 Receiver 環境檔，停止產生新 Token；保留原檔即可繼續下一步。')
ip = subprocess.check_output(['tailscale','ip','-4'], text=True).splitlines()[0].strip()
token = secrets.token_urlsafe(32)
p.write_text(f'CLOUDSYNC_BIND={ip}\nCLOUDSYNC_PORT=9108\nCLOUDSYNC_TOKEN={token}\nCLOUDSYNC_STATE=/var/lib/cloudsync-monitor/last_success.json\n')
p.chmod(0o640)
PY

chown root:cloudsync-monitor /etc/cloudsync-monitor.env
cp /root/truenas-hybrid-cloud-monitoring/systemd/cloudsync-monitor.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now cloudsync-monitor
MONITOR_TS_IP=$(tailscale ip -4 | head -n 1)
curl -fsS "http://${MONITOR_TS_IP}:9108/metrics"
```

尚未成功回報時，只有 HELP／TYPE 而沒有任務時間戳是合理結果，不要偽造成功時間。Token 留在此環境檔並填入 A 站 Post-script，不在重跑其他服務時重新產生。

## 7.8 防火牆與 TrueNAS A Post-script

先執行 firewall-cmd --get-active-zones，以下 ADMIN_ZONE 必須對應實際介面區域；ADMIN_CIDR 為可管理此 VM 的來源網段。

```bash
firewall-cmd --get-active-zones
ADMIN_ZONE=public
ADMIN_CIDR=192.168.23.0/24
firewall-cmd --permanent --zone="$ADMIN_ZONE" --add-rich-rule="rule family=ipv4 source address=${ADMIN_CIDR} port port=9090 protocol=tcp accept"
firewall-cmd --permanent --zone="$ADMIN_ZONE" --add-rich-rule="rule family=ipv4 source address=${ADMIN_CIDR} port port=3000 protocol=tcp accept"
firewall-cmd --permanent --zone="$ADMIN_ZONE" --add-rich-rule='rule family="ipv4" source address="100.114.236.88/32" port port="9108" protocol="tcp" accept'
firewall-cmd --reload
firewall-cmd --zone="$ADMIN_ZONE" --list-all
```

Tailscale 會建立自己的 netfilter 規則；實際跨站存取授權也需由 tailnet 的 grants／ACL 管理，不能只憑上述 rich rule 宣稱已限制所有 Tailscale 流量。

在 A 站【資料保護 ➔ 雲端同步作業 ➔ 目標任務 ➔ 進階選項 ➔ Post-script】貼上。替換下列 MONITOR_TS_IP 與 TOKEN；Task ID 預設使用任務提供的 CLOUD_SYNC_ID，必要時核對實際 ID：

```bash
MONITOR_TS_IP='填入監控VM的Tailscale_IP'
TOKEN='填入/etc/cloudsync-monitor.env中的Token'
curl -fsS --connect-timeout 5 --max-time 15 \
  -X POST -H "Authorization: Bearer ${TOKEN}" \
  --data-urlencode "task_id=${CLOUD_SYNC_ID}" \
  "http://${MONITOR_TS_IP}:9108/success" \
  || logger -t cloudsync-monitor 'Cloud Sync callback failed'
```

以真實 Run Now 成功任務驗證，回監控 VM 查詢 /metrics 應出現該 task_id 的時間戳。回報失敗應查 Token、IP、9108、服務與權限；不把本機 /success 手動測試當作備份成功證據。

## 7.9 Prometheus 四個採集工作

```bash
id prometheus >/dev/null 2>&1 || useradd --system --no-create-home --shell /sbin/nologin prometheus
cd /tmp
curl -fLO https://github.com/prometheus/prometheus/releases/download/v2.54.1/prometheus-2.54.1.linux-amd64.tar.gz
tar -xzf prometheus-2.54.1.linux-amd64.tar.gz
install -m 755 prometheus-2.54.1.linux-amd64/prometheus /usr/local/bin/prometheus
install -m 755 prometheus-2.54.1.linux-amd64/promtool /usr/local/bin/promtool
install -d -m 755 /etc/prometheus
install -d -m 755 -o prometheus -g prometheus /var/lib/prometheus
cp -r prometheus-2.54.1.linux-amd64/consoles prometheus-2.54.1.linux-amd64/console_libraries /etc/prometheus/
cp /root/truenas-hybrid-cloud-monitoring/configs/prometheus.yml /etc/prometheus/prometheus.yml

python3 - <<'PY'
import subprocess, yaml
from pathlib import Path
p = Path('/etc/prometheus/prometheus.yml')
config = yaml.safe_load(p.read_text())
ip = subprocess.check_output(['tailscale','ip','-4'], text=True).splitlines()[0].strip()
for job in config['scrape_configs']:
    if job['job_name'] == 'cloudsync_success':
        job['static_configs'][0]['targets'] = [ip + ':9108']
p.write_text(yaml.safe_dump(config, sort_keys=False))
PY

chown root:prometheus /etc/prometheus/prometheus.yml
chmod 640 /etc/prometheus/prometheus.yml
/usr/local/bin/promtool check config /etc/prometheus/prometheus.yml
cp /root/truenas-hybrid-cloud-monitoring/systemd/prometheus.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now prometheus
curl -fsS http://127.0.0.1:9090/-/ready
```

瀏覽 http://監控VM管理IP:9090/targets。共四個 job：prometheus、truenas_snmp、aws_s3、cloudsync_success；truenas_snmp 有兩個目標，因此通常共五個 target，均應 UP。S3 API 是否真的成功還需看 Exporter 的 health_status，不能只看 HTTP UP。

## 7.10 Grafana、資料源與完整九條告警

```bash
cat > /etc/yum.repos.d/grafana.repo <<'EOF'
[grafana]
name=grafana
baseurl=https://rpm.grafana.com
repo_gpgcheck=1
enabled=1
gpgcheck=1
gpgkey=https://rpm.grafana.com/gpg.key
sslverify=1
sslcacert=/etc/pki/tls/certs/ca-bundle.crt
EOF
dnf install -y grafana
install -d -m 755 /etc/grafana/provisioning/datasources /etc/grafana/provisioning/alerting
cp /root/truenas-hybrid-cloud-monitoring/configs/grafana-datasource.yaml /etc/grafana/provisioning/datasources/prometheus.yaml
cp /root/truenas-hybrid-cloud-monitoring/configs/grafana-alerts.yaml /etc/grafana/provisioning/alerting/truenas-alerts.yaml
systemctl daemon-reload
systemctl enable --now grafana-server
curl -fsS http://127.0.0.1:3000/api/health
```

全新建置只載入這一份九條規則。不要再另外執行 deploy-zfs-alerts.py 或複製 grafana-zfs-members.yaml，避免重複 UID。所有告警群組均使用 1m，避開先前 15s 與排程基準不相容的啟動錯誤。Prometheus SNMP 採集仍可為 15s。

登入 http://監控VM管理IP:3000，首次登入依畫面變更管理員密碼。確認 Prometheus 資料源 UID cg15oru9k9clcd，Alert rules 應有九條；沒有 Cloud Sync 成功時間戳時，逾時告警可先出現 No Data，完成真實回報後再判讀。

## 7.11 匯入面板、Email 與 Discord

下載 grafana/TrueNAS_Hybrid_Cloud.json，Grafana【Dashboards ➔ New ➔ Import】上傳，選 Prometheus。新主機直接匯入；既有主機使用同 UID 並 Overwrite。共有十個面板，用途見 [dashboard-panels.md](dashboard-panels.md)。容量為 zfs 根資料集 USED／AVAILABLE，不是 zpool 原始容量。

編輯 /etc/grafana/grafana.ini 已存在的 [server]、[smtp] 區塊，不重複新增同名區塊。下列管理 IP、Gmail 帳號及 App Password 必須換成實際值：

```ini
[server]
domain = 192.168.23.158
root_url = http://192.168.23.158:3000/

[smtp]
enabled = true
host = smtp.gmail.com:587
user = YOUR_GMAIL_ACCOUNT@gmail.com
password = "YOUR_GOOGLE_APP_PASSWORD"
from_address = YOUR_GMAIL_ACCOUNT@gmail.com
from_name = NAS_Alert
skip_verify = false
```

執行 systemctl restart grafana-server。到【Alerting ➔ Contact points ➔ Notification templates】建立 zh_tw_alert_template，貼入 configs/grafana-notification-template.tmpl 的完整 Go template 原文；不要貼 YAML provisioning 檔。

建立 NAS_Alerts_Email_Discord 聯絡點，加入 Email 與 Discord 兩個整合。填入自己的收件地址／Webhook，Title／Subject 為 {{ template "nas.title" . }}，Message／Body 為 {{ template "nas.body" . }}。分別按 Test 確認兩個管道，再於 Notification policies 指向此聯絡點並啟用恢復通知。範例可設 group_by 為 grafana_folder、alertname、instance，group_wait=10s、group_interval=1m、repeat_interval=4h；時間依實際需求調整。

## 7.12 驗收、故障演練與重建保存清單

| 驗收項目 | 正常／預期結果 |
|---|---|
| 時間 | chronyd 啟動，時區 Asia/Taipei |
| Tailscale | 可連兩站，IP 與設定一致 |
| SNMP extend | 兩站皆有完整狀態與 USED／AVAILABLE |
| 指標 | 成員=0、退出碼=0；容量非 No Data |
| Prometheus | 四個 job、通常五個 target 均 UP |
| S3 | health_status=1；可見容量／物件數 |
| Cloud Sync | 真實成功任務後出現正確 task_id 時間戳 |
| Grafana | 十面板、九規則、資料源 UID 正確 |
| 通知 | Discord 與 Email 各自 Test 成功，確認異常與恢復 |

先以暫停 snmp_exporter 驗證採集離線與恢復，再依 [zfs-failure-test.md](zfs-failure-test.md) 執行隔離磁碟故障測試。不要將停止 Exporter 當成已驗證磁碟故障告警。

重建前另行保存：AWS 監控帳號金鑰、Receiver Token／成功回報狀態檔、Gmail App Password、Discord Webhook、Grafana 通知政策／聯絡點設定，以及 Tailscale 節點授權流程。私密資料另存安全位置，不提交 GitHub。若原 VM 尚有可用磁碟，可另外備份 Grafana 資料庫與設定；GitHub 原始碼不包含所有現場私密設定。

## 容量口徑與版本修正彙整

| 舊問題 | 本版處理 |
|---|---|
| 只看池 ONLINE，漏掉成員 FAULTED | 獨立成員指標＋兩條告警＋綜合健康面板 |
| 將 OID 第 7 欄當健康數值 | 移除錯誤自訂值，使用原生健康字串 |
| Grafana 15s 群組無法啟動 | 告警群組統一 1m；採集週期另外設定 |
| 根掛載點只顯示 384 KiB | 使用 zfs USED，包含子資料集與快照 |
| 六顆磁碟原始容量約 3 TB | 使用根資料集 USED＋AVAILABLE，不把 parity 空間當資料可用額度 |
| 重複空間 Gauge／面板 | 保留十個用途清楚的面板 |
| 多份檔案重複載入相同 UID | 從零建置統一使用一份九條規則 |
| B 站沒有 extend | 兩站分別查詢驗證，不把缺資料當正常 |
| Cloud Sync Token 被重新產生 | 獨立環境檔，重建／更新時明確保留 |

500 GB 的六碟 RAID-Z2 理論資料容量約 (6−2)×500 GB=2000 GB≈1.82 TiB；若 VMware 設定其實是 500 GiB，理論值約 2000 GiB≈1.95 TiB。實際 AVAILABLE 還受 ZFS 中繼資料、保留空間、既有資料、quota／reservation 影響；以 zfs list 實測為準，不硬寫固定 2 TB。

OpenZFS 官方說明：
- https://openzfs.github.io/openzfs-docs/man/v2.3/7/zfsprops.7.html
- https://openzfs.github.io/openzfs-docs/man/v2.2/7/zpoolprops.7.html

本流程已完成設定解析、查詢語法、合成狀態與文字解析驗證；尚未在全新 Rocky VM 逐項重建實測。既有 A 站成員故障與 Discord 通知已有使用者截圖佐證，不代表新主機或 Email 已自動通過。
