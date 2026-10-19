# ZFS 儲存池健康監控與故障演練

## 面板判讀

| 項目 | 回答的問題 | 不代表的意義 |
|---|---|---|
| A／B 空間使用率 | 各站已用空間占總空間的比例 | RAID 健康或複寫完成率 |
| ZFS 儲存池健康狀態 | 預期儲存池是否 ONLINE、DEGRADED 或其他異常 | SMB 端到端可用性及重建進度 |
| 監控採集／API 狀態 | SNMP 或 S3 清單查詢是否成功 | 磁碟一定健康或備份一定成功 |

一顆 RAID-Z2 資料碟離線時，SNMP 仍可回應，因此「採集正常、儲存池 DEGRADED」是合理組合。停止 snmp_exporter 時，應顯示「採集失敗、健康無資料」，不能將舊 ONLINE 當作目前正常。

健康狀態面板使用 zpoolHealthStr 的字串標籤，不假設私有 MIB 的數值 enum。ONLINE 對應 1，DEGRADED 對應 2，其他有回報的狀態對應 3；預期池沒有有效指標或 up 不為 1 時對應 4。3 是本監控面板的分類碼，並非原始 ZFS enum，也不將 OFFLINE、UNAVAIL、SUSPENDED 全部改稱 FAULTED。實際狀態可在 Prometheus 查詢 zpoolHealthStr，或到 TrueNAS 執行 zpool status。

目前預期池為 A 站 mainpool、boot-pool，以及 B 站 backuppool、boot-pool；若池名稱或位址更動，須同步修改面板和告警。健康查詢會移除 nodename 標籤並保留 instance、zpoolName，以穩定比對預期池；通知模板應顯示這兩個標籤。

## 套用設定

1. 先確認 SNMP Exporter 已有 truenas_zfs 模組，並能對兩站回傳 zpoolHealthStr。僅修改 Prometheus 不會自動建立 Exporter 模組。
2. 備份目前 /etc/prometheus/prometheus.yml 及 Grafana 告警設定檔。
3. 將 configs/prometheus.yml 的 truenas_snmp.params.module 更新為包含 truenas_zfs；其餘 IP、9108 目標及客製設定依現場保留。用 promtool check config 驗證後重啟或重新載入 Prometheus。
4. 查詢 zpoolHealthStr{job="truenas_snmp"}，應看到兩站的資料池與 boot-pool。
5. 使用修改後的 grafana/TrueNAS_Grafana面板 JSON 匯入，DS_PROMETHEUS 選擇現有 Prometheus。儀表板 uid 沿用上傳檔，可能更新同 uid 儀表板；請先匯出舊版。
6. 將 configs/grafana-alerts.yaml 複製至目前使用的 /etc/grafana/provisioning/alerting/truenas-alerts.yaml，替換同一份檔案，勿同時留下另一份相同規則 uid 的設定。此檔的 datasourceUid 為 cg15oru9k9clcd，須與現場一致。
7. 重啟 grafana-server，查看 TrueNAS_Alerts 共七條規則，確認現有通知政策仍路由至 Discord／Email，並可送出恢復通知。
8. 容量差異原有配對問題已改為兩站分別 sum 再相減；本指標只是空間差異參考，不驗證資料一致性。Cloud Sync task_id 預設仍為 1，請核對實機。

新增規則：

| 名稱 | 條件 | Pending | 等級 |
|---|---|---|---|
| ZFS 儲存池降級 | 狀態碼等於 2 | 1 分鐘 | warning |
| ZFS 儲存池其他異常 | 狀態碼等於 3 | 1 分鐘 | critical |
| ZFS 健康指標無法取得 | 狀態碼等於 4 | 2 分鐘 | warning |

規則每分鐘評估，SNMP 每 15 秒採集。通知延遲還包含 Pending、網路及 Notification policy 的 group_wait，不能宣稱立即通知。Prometheus 本身不可用時由 Grafana 的 Error／No Data 行為處理；池層級 fallback 不會掩蓋資料源錯誤。

## 通知模板

請在既有 nas.body 的每個 firing／resolved 迴圈加入：

```gotemplate
{{ if .Labels.zpoolName }}儲存池：{{ .Labels.zpoolName }}
{{ end }}{{ if .Annotations.description }}處置說明：{{ .Annotations.description }}
{{ end }}
```

原模板的 instance 位址仍需保留，才能分辨兩站同名的 boot-pool。

## 第八章情境一建議文字

### 單顆或雙顆資料碟故障模擬與 RAID-Z2 復原驗證

本測試以 VMware 中 TrueNAS 的資料虛擬磁碟模擬故障，不宣稱已完成實體硬碟熱抽換。測試前確認資料已有可用備份，核對資料碟與系統碟身分，先執行單碟測試，再於隔離測試環境評估雙碟情境；不對正式資料池製造故障。

1. 基準驗證：確認資料池 ONLINE，從 Windows 11 持續存取測試檔案並記錄時間、錯誤及傳輸表現。B 站若未開啟 SMB，驗證其管理及備份功能，不宣稱有對外 SMB 服務。
2. 故障與預警：模擬單顆資料碟離線，確認同一組 RAID-Z2 VDEV 在容錯範圍內轉為 DEGRADED。監控應呈現「採集可正常回應、資料池降級」，並於規則滿足 Pending 後產生通知。這項測試只證明 DEGRADED 分支；不需要破壞更多磁碟製造 FAULTED。
3. 替換與重建：於 TrueNAS Storage 的目標池裝置管理中定位故障磁碟，準備容量足夠的新磁碟後執行 Replace。替換會清除新磁碟內容，請核對裝置；記錄 resilver 進度、完成時間及錯誤。虛擬環境的新增／移除硬碟須依控制器能力操作，不保證可熱插拔。
4. 復原驗證：重建完成後確認 pool ONLINE、無已知永久資料錯誤，重新核對測試檔案內容／雜湊、服務表現與告警恢復通知。重建期間可能有效能下降或 I/O 延遲，不能保證讀寫完全不受影響。
5. 定期巡檢：另行安排 Scrub，驗證已配置資料的 checksum。只有存在可用冗餘副本時才能自動修復部分錯誤；Scrub 不取代備份，也不等於 resilver。

RAID-Z2 每組 VDEV 可容忍兩顆資料碟故障。兩顆系統碟的 Mirror 僅容忍其中一顆故障，不能將 RAID-Z2 的雙碟容錯套用到 boot-pool。若實測期間未觀察到服務中斷，記為「本次測試未觀察到中斷」並附量測頻率，不預先宣稱 RTO = 0 秒。Resilver 耗時記為冗餘恢復時間，與服務中斷時間分開記錄。

## 驗證範圍

本次使用 Prometheus 2.54.1 promtool 對 ONLINE、DEGRADED、FAULTED、OFFLINE、SUSPENDED、SNMP 採集失敗及健康指標缺失進行七組合成資料測試。另驗證 Prometheus 設定與所有 PromQL 語法。尚未登入實際 Grafana／TrueNAS，未聲稱真實磁碟故障、郵件／Discord 或重建測試已通過。
