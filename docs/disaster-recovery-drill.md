# 災難復原演練與驗收記錄

對應 Word 第八章。本文保存完整操作順序與驗收方式；尚未附實測時間、日誌及檔案核對結果的項目均為演練規劃，不代表已驗證的 RPO／RTO。本文不會自動操作 NAS。

## 1. 演練前準備

- 使用測試資料集與測試檔案，記下大小、SHA-256、ACL、快照名稱及建立時間。
- 確認 A 的本地快照、B 的已接收快照、S3 的實際物件可讀；把加密金鑰、NAS 設定備份與應變聯絡資料離線保管。
- 記錄各 VM、資料碟與開機碟序號。磁碟故障模擬只在隔離測試環境進行；不要把資料碟誤認為開機 Mirror。
- 量測基準時間使用同一時區並確認時鐘同步。開始、告警接收、資料可用及恢復保護的時間分開記錄。
- B 平時不提供員工 SMB；接管時才確認或建立所需帳號、群組、共用與路由。複寫資料集不代表 NAS 使用者、SMB 設定會自動一起複寫。

## 2. 雙碟故障自動告警與 RAID-Z2 復原

對應 Word **8.1**。情境為在 VMware 移除 TrueNAS A 同一組 RAID-Z2 的**兩顆資料碟**，確認主動告警，再加入兩顆新碟、逐顆 Replace／resilver 並驗收資料與恢復通知。

請由 [災難情境模擬測試 01：雙碟故障完整實作流程](raidz2-dual-disk-drill.md) 開始，內含：

1. VMware VMDK／device node 與 NAS 序號／成員 GUID 對照，避免誤動開機 Mirror。
2. Windows SMB 測試檔與故障前、降級期間、重建後的 SHA-256／讀寫驗證。
3. VMware 移除兩顆資料碟、關機離線與開機後 DEGRADED 的分開記錄。
4. Grafana 降級／成員異常規則、Prometheus 唯讀查詢、Email／Discord 真實告警。
5. 加入兩顆新 VMDK、TrueNAS SCSI／udev 掃描與 disk.sync_all。
6. 第一顆重建完成後仍 DEGRADED，再替換第二顆，直到 pool／成員 ONLINE。
7. 規則 Normal、雙管道恢復通知、時間表、D01–D14 截圖與通過標準。

RAID-Z2 的兩碟容錯是每組 VDEV；兩顆開機 Mirror 不適用此雙碟移除流程。關機操作包含計畫性停機，不宣稱全程不中斷。上述文件是測試程序，**實際雙碟演練結果仍待填寫**；單碟測試或既有替身測試不能代替本輪。

## 3. 誤刪或勒索加密

### 單一檔案：先 Clone 再取回

1. 記下被刪檔案及最後正常時間，選擇事故前的有效快照。
2. 在 A 的「資料集 → 快照」選擇 Clone to New Dataset，命名如 `mainpool/data_recovery`；UI 名稱依版本確認。
3. 由管理員核對 Clone 內檔案的時間、內容與雜湊，再只複製需要的檔案回原資料集，檢查擁有者及 ACL。
4. 使用者驗證完成且不再需要臨時副本後，才清理 Clone。

### 大範圍感染：隔離後評估 Rollback

1. 隔離受感染用戶端並暫停受影響 SMB 存取，避免持續寫入；保留事件所需證據。
2. 核對事故前快照，確認快照後的新資料及較新快照／Clone 相依性，暫停可能傳播異常資料的同步。
3. 優先在 Clone 驗證可恢復內容。只有確認影響範圍且取得維運決策後，才對正式資料集執行 Rollback。
4. Rollback 會失去所選快照之後的資料變更，也可能影響較新快照及後續增量複寫；不要把 UI 完成時間當作整體服務 RTO。
5. 核對檔案、權限、乾淨用戶端存取與備份鏈後恢復服務。不是所有 ransomware 情境都能僅靠 Rollback 解決。

