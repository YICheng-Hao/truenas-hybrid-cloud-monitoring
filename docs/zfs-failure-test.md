# 第七章監控修正與第八章磁碟故障驗證

## 漏報原因

2026-10-19 實測截圖顯示 A 站 mainpool 與 raidz2-0 仍回報 ONLINE，但兩顆成員已 FAULTED，並有持續 I/O 錯誤。SNMP 的 zpoolHealthStr 也回傳 ONLINE，原先只檢查池狀態的規則因此無法觸發。此為本次觀察，不推定所有版本均有相同行為。

修正後同時使用原生池健康字串及 Net-SNMP extend 的完整成員狀態；成員告警獨立於池狀態。不要為了取得 DEGRADED 字樣繼續移除磁碟。

## 7.1 A、B 兩站新增 SNMP 資料來源

分別登入兩站 TrueNAS：【System／系統設定 ➔ Services ➔ SNMP ➔ Edit】，在「附屬參數／Auxiliary Parameters」保留其他設定，確保以下每個名稱僅出現一次：

```text
extend zfs /usr/sbin/zpool status -P
extend zfs_capacity /usr/sbin/zfs list -Hp -o name,used,available
```

儲存後，關閉再開啟該站 SNMP 服務。不要直接編輯由 TrueNAS 產生的 snmpd.conf。兩條指令只讀取狀態，不變更池配置。

由 Rocky Linux 監控 VM 驗證兩站：

```bash
for NAS_TS_IP in 100.114.236.88 100.113.107.95; do
  snmpget -v2c -c public -t 5 -r 1 "$NAS_TS_IP" \
    1.3.6.1.4.1.8072.1.3.2.3.1.2.3.122.102.115
  snmpget -v2c -c public -t 5 -r 1 "$NAS_TS_IP" \
    1.3.6.1.4.1.8072.1.3.2.3.1.2.12.122.102.115.95.99.97.112.97.99.105.116.121
done
```

第一項應有完整成員表，第二項應有資料池根資料集名稱與 USED、AVAILABLE 兩個數值。No Such Instance 表示對應 extend 未生效，不代表磁碟正常。查詢 IP 必須與實際修改的 TrueNAS 相同。

## 7.2 更新現有監控 VM

以 root 執行。fetch 與 git show 不會切換本地工作分支：

```bash
(
set -e
dnf install -y python3-pyyaml
git -C /root/truenas-hybrid-cloud-monitoring fetch origin main
git -C /root/truenas-hybrid-cloud-monitoring show \
  FETCH_HEAD:scripts/deploy-zfs-members.py > /root/deploy-zfs-members.py
python3 /root/deploy-zfs-members.py
)
```

腳本備份 SNMP、Prometheus 及現有告警 provisioning 檔，補入 truenas_zfs 指標，保留其他 SNMP 模組與實機 Prometheus 目標，新增兩條成員規則。會執行 Exporter dry-run、promtool、A 站指標檢查與 Grafana 啟動健康檢查。失敗時還原備份設定並重新啟動服務。備份位置為 /root/zfs-member-backup-時間戳記。

增量腳本不改寫 Dashboard、通知模板或通知政策；會將既有 UID alert_zfs_pool_cap_high 的容量規則更新成 USED／(USED＋AVAILABLE)。現有 4＋3＋2 條可繼續分檔載入，不要再額外載入整合九條的 configs/grafana-alerts.yaml。全新部署可選整合檔，但不能再同時載入相同 UID 的分檔規則。整合檔與增量更新均以根資料集 USED／(USED＋AVAILABLE) 判斷容量門檻。

新增檔案為 /etc/grafana/provisioning/alerting/zfs-member-alerts.yaml，群組 zfs_members_1m。每分鐘評估；故障 Pending 0 秒、資料缺失 Pending 2 分鐘。傳送時間另受通知政策 group_wait／group_interval 影響，不能將 Pending 0 秒稱為零延遲。

| 指標 | 內容 |
|---|---|
| zpoolHealthStr | TrueNAS 原生池健康字串 |
| zfsMemberFault | 0：正常表格；1：表格列含 DEGRADED／FAULTED／UNAVAIL／OFFLINE／REMOVED／SUSPENDED；2：無法辨識輸出 |
| zfsStatusCommandExit | zpool status 退出碼；0 才能採信成員結果 |
| zfsUsablePoolUsedBytes | 池根資料集 USED，包含子資料集與快照 |
| zfsUsablePoolAvailableBytes | 池根資料集 AVAILABLE，反映尚可使用的資料空間 |

