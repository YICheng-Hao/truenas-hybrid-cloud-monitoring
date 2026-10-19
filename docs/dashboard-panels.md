# Grafana 十個面板用途

| 面板 | 用途 | 判讀限制 |
|---|---|---|
| A／B ZFS 綜合健康 | 同時查看兩站資料池、boot-pool 與成員狀態 | 成員故障定位仍需 zpool status -P |
| 採集連線／S3 API | SNMP 採集與 S3 清單查詢是否成功 | 連得上不代表磁碟健康或備份最近成功 |
| Cloud Sync 距成功回報 | 距 Post-script 成功通知多久 | 不等於已驗證可復原的 RPO |
| A 站 ZFS 資料空間（RAID-Z2） | mainpool 根資料集已用、可用與兩者合計 | 來源 zfs USED／AVAILABLE；有配額的子資料集可用額度可能不同 |
| B 站 ZFS 資料空間（RAID-Z2） | backuppool 根資料集已用、可用與兩者合計 | 兩站配置不同不等於複寫失敗 |
| S3 已用容量 | 物件清單總位元組 | 受 Exporter 更新週期影響 |
| S3 儲存費估算（月） | 依設定費率估算儲存費 | 非帳單，不含所有請求／取回／傳輸費 |
| CPU 使用率 | 各站平均邏輯 CPU 負載 | 不等於 SMB 吞吐量 |
| 記憶體使用率 | HOST-RESOURCES-MIB 記憶體比例 | 包含系統快取，非應用程式細項 |
| Tailscale 網路流量 | tailscale0 收送位元率 | 非延遲或備份完成率 |

## 綜合健康判讀順序

| 優先序 | 顯示 | 條件 |
|---|---|---|
| 1 | 紅色：儲存池異常 | 任一預期池有效狀態非 ONLINE／DEGRADED |
| 2 | 橙色：DEGRADED 降級 | 任一預期池原生回報 DEGRADED |
| 3 | 紅色：成員異常／冗餘需檢查 | 有效表格含成員／VDEV 異常 |
| 4 | 綠色：ONLINE 正常 | 兩個池皆 ONLINE、成員正常、指令成功且採集在線 |
| 5 | 紫色：健康資料不完整 | 資料不足或採集離線 |

池 ONLINE、成員 FAULTED 時顯示紅色成員異常，不偽裝成原生 DEGRADED。原生池真的為 DEGRADED 時才顯示 DEGRADED。

已移除重複的 A／B 空間使用率 Gauge；不再把根資料集的 384 KiB metadata 當成整池用量。需要兩站啟用 extend zfs_capacity，容量才會有資料。容量為資料空間口徑，已使用包含子資料集與快照；總資料空間為 USED＋AVAILABLE，不是含 parity 的原始磁碟加總。

匯入同 UID 並覆寫才會更新既有面板。統計面板查詢採 Instant；CPU、記憶體與流量趨勢採 Range。

若六碟每顆為 500 GB，RAID-Z2 理論資料容量約 2000 GB＝1.82 TiB；若每顆是 500 GiB，則約 2000 GiB＝1.95 TiB。實際可用空間仍以 zfs list 為準。
