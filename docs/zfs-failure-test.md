# 第七章監控驗證與第八章故障測試

本文件配合目前的 `configs/grafana-alerts-stable.yaml` 與十面板 JSON。從零建置請先完成 [監測 VM 安裝](monitoring-vm-from-zero.md)。目前已正常運作的 VM 不必重跑歷史 `deploy-zfs-capacity.py` 或 `deploy-zfs-members.py`；它們不是這份建置流程的後續步驟。

## 1. 先驗證來源與規則

A／B TrueNAS SNMP 附屬參數各保留一條：

```text
extend zfs /usr/sbin/zpool status -P
```

本版容量使用標準 hrStorage，不需要 `zfs_capacity` 或 `zfsUsablePool`。若既有系統另有用途，保留其設定即可。

在監測 VM 執行：

```bash
for NAS_TS_IP in 100.114.236.88 100.113.107.95; do
  snmpget -v2c -c public -t 5 -r 1 "$NAS_TS_IP" \
    1.3.6.1.4.1.8072.1.3.2.3.1.2.3.122.102.115 \
    1.3.6.1.4.1.8072.1.3.2.3.1.4.3.122.102.115
  curl -fsSG http://127.0.0.1:9116/snmp \
    --data-urlencode "target=$NAS_TS_IP" \
    --data-urlencode 'auth=public_v2' \
    --data-urlencode 'module=truenas_zfs' | grep -E '^(zpoolHealthStr|zfsMemberFault|zfsStatusCommandExit)'
done
python3 /root/truenas-hybrid-cloud-monitoring/scripts/setup-monitoring-vm.py --verify-only
```

SNMP 回應應有完整成員表與指令退出碼 0。正常時 `zfsMemberFault` 為 0；表格含異常成員時為 1；無法辨識輸出時為 2。資料缺失不是正常。`--verify-only` 是唯讀檢查，會檢查兩站容量／成員來源、S3 API，以及 Grafana 資料源與九條規則實際評估。

先到 Grafana【Alerting → Contact points】分別測試 Email、Discord 收訊。聯絡點 Test 成功僅證明通知管道可用，仍須完成下列真正的規則觸發與恢復測試。

## 2. 九條規則與等待時間

| 規則 | Pending | 判定內容 |
|---|---|---|
| 節點／S3 監控離線 | 2m | SNMP 採集失敗或 S3 清單 API 失敗 |
| 根掛載點容量超標 | 5m | hrStorage 根掛載點使用率 >85%，不是整池所有資料集用量 |
| 兩站已用空間差異 | 15m | 兩站根掛載點差異 >10 GiB，僅作觀察，不代表複寫失敗 |
| Cloud Sync 成功回報逾時 | 5m | 指定任務超過 28 小時未回報成功 |
| 原生池 DEGRADED | 1m | 原生池健康字串為 DEGRADED |
| 原生池其他異常 | 1m | 有效健康字串不是 ONLINE／DEGRADED |
| 原生池健康資料缺失 | 2m | 預期池無有效健康來源 |
| 成員／VDEV 異常 | 0s | 成員指標為 1，且指令成功、採集在線 |
| 成員狀態無法取得 | 2m | 來源缺失、輸出不明、指令失敗或採集離線 |

群組每分鐘評估，SNMP 每 15 秒採集；通知還受首次 `group_wait=10s`、後續 `group_interval=1m` 與網路影響。Pending 0s 不代表拔除磁碟當下立即收到通知。S3 每 5 分鐘採集，其離線偵測較慢。

## 3. 監控採集離線測試

在監測 VM 暫停 SNMP Exporter：

```bash
systemctl stop snmp_exporter
```

確認 Prometheus `/targets` 兩個 NAS Target 變為 DOWN，面板「採集連線」顯示離線；ZFS 綜合健康應顯示資料不完整，不能顯示 DEGRADED。等待離線／來源缺失規則從 Pending 進入 Firing，確認兩管道收到對應告警名稱，而非 `DatasourceError`。

完成後恢復：

```bash
systemctl start snmp_exporter
systemctl is-active snmp_exporter
```

確認 Target 回到 UP、健康資料恢復，並收到解除通知。若沒有通知，依序查 Target、實際指標、Alert rules 的 Health／State，再查聯絡點與通知政策；不要只修改面板。

## 4. 測試 NAS 的單碟離線與恢復

使用具備備份的測試用 RAID-Z2 NAS。先確認所有成員正常，記錄資料池名稱與欲測磁碟序號；不要選系統碟。每次只測一顆，完成恢復後才進行下一輪。

1. 在 TrueNAS【Storage → 池 → Manage Devices】選定資料成員，使用 Offline 模擬單碟不可用，記錄操作時間。同時在 Windows 11 持續測試 SMB 讀寫並記錄錯誤與時間。
2. 在該 NAS Shell 執行 `zpool status -P`，保存池與成員的實際狀態。以實際輸出為準，不因 VMware 已移除裝置就推定 ZFS 已回報 DEGRADED。
3. 回監測 VM 重跑步驟 1 的 SNMP／Exporter 查詢，確認來源已反映變化，再查看 Prometheus 與 Grafana。
4. 原生池回報 DEGRADED 時，面板顯示「DEGRADED 降級」，對應降級告警應觸發。原生仍 ONLINE、但成員表已有 FAULTED／OFFLINE 等異常時，面板顯示「成員異常／冗餘需檢查」，由成員規則告警，不能強制把它改寫成 DEGRADED。
5. 確認 Grafana 真正進入 Firing，記錄 Discord 與 Email 的告警名稱、節點、觸發／收訊時間。規則的評估錯誤通知不算磁碟故障測試成功。
6. 若只是模擬 Offline 且原磁碟仍健康，於 TrueNAS 對該成員執行 Online，查看是否需要同步；等待實際狀態恢復，再確認面板與兩管道解除通知。

若 TrueNAS 成員表與原生字串都仍為 ONLINE，監控來源尚未回報故障；先核對移除的是正確的測試 NAS／正確磁碟，並執行測試資料的讀寫驗證。不要為了讓畫面出現 DEGRADED 繼續移除其他成員。

## 5. 實際換碟與 Resilver 驗收

實際故障才使用 Replace；替換磁碟須不小於原磁碟，且該動作會清除替換碟上的資料。TrueNAS 的換碟流程會啟動 Resilver；保存開始、完成時間及 `zpool status -P` 輸出。官方步驟見 [TrueNAS 25.04 換碟文件](https://www.truenas.com/docs/scale/25.04/scaletutorials/storage/disks/replacingdisks/)。

Grafana 告警解除只代表告警條件不再成立，不能單憑解除通知宣稱 Resilver 已完成。必須另以 NAS 的掃描／重建結果與成員 ONLINE 狀態確認。Scrub 是另一項巡檢作業，亦應保存實際排程與結果。

SMB 測試期間沒有觀察到中斷時，文件寫「本次測試未觀察到 SMB 服務中斷」，並附觀測方式／時間解析度；不能從 RAID-Z2 容錯能力直接推論所有故障情境的 RTO 固定為 0 秒。

## 6. 本專案內部自動測試的範圍

[安裝測試報告](installation-test-report.md) 記錄真實 Rocky VM 的建置、重跑、重開機與合成故障通知測試。合成 SNMP 測試驗證監控程式如何處理 ONLINE／成員異常／DEGRADED，不代替你的實際硬碟故障、SMB 可用性與 Resilver 驗收。十面板用途與容量口徑見 [面板說明](dashboard-panels.md)。