依據：[TrueNAS 25.10 snapshot rollback API](https://api.truenas.com/v25.10/api_methods_pool.snapshot.rollback.html)。

## 4. A 站離線後由 B 接管

1. 記錄 A 離線與雙管道告警時間。確認是 A 故障或跨站網路問題，並隔離 A 的寫入端，避免兩站同時提供可寫服務。
2. 暫停原 A→B 複寫排程，核對 B **實際最後接收快照**及其建立時間，而不只看最後任務 SUCCESS。
3. 以安全保管的對應資料集金鑰解鎖 `backuppool/backup_snapshot`，驗證檔案內容。金鑰檔名稱依實際匯出結果，不硬寫成固定檔名；解鎖不是自動重建 SMB 服務。
4. 優先從已核對快照建立可寫 Clone 作為應急服務，保留原備份。如果直接將接收資料集改可寫，須明確記錄其與後續複寫的衝突。
5. 在 B 準備使用者／群組的 UID/GID、ACL、SMB 共用與服務，確認防火牆、DNS／路由及用戶端連線路徑。NAS 資料集屬性與檔案 ACL 不等於 TrueNAS 系統帳號設定。
6. 由 A 站的乾淨 Windows 測試端經路由或 Tailscale 連入 B 的應急共用，驗證讀寫與群組權限。B 站本地測試端可以作為演練工具，不需對一般員工常態開放。
7. A 修復後，先在 B 保存新異動快照，確認最新資料來源、接收端與增量基準，再規劃回切。先回傳到 A 的驗證資料集，核對後切換用戶端；避免直接覆寫唯一最新副本。
8. 恢復原排程、B 唯讀保護及金鑰管理，另驗證新一輪複寫成功。若 Clone 已使用，清理前先確認資料都已轉回。

B 未載入金鑰屬加密鎖定狀態，不以「零知識」代表整個系統管理員無法改動。PULL、關閉 B 的 SSH 與分離憑證可縮小風險，但不代表 B 絕對不可刪除或竄改。

## 5. 從 S3 與封存類別復原

1. 新建 NAS／目標資料集並確認可用空間。使用具目標 bucket `s3:ListBucket` 與物件 `s3:GetObject` 的還原身分；本專案僅有 ListBucket 的**監控金鑰不能下載還原**。
2. 檢查待還原物件的 StorageClass 及版本。Lifecycle 是依物件條件處理；COPY 與未授予 DeleteObject 不保證保留歷史版本，未啟用版本控制時不能取回已被覆寫的舊內容。
3. 物件為 S3 Standard 時，可直接建立 Cloud Sync **PULL＋COPY** 任務，先拉回空白測試資料集；不要修改原有日常 PUSH 任務來試驗還原。
4. 物件為 Glacier Flexible Retrieval／Deep Archive 時，還原身分還需 `s3:RestoreObject`，對指定物件發起取回，完成後才可下載。不要使用監控使用者的金鑰去做解凍。
5. 如有 SSE-KMS、版本控制或額外 bucket policy，還需核對相應 KMS、版本或其他有效權限。本專案原設計為 SSE-S3。

單一物件的 CLI 範例（在已配置**還原憑證**的管理終端機執行，替換 bucket／key／region；不把金鑰寫進命令）：

```bash
aws s3api head-object \
  --bucket truenas-backup-myhome-2026 \
  --key "important_project.zip" --region ap-east-2

aws s3api restore-object \
  --bucket truenas-backup-myhome-2026 \
  --key "important_project.zip" --region ap-east-2 \
  --restore-request '{"Days":7,"GlacierJobParameters":{"Tier":"Standard"}}'

aws s3api head-object \
  --bucket truenas-backup-myhome-2026 \
  --key "important_project.zip" --region ap-east-2 \
  --query '{StorageClass:StorageClass,Restore:Restore}'
```

`restore-object` 是單一物件操作，不是整個資料夾遞迴解凍。大量物件應規劃清單與 S3 Batch Operations。對已可立即存取的物件不需發出 RestoreObject。

| 類別 | Expedited | Standard | Bulk |
|---|---|---|---|
| Glacier Flexible Retrieval | 通常 1–5 分鐘（小於 250 MB），受容量與費用條件影響 | 通常 3–5 小時 | 通常 5–12 小時 |
| Glacier Deep Archive | 不提供 | 通常 12 小時內 | 通常 48 小時內 |

以上為 AWS 一般取回說明，不含本地下載、權限重建與驗證，亦非端到端 RTO 保證。大量資料／大物件可能更久；暫時副本及請求、取回與傳輸費另計。依據：[AWS archive retrieval options](https://docs.aws.amazon.com/AmazonS3/latest/userguide/restoring-objects-retrieval-options.html)。

6. 解凍完成且尚在暫時副本有效期限內，執行新建的 Cloud Sync PULL 任務，核對日誌與下載檔案 SHA-256、數量及抽樣開啟結果。
7. S3 的一般檔案同步不等於 ZFS 快照複寫，須另核對 ACL、擁有者及 SMB 配置；完成驗證後才接回正式服務。

## 6. RPO／RTO 記錄表

- 實際 RPO：事故時間減「可用還原點的資料時間」，不可只用排程頻率代替。
- 實際 RTO：事件開始至「指定服務通過可用性與權限驗證」的時間。另記磁碟 resilver、封存取回等階段時間。
- 每日快照 18:00、B 複寫 18:30、S3 同步 19:00 為本專案既有排程；前次失敗或未完成時，資料落差可能超過一天。
- 保留原規劃的本地復原 1 分鐘、B 接管 15 分鐘，可列為**待驗證目標**；沒有實測紀錄不寫成已達成數值。硬碟容錯不等於 RTO 必為 0。
- 未做分層容量、取回頻率、流量及帳單比較時，不宣稱省下固定 70% 成本。

| 情境 | 事故時間 | 還原點／資料時間 | 告警收訊時間 | 服務通過時間 | RPO | RTO | 檔案／ACL／日誌證據 |
|---|---|---|---|---|---|---|---|
| 雙資料碟故障 | 待填 | 待填 | 待填 | 待填 | 待量測 | 待量測 | 待補 |
| 誤刪／加密 | 待填 | 待填 | 待填 | 待填 | 待量測 | 待量測 | 待補 |
| B 站接管 | 待填 | 待填 | 待填 | 待填 | 待量測 | 待量測 | 待補 |
| S3／封存復原 | 待填 | 待填 | 待填 | 待填 | 待量測 | 待量測 | 待補 |

Word 圖 8-1 至 8-4 分別保留磁碟故障／重建、快照復原、B 接管、S3 PULL 驗證的關鍵證據；其餘截圖與完整日誌放於此文件的演練紀錄，不在尚未提供時宣稱已完成。
