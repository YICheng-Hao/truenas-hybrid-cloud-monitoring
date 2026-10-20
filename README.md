# TrueNAS 混合雲災備監控

監測 TrueNAS A／B 的 SNMP、ZFS 健康與磁碟成員，以及 AWS S3 清單和真實 Cloud Sync 成功回報；由 Prometheus 採集、Grafana 顯示與透過 Email／Discord 通知。

## 從零建立監測 VM

請依 [完整複製貼上教學](docs/monitoring-vm-from-zero.md) 操作。這是全新 Rocky Linux 9／10 x86_64 VM 安裝流程。目前正常運作的舊 VM 不需要執行安裝器。

```bash
sudo -i
(
  set -e
  dnf install -y git python3 python3-pyyaml
  if [ -d /root/truenas-hybrid-cloud-monitoring/.git ]; then
    git -C /root/truenas-hybrid-cloud-monitoring pull --ff-only origin main
  else
    git clone https://github.com/YICheng-Hao/truenas-hybrid-cloud-monitoring.git /root/truenas-hybrid-cloud-monitoring
  fi
  python3 /root/truenas-hybrid-cloud-monitoring/scripts/setup-monitoring-vm.py
)
```

安裝器逐項詢問實際 IP／網段、AWS 監控憑證、Gmail 應用程式密碼、收件地址、Discord Webhook 與 Grafana 密碼，不必自行修改 Python／YAML／JSON。Tailscale 需要完成登入。私人儲存庫仍需 GitHub 讀取權限。

自動部署四個 Prometheus Job、十個面板、九條告警、繁體中文模板、雙通知聯絡點與預設通知路由。最後將自動產生的 `/root/truenas-cloudsync-postscript.sh` 內容貼到 TrueNAS A 的 Cloud Sync Post-script，執行真實同步，再測試 Email／Discord 收訊。首次真實成功前，Cloud Sync 時間沒有資料是預期狀態。

## 災難情境模擬測試

- [測試 01：VMware 雙碟故障自動告警與 RAID-Z2 復原](docs/raidz2-dual-disk-drill.md)：移除 TrueNAS A 兩顆資料碟、驗證真實通知、掃描兩顆新碟、逐顆 Replace／resilver、核對檔案與恢復通知。含完整實作、截圖清單及結果表；目前為程序，實際演練結果待填。
- [其他災難復原與驗收流程](docs/disaster-recovery-drill.md)：快照復原、B 站接管、S3／Glacier 取回與 RPO／RTO 量測。

## 固定使用的設定

- `scripts/setup-monitoring-vm.py`：全新監測 VM 安裝／唯讀驗證；重跑保留 Receiver Token 與回報檔，拒絕覆寫未受管的既有 VM。
- `scripts/configure-truenas-snmp-stable.py`：選用；在 TrueNAS 執行，建立 SNMP `extend zfs` 成員來源。
- `configs/snmp-zfs-stable.yml`：預設 ZFS 健康與成員模組；與 SNMP Exporter 官方標準模組合併。
- `configs/grafana-alerts-stable.yaml`：安裝器使用的九條告警；`configs/grafana-alerts.yaml` 保持相同內容。
- `configs/grafana-notification-template.tmpl`：繁體中文通知與恢復模板，時間使用 Asia/Taipei。
- `grafana/TrueNAS_Hybrid_Cloud.json`：十面板；沿用已確認正常的 hrStorage 根掛載點容量查詢。
- [面板數值說明](docs/dashboard-panels.md)。

先前的 `deploy-zfs-capacity.py`、`deploy-zfs-members.py`、`configure-truenas-snmp.py` 與 `snmp-zfs-modules.yml` 保留為歷史排錯工具／設定，並非這份從零安裝流程的步驟；不要把它們再套在本流程後面。

## 固定版本與驗證範圍

SNMP Exporter 0.26.0、Prometheus 2.54.1、Grafana 13.2.4。前兩者下載檔使用官方 SHA256 清單驗證；Tailscale 與 AWS CLI v2 從官方管道安裝。

```bash
python3 -m unittest discover -s tests -p 'test_*.py' -v
```

元件回歸測試包含 32 項。完整 VM 與故障／恢復整合測試由 [GitHub Actions](https://github.com/YICheng-Hao/truenas-hybrid-cloud-monitoring/actions/workflows/monitoring-vm-test.yml) 執行；實際輪數、失敗原因與通過範圍記錄於 [安裝測試報告](docs/installation-test-report.md)。外部 NAS、S3、Email／Discord 與 Tailnet 身分採隔離替身，真實 Cloud Sync、跨站連線與外部收訊仍需依教學驗收。

禁止上傳 `/root/monitoring-setup.json`、AWS 憑證、Gmail App Password、Discord Webhook 或 Receiver Token。

Rocky 10 支援修正：依實際主版本選用 Tailscale 官方 RHEL 9／10 軟體源。版本偵測測試涵蓋 Rocky 10.2；完整 VM 驗證狀態以測試報告為準。官方來源：https://pkgs.tailscale.com/stable/ 。安裝命令使用子 Shell，失敗時不會因 `set -e` 結束目前 SSH Shell；已有專案目錄時採快轉更新，不重複 clone。