面板總資料空間＝USED＋AVAILABLE，不再以含 parity 的 zpool SIZE 表示資料可用容量。

成員指標為主機層級，不帶個別磁碟／池標籤，故障定位仍需 zpool status -P。容量解析預設每站僅有一個 mainpool 或 backuppool；同站有多個相符池時，需改為逐池指標。

舊自訂 zpoolHealth 指標曾錯接 TRUENAS-MIB zpoolEntry 第 7 欄；它是寫入位元組累計，不是健康數值。不能用該大數值判斷健康或宣稱健康 enum 溢位。本次腳本移除此錯誤指標，保留 zpoolHealthStr。

## 7.3 匯入面板

1. 下載 grafana/TrueNAS_Hybrid_Cloud.json。
2. Grafana【Dashboards ➔ New ➔ Import ➔ Upload dashboard JSON file】上傳，資料源選現有 Prometheus。
3. 保留 UID truenas321-capacity-cloudsync-vm，選 Overwrite 覆寫既有面板，避免保留兩份。
4. 確認標題為「TrueNAS 混合雲｜ZFS 成員・容量・備份監控」，共 10 個面板，舊 A／B 使用率 Gauge 已移除。

GitHub JSON 更新不會自動更新 Grafana 資料庫。Dashboard、告警 provisioning 與通知模板為獨立設定。面板用途與容量口徑見 [dashboard-panels.md](dashboard-panels.md)。

## 7.4 九條規則

| 規則 | Pending | 意義 |
|---|---|---|
| 節點／S3 監控離線 | 2m | 採集或 S3 查詢失敗 |
| 容量超標 | 5m | 根資料集 USED／(USED＋AVAILABLE) >85% |
| 兩站已用空間差異 | 15m | 舊有參考規則；差異不等於複寫失敗 |
| Cloud Sync 成功回報逾時 | 5m | task_id=1 超過 28 小時未回報成功 |
| 原生池 DEGRADED | 1m | 池字串為 DEGRADED |
| 原生池其他異常 | 1m | 池字串非 ONLINE／DEGRADED |
| 原生池健康資料缺失 | 2m | 預期池無有效狀態 |
| 成員／VDEV 異常 | 0s | 成員指標=1、指令成功且採集在線 |
| 成員狀態無法取得 | 2m | 資料缺失、解析／指令失敗或採集離線 |

資料源 UID 範例 cg15oru9k9clcd、Cloud Sync task_id 範例 1，需依實機核對。模板應保留 instance，才能辨識兩站；通知恢復不直接等於已完成 resilver。

通知模板原始碼另存於 configs/grafana-notification-template.tmpl，供文件與重建參考。它是貼到 Grafana Notification templates 介面的 Go template，不是直接放入 provisioning/alerting 的 YAML。聯絡點 Title／Subject 使用 {{ template "nas.title" . }}，Message／Body 使用 {{ template "nas.body" . }}。現場已能收到通知者不必為了更新面板重建聯絡點。時區格式使用 Grafana 官方支援的 tz／date 函式：https://grafana.com/docs/grafana/latest/alerting/configure-notifications/template-notifications/reference/

## 8.1 資料虛擬磁碟故障與復原驗證

1. 基準：記錄 zpool status -P、Windows 11 檔案讀寫、服務回應及可用備份。核對資料碟與系統碟身分。
2. 故障：於隔離 VMware 測試環境先驗證單碟；已出現兩顆 FAULTED 時停止增加故障。
3. 判讀：分別保存池與成員證據。若池 ONLINE、成員 FAULTED，記錄實際結果，應顯示紅色成員異常並通知；只有原生回傳 DEGRADED 才記為池 DEGRADED。
4. 通知：記錄故障、採集、Grafana Firing、Discord 與 Email 到達時間，分別驗證各管道。採集正常與成員故障可同時成立。
5. 替換：於 TrueNAS 目標池裝置管理定位故障碟，核對容量足夠的新磁碟後 Replace。替換會清除新磁碟；熱插拔支援依實際 VMware 控制器判斷。
6. 復原：記錄 resilver 進度／完成時間、池與成員狀態、永久資料錯誤，以及測試檔案雜湊與讀寫結果。
7. 巡檢：另行排程 Scrub 檢查 checksum；只有存在可用冗餘時才可能修復對應錯誤。Scrub 不取代備份或 resilver。

