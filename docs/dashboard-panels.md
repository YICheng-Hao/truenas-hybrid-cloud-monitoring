# 面板數值說明

本版共十個面板；容量採用 2026-10-19 已確認正常的 hrStorage 查詢。

| 面板 | 意義 |
|---|---|
| A／B ZFS 綜合健康 | 結合 TrueNAS 原生池健康字串與 `zpool status -P` 成員異常指標。池實際 DEGRADED 才顯示 DEGRADED；池仍 ONLINE 但磁碟成員異常時顯示成員異常；缺資料不顯示綠燈正常。 |
| 採集連線／S3 API | 監控端能否取得資料／列舉 S3。連線正常不代表磁碟健康，也不代表備份任務成功。 |
| Cloud Sync 距成功回報 | TrueNAS A 真實 Cloud Sync 成功後回報的時間差。不是 S3 最近一個物件的上傳時間；無檔案變更的成功任務仍可更新此回報。 |
| A 站根掛載點容量 | `/mnt/mainpool` 的已用、可用、總量，三者來自同一個 hrStorage 根掛載點。 |
| B 站根掛載點容量 | `/mnt/backuppool`，與 A 站相同查詢邏輯。 |
| S3 已用容量 | 列舉目前物件大小加總，不含未列出的舊版本等其他計費項目。 |
| S3 儲存費估算（月） | 目前物件容量 × 單一儲存單價，僅為粗估，不是完整 AWS 帳單。 |
| CPU 使用率 | A／B 處理器負載；不是儲存空間使用率。 |
| 記憶體使用率 | A／B Physical memory 的 SNMP 使用率；ZFS ARC 快取也會占用記憶體。 |
| Tailscale 網路流量 | Tailscale 介面的收／送位元組速率；不是整台 NAS 所有網卡總量。 |

根掛載點已用空間不等於整個 ZFS 池的所有子資料集與快照占用量。根資料集本身可能只有幾百 KiB，因此不要把這個數字解釋為整池僅使用幾百 KiB。兩站根掛載點差異只作觀察參考，不能證明 ZFS 複寫成功或失敗；須另外查看 TrueNAS Replication Tasks 與快照。

容量保留實際採集值，不將 RAID-Z2 六顆硬碟的原始容量相加當可用空間，也不硬編碼 2 TB。500 GiB 與 500 GB 是不同容量單位，名目容量還需扣除 ZFS 開銷。

面板由 `/etc/grafana/provisioning/dashboards/truenas.yaml` 載入 `/var/lib/grafana/dashboards/truenas.json`。UI 允許保存調整；再次執行安裝器或更新該檔案時，檔案中的版本會重新套用，持久修改應同步到儲存庫 JSON。
