# 企業級 NAS 與儲存安全管理方案 — 混合雲監控中心

本專案收納 TrueNAS A／B、AWS S3、Prometheus 與 Grafana 的監控程式及第七、八章操作設定。

從零開始重建 Rocky Linux 9 監控 VM，請依 [完整建置指南](docs/monitoring-vm-from-zero.md) 的 7.1～7.12 順序操作。指南已彙整套件、Tailscale、兩站 SNMP、S3 IAM、Receiver Token、Prometheus、Grafana、九條告警、十面板及雙管道通知驗證。

目前預設 Dashboard 的兩個容量面板已還原為原先 hrStorage 根掛載點查詢，讓現有主機恢復使用既有資料來源；其餘健康與採集面板未改動。匯入同 UID 並覆寫即可，不需要執行容量更新腳本。掛載點已用可能只反映根資料集自身，不能稱為含全部子資料集與快照的整池用量。

zfs USED／AVAILABLE 採集流程仍保留在程式與從零指南中，但現場 NAS 持續回傳舊 zpool 格式，尚未確認此新流程在使用者兩站成功。約 3 TB 的 zpool 原始容量也不能直接稱為 RAID-Z2 可用資料容量；暫不要求為了恢復顯示繼續變更 NAS 設定。

既有 VM 只修容量顯示時，使用 [容量專用更新腳本](scripts/deploy-zfs-capacity.py)，步驟見 [容量故障排除](docs/zfs-failure-test.md#既有-vm容量更新被成員檢查阻擋)。它不依賴成員指標、不改告警、不重啟 Grafana，會驗證兩站容量後才保留更新。完整 deploy-zfs-members.py 的成員檢查失敗時會還原設定，不代表新容量已完成部署。

NAS 回覆仍為舊四數值格式時，先修正該 NAS 的 extend 命令；可使用 [TrueNAS 端設定腳本](scripts/configure-truenas-snmp.py)，須分別在 A、B 的 TrueNAS 本機執行，不能在 Rocky 執行。

## 2026-10-19 成員故障監控修正

實測出現「mainpool 整體仍 ONLINE，但兩顆成員磁碟已 FAULTED」。單靠 zpoolHealthStr 會漏報，因此加入 SNMP extend 成員狀態採集。使用者截圖確認 A 站指標為 1，Discord 收到成員異常通知；B 站則收到成員狀態無法取得通知。尚未確認 Email、磁碟更換及重建完成。

19:35 的後續截圖已顯示兩站綜合健康與採集正常；此畫面不單獨證明硬碟替換或 resilver 已完成。本版另修正容量口徑，需更新兩站的 zfs_capacity 命令與監控 VM 的模組，再匯入新版面板。

- [部署步驟與技術文件修訂](docs/zfs-failure-test.md)
- [十個面板用途與狀態對照](docs/dashboard-panels.md)
- [可直接匯入的 Grafana JSON](grafana/TrueNAS_Hybrid_Cloud.json)
- [成員與容量增量部署腳本](scripts/deploy-zfs-members.py)
- [SNMP ZFS 模組參考設定](configs/snmp-zfs-modules.yml)
- [完整九條告警規則](configs/grafana-alerts.yaml)
- [僅新增兩條成員告警](configs/grafana-zfs-members.yaml)
- [繁體中文通知模板原始碼](configs/grafana-notification-template.tmpl)

現有監控 VM 使用增量部署流程，不要重跑 install.sh；該安裝腳本會重新產生 Cloud Sync Token。完整九條規則與分開部署的規則檔不能同時載入相同 UID。

| 目錄／檔案 | 用途 |
|---|---|
| exporters/s3_realtime_exporter.py | S3 清單容量與月費估算，9107 |
| exporters/cloudsync_success_receiver.py | Cloud Sync 成功回報與指標，9108 |
| systemd/ | 監控服務單元 |
| configs/prometheus.yml | 四個採集工作；truenas_snmp 包含 truenas_zfs |
| configs/grafana-datasource.yaml | Prometheus UID cg15oru9k9clcd |
| grafana/ | 十面板 JSON；舊無副檔名路徑保留為相同新版內容 |
| aws-iam/ | S3 唯讀監控政策 |
| tests/ | PromQL 狀態測試與 SNMP 文字解析測試 |

本次監控修正僅讀取 ZFS 狀態，不執行 offline、clear、replace 或 scrub。憑證、Token、Webhook 與密碼不應提交到儲存庫。