RAID-Z2 每個 VDEV 容忍兩顆資料碟故障；雙系統碟 Mirror 僅容忍一顆系統碟故障。未觀察到中斷時記錄量測頻率及結果，不預先宣稱 RTO=0 秒。B 站不提供 SMB 時驗證備份與管理功能即可；重建時間與服務中斷時間分開記錄。

## 驗證紀錄

先前截圖確認 A 站 zfsMemberFault=1、zfsStatusCommandExit=0，Discord 收到成員異常；B 站當時收到成員資料缺失。19:35 後續截圖已顯示兩站綜合健康與採集正常。未宣稱 Email、硬碟替換、resilver 或還原通過。

新版容量與 Dashboard 已進行 SNMP Exporter 0.26.0 dry-run、PromQL 語法及合成狀態測試；仍需實機啟用 zfs_capacity、更新腳本並匯入面板。測試不操作實際磁碟。

## 從零重建

完整的新 VM 建置順序與設定彙整，見 [monitoring-vm-from-zero.md](monitoring-vm-from-zero.md)。新主機只載入整合九條規則；容量使用 zfs 根資料集 USED／AVAILABLE，額外考量 quota、reservation 與 ZFS 保留空間。

## 既有 VM：容量更新被成員檢查阻擋

若完整部署腳本出現 `A site did not return zfsMemberFault; changes will be rolled back`，代表更新已還原。此時新版 Dashboard 查詢 zfsUsablePool，但採集端仍可能是舊 zfsDataPool，故容量無資料。不要重新匯入相同 JSON 或繼續等待採集。

先確認 A、B 兩站 SNMP 附屬參數同時保留兩行，每個名稱各一次，儲存並重啟該站 SNMP：

```text
extend zfs /usr/sbin/zpool status -P
extend zfs_capacity /usr/sbin/zfs list -Hp -o name,used,available
```

之後在 Rocky 監控 VM 以 root 執行容量專用更新：

```bash
(
set -e
git -C /root/truenas-hybrid-cloud-monitoring fetch origin main
git -C /root/truenas-hybrid-cloud-monitoring show \
  FETCH_HEAD:scripts/deploy-zfs-capacity.py > /root/deploy-zfs-capacity.py
python3 /root/deploy-zfs-capacity.py
)
```

此腳本只增加／更新 SNMP Exporter 的容量解析與相應 GET OID，保留其他指標及既有告警。不檢查成員指標作為容量部署前提，不改 Prometheus 目標，不重啟 Grafana，也不把缺少的健康資料當正常。兩站容量數值皆實際讀取成功才保留更新；任一站失敗時輸出該站容量原始回覆並還原 Exporter 設定。

應看到 A、B 各自的 USED、AVAILABLE、合計 TiB，及「兩站容量指標均已實際讀取成功」。此後等待下一次 15 秒採集並重新整理目前面板即可；無須再換 JSON。若有錯誤，保留腳本的完整輸出判讀，勿宣稱已完成。

容量專用腳本不修改容量門檻規則；若需要更新舊容量告警，應於成員來源確認後完成整合部署，或依 configs/grafana-alerts.yaml 的 alert_zfs_pool_cap_high 設定更新。從零建置的整合九條規則已使用新版資料容量。

本修正另以真正的 snmp_exporter 0.26.0 連到本機模擬 SNMP 回覆，確認 A／B 根資料集數值可輸出、子資料集不重複計算、舊五欄 zpool 格式不被誤認成資料容量。測試程式為 tests/snmp-capacity-smoke.py；這不代表遠端 TrueNAS 設定已自動生效。

若原始 SNMP 回覆仍為「名稱＋SIZE／ALLOC／FREE／CAP 四個數值」，即證明該站仍執行舊 zpool 命令；請先修正 NAS 端，再重跑容量部署，不能只更新 VM。正確的 zfs 命令回覆為「名稱＋USED／AVAILABLE 兩個數值」。

需要直接修正 TrueNAS 25.10 設定時，可在該 NAS 以 root／sudo 執行 scripts/configure-truenas-snmp.py。腳本先確認本機有 mainpool 或 backuppool、備份原附屬參數，再透過 snmp.update 保存兩個 extend，保留其他選項、移除同名重複命令，最後重啟 SNMP 並讀回設定。此腳本必須分別在 A、B TrueNAS 執行，不是在 Rocky 監控 VM。來源設定 API：https://api.truenas.com/v25.10/api_methods_snmp.update.html 。
