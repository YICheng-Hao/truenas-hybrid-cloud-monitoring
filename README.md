# TrueNAS 混合雲災備監控

監測 TrueNAS A／B 的 SNMP、ZFS 健康與磁碟成員，以及 AWS S3 清單和真實 Cloud Sync 成功回報；由 Prometheus 採集、Grafana 顯示與透過 Email／Discord 通知。

## 從零建立監測 VM

請依 [完整複製貼上教學](docs/monitoring-vm-from-zero.md) 操作。這是全新 Rocky Linux 9 x86_64 VM 安裝流程。目前正常運作的舊 VM 不需要執行安裝器。

```bash
sudo -i
dnf install -y git python3 python3-pyyaml
git clone https://github.com/YICheng-Hao/truenas-hybrid-cloud-monitoring.git /root/truenas-hybrid-cloud-monitoring
python3 /root/truenas-hybrid-cloud-monitoring/scripts/setup-monitoring-vm.py
```

安裝器逐項詢問實際 IP／網段、AWS 監控憑證、Gmail 應用程式密碼、收件地址、Discord Webhook 與 Grafana 密碼，不必自行修改 Python／YAML／JSON。Tailscale 需要完成登入。私人儲存庫仍需 GitHub 讀取權限。

自動部署四個 Prometheus Job、十個面板、九條告警、繁體中文模板、雙通知聯絡點與預設通知路由。最後將自動產生的 `/root/truenas-cloudsync-postscript.sh` 內容貼到 TrueNAS A 的 Cloud Sync Post-script，執行真實同步，再測試 Email／Discord 收訊。首次真實成功前，Cloud Sync 時間沒有資料是預期狀態。

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
python3 -m unittest discover -s tests -p 'test_setup_monitoring.py'
```

已測試設定產生、容量查詢來源、九條唯一告警 UID、一分鐘評估週期、雙通知與秘密檔權限；已實際啟動 Grafana 13.2.4 驗證載入九條告警、十面板與 Email／Discord 聯絡點。未聲稱已在全新 Rocky VM 完成整套系統級安裝測試；實際 Cloud Sync 與通知收訊須依教學驗收。

禁止上傳 `/root/monitoring-setup.json`、AWS 憑證、Gmail App Password、Discord Webhook 或 Receiver Token。
