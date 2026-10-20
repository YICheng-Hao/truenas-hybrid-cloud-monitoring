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

## 4. A 站離線與異地備份緊急取回

對應 Word **8.2**。本情境由 **IT 協助取回急用資料**，不再要求 A 站全體員工跨站連入 B 工作。B 平時維持備份用途，事故時只在 B 站內部臨時提供唯讀 SMB，交付出去的副本才供指定負責人修改。

**驗證範圍：**只模擬 TrueNAS A 停機，B、兩台 Gateway、監控 VM 與測試 Windows 保持運作。不是整個 A 據點斷電、全公司跨站接管或自動容錯切換。以下為操作與驗收程序；未附本輪證據的項目仍為待驗證，不宣稱已完成全流程實測。

### 操作位置與演練前準備

| 設備／位置 | 本專案位址或路徑 | 本次用途 |
|---|---|---|
| W11_A | 192.168.1.50/24；Gateway 192.168.1.1 | 驗證 A 共用失效、接收交付副本、負責人暫時工作 |
| TrueNAS A | 192.168.1.100；mainpool/data | 原正式資料與 SMB；修復後維持原資料集與共用路徑 |
| Gateway_VM_HQ | 內網 192.168.1.1 | 原 A 對外連線；不為本次緊急取回新增員工跨站 SMB 通道 |
| TrueNAS B | 10.10.10.100；backuppool/backup_snapshot | 解鎖備份、建立臨時 Clone 與唯讀共用 |
| W11_B | 10.10.10.50/24；Gateway 10.10.10.1 | IT 在 B 站內網取回檔案 |
| Gateway_VM_B | 內網 10.10.10.1 | 原 B 對外連線，演練時保持運作 |
| 監控 VM | 192.168.23.159；Tailscale 100.82.30.20 | Grafana 與 Email／Discord 告警 |

開始前先核對現場位址。W11_B 是 B 站測試 Windows，不是 Gateway VM，也不是員工 W11_A。NAS 管理網頁先使用 **B 現有的 truenas_admin**，不能假設 A 的 itadmin 已自動出現在 B。

1. 先以測試專案資料夾演練，建立可辨識的文件內容並截圖。完成 A 快照與 B 複寫，核對 B 確實收到包含該文件的快照。
2. 記錄 A 原正式 SMB 名稱、路徑、備份任務與排程。確認 B 備份、NAS 設定及對應金鑰可用；金鑰保存在 NAS 以外，不放 GitHub 或截圖。
3. 事先準備 B 的 **SMB 取回帳號**與所需資料讀取權限。Web UI 管理員不等於 SMB 使用者；不授予取回帳號管理員或 sudo 權限，也不必在 B 建立全公司的帳號。
4. 本次可使用已建立的 baylen 作為取回測試帳號，UID=3000、主要群組 executives／GID=3000，啟用 SMB Access。共用設唯讀，即使該帳號原有檔案寫入權限，也不允許透過此共用改寫資料。正式環境應使用專用 IT 取回帳號，不共用員工密碼。
5. 若使用其他帳號，依第 5.5–5.8 節預先建立及驗證，只授權所需範圍。不能因無權限就把整份備份改成所有人可讀寫。

**本環境金鑰的準備方式：**A 的 mainpool/data 顯示「Unlocked by parent」，須在 **A → 資料集 → mainpool → 加密 → Export Key** 匯出來源金鑰。保留原檔，複製一份 JSON，在副本中只將冒號左側的 `mainpool` 改為 `backuppool/backup_snapshot`，右側金鑰不變，另存為 `B-backup_snapshot-key.json`。記事本存檔類型選「所有檔案」，避免變成 .json.txt。這是來源金鑰對應目的資料集名稱，不是產生或更換金鑰；不適用於另外重新加密或已換金鑰的備份。演練前在 B 實際驗證可解鎖。

若 B 的 executives 誤建為 GID 3001，GID 不能在編輯頁直接修改。先以 `getent group 3000` 確認 3000 未被占用，再將舊群組更名 executives_old，新增 executives／3000，最後把 baylen 主要群組切到新 executives；不要猜編號或直接改整份備份 ACL。在 **B Shell** 核對：

```bash
zfs list -o name,mountpoint backuppool/backup_snapshot
id baylen
getent group executives
```

預期顯示 B 備份資料集，且 baylen 包含 uid=3000、gid=3000(executives)。兩台 NAS 都可能顯示 hostname truenas，需用資料集及管理 IP 確認操作位置。

### 1. 關閉 A 站並確認告警

1. **B 管理網頁：**記錄最後收到的快照名稱與資料時間，暫停原 PULL 複寫的自動執行／排程，保留原任務設定。
2. **VMware：**關閉 TrueNAS A，保持 B、Gateway、監控與 Windows 運作。記錄採正常關機或其他故障模擬方式；正常關機不寫成已驗證突然斷電。
3. **W11_A：**確認原 A 共用無法存取。
4. **監控：**保存 Grafana A 離線狀態、Email 與 Discord 實際收訊時間。通知可能受採集、規則評估、持續時間與通知等待影響，不預填保證秒數。

**截圖 E01：**A VM 關閉、W11_A 原共用失敗、Grafana／Email／Discord 告警，可合併成一組。

### 2. 確認員工急用的資料

員工提供專案名稱、原資料夾相對路徑與檔名，IT 確認是否有權取用，再記錄取回範圍、來源快照時間、交付對象及交付時間。

每個專案指定一位負責人保管暫時工作版本。本輪可選一個「緊急取回測試」資料夾，內放「專案進度.txt」；原始內容填入可辨識文字，交付後由負責人新增「A 故障期間的工作更新」，作為交回驗證。

只取出所需資料，不直接交付整個公司資料集。可取回的內容以 B 的實際快照為準，尚未備份的最新變更不能憑此流程恢復。

### 3. 在 B 解鎖備份並建立臨時唯讀共用

**操作位置：B 管理網頁；管理員 truenas_admin。**

1. 選取 backuppool/backup_snapshot。若為 Locked，按 Unlock，上傳已驗證的 B-backup_snapshot-key.json，不勾「強制」，確認 Unlocked。已解鎖時不用重鎖再解。
2. 若顯示 Please specify key，核對 JSON 左側是否為完整目的路徑；Invalid Key 則核對來源金鑰，不靠強制或任意改檔名解決。
3. 在 View Snapshots 選事故前的可用快照，記錄名稱與時間，按 **Clone to New Dataset**。
4. 父層選 backuppool，名稱 takeover_work，完整資料集為 **backuppool/takeover_work**。若同名 Clone 已存在，先核對其來源與用途，不覆寫或刪除。
5. 在 **B Shell** 檢查：

```bash
sudo zfs get origin,readonly,mounted,mountpoint backuppool/takeover_work
```

確認 origin 為選定備份快照、mounted=yes、mountpoint=/mnt/backuppool/takeover_work。Clone 用量很小可能是共用快照區塊，不代表檔案只剩幾百 KiB。原 backup_snapshot 保持備份與唯讀保護，不對原備份執行 Rollback。

6. 在 **B → 共用 → Windows Shares（SMB）→ 新增** 設定：

| 欄位 | 設定 |
|---|---|
| Path | /mnt/backuppool/takeover_work |
| Name | takeover_work |
| Purpose | Default Share |
| Enabled | 勾選 |
| Read Only／Export Read Only（依介面於進階選項尋找） | 啟用 |
| 存取範圍 | 僅授權 IT 取回帳號及 W11_B；不要開 guest 或全公司權限 |

啟動 B SMB，記錄原服務狀態；臨時使用不需設定永久自動啟動。先保留既有檔案 ACL，不按 Strip ACL 或遞迴放寬原備份權限。依 share ACL、有效防火牆／存取規則限制本次來源與帳號；若已有寬鬆 Tailnet ACL 或其他來源可達，不能只因 W11_B 能連線就宣稱其他來源被隔離，應核對並測試未授權來源被拒絕。只設定唯讀不等於限制誰能讀取。

在 W11_B 實際嘗試新增測試檔，預期遭拒，才算唯讀共用驗證通過。不要把 Clone 的 readonly=off 與 SMB 共用唯讀混淆；本次可讀 Clone 配合唯讀 SMB，不需為演練修改備份來源的保護。

**截圖 E02：**B 的 Unlocked、來源快照、Clone 路徑及 SMB 唯讀設定；金鑰內容不可入圖。

### 4. IT 使用 W11_B 取回並交付

1. 在 **W11_B** 按 Win+R，輸入：

```text
\\10.10.10.100\takeover_work
```

2. 以預先準備的 SMB 取回帳號登入，開啟指定文件，與故障前內容截圖比對；無法讀取時先核對帳號及 ACL，不以所有人完整控制排錯。
3. 將所需資料**複製**至公司核准的加密隨身碟或受控檔案交付管道，不用剪下或移動。接收處建立本輪獨立資料夾，避免覆寫其他交付版本。
4. 若 VMware 演示使用 USB，先核對裝置及加密狀態，僅透過 VMware 的可移除裝置功能連到目前需要的 Windows VM；完成後安全退出，再交付到 W11_A。不為本輪格式化既有 USB，不將兩 VM 同時連到同一 USB。若環境不支援，改用公司已核准的交付管道，不假設拖放／共享資料夾已啟用。
5. 交付給 A 站指定負責人，在 **W11_A** 開啟文件，確認內容可用。加密密碼另循核准方式交付，不和資料放在同一個檔案。
6. 記錄檔案清單、來源快照、接收人及驗證時間。這是「急用資料交付完成時間」，不是 A 正式 SMB 恢復時間。

若使用本專案的 baylen 測試帳號，以管理員控制的 W11_B 代操作取回；不把 B 帳號密碼交給員工，也不讓 W11_A 直接登入 B。若更換 SMB 身分，先關閉檔案並針對 B 中斷原連線再登入；Web UI 切換帳號不會改 Windows SMB 身分。

**截圖 E03：**W11_B 的 B UNC 與文件內容、唯讀寫入遭拒，以及 W11_A 成功開啟交付副本。不要拍加密密碼。

### 5. 負責人暫時工作，A 修好後交回

1. 負責人將文件存放於 Windows 指定的暫時工作資料夾，修改測試文件並儲存；每個專案維持一份受控工作版本。多人需要協作時，由負責人統整，不讓各自副本直接互相覆寫。
2. A 修復後，IT 核對原儲存池健康、資料集已解鎖、mainpool/data 及原 SMB 路徑正常。原本 PULL 排程先保持暫停；若原快照／Cloud Sync 任務被暫停，也先保留其狀態至交接完成。
3. 通知負責人儲存、關閉工作檔。IT 在 A 正式資料集內建立本輪獨立交接子資料夾，例如：

```text
緊急取回交接_20261020
```

這是原共用內的**一般資料夾**，不是新 ZFS 資料集，不改 SMB 路徑或備份來源。名稱依本輪日期且不得覆寫舊交接資料夾。
4. 將最新工作檔複製進交接資料夾，由負責人確認新增／修改／刪除清單，開啟內容比對。先備份 A 正式位置的現有版本，並建立交接前快照，再由 IT 將經確認的變更合併回原專案位置。
5. 同名檔案先比較內容再決定保留版本，不按「全部取代」；交付副本缺少某檔案不代表正式資料要刪除，必須有明確刪除清單與確認。不以檔案日期較新作為唯一依據。
6. Windows 複製可能依目的端繼承權限，不能假設保留完整 NAS 擁有者／ACL。依第 5.7–5.8 節核對交接資料夾與正式檔案的權限；baylen 可存取其授權內容，若驗證 employees 唯讀，需使用實際 employees 帳號測試。
7. 以原員工帳號連回 **A 原正式共用**，開啟合併後文件，確認「A 故障期間的工作更新」仍在，再做可寫／唯讀權限驗證。記錄 A 完整檔案服務恢復時間。

本次 B 只提供唯讀取回，正式工作異動留在交付副本。**不需要將整個 B Clone 反向複寫覆蓋 A，也不需要更換 mainpool/data、建立 return_from_b 或改三套備份來源。**交付範圍過大或大量員工需同時共享寫入時，另行規劃正式 DR 接管，不把此人工交付流程當成全公司高可用方案。

**截圖 E04：**W11_A 暫時工作更新、A 獨立交接資料夾與正式位置的新內容，以及權限驗證。

### 6. 關閉臨時服務並恢復備份

| B 站／交付項目 | 收尾處理 |
|---|---|
| W11_B SMB 連線 | 關閉文件與視窗，安全退出 USB，針對本次 B 共用解除連線，不清除其他業務磁碟連線 |
| takeover_work 共用 | 停用；確認無需保留時可刪除這筆共用設定，與刪除資料集分開處理 |
| B SMB 服務 | 若 B 沒有其他 SMB 用途，停止並取消開機自動啟動；若另有用途，只停用本次共用 |
| 本次專用取回帳號 | 停用 SMB Access，必要時鎖定並驗證登入被拒；不可連帶停用 B 管理員或其他服務帳號 |
| executives 等群組 | 保留必要 UID/GID 與 ACL 對應，不需刪除重建；executives_old 只有確認無帳號／檔案 GID／ACL／服務引用後才清理 |
| Clone／來源快照 | 暫留至交接與新一輪備份驗收完成；清理前核對 origin 與相依性，不強制刪除依賴中的來源快照 |
| 原 backup_snapshot | 維持備份用途與 readonly=on，金鑰離線保管 |
| 加密 USB、工作副本與交接資料夾 | 依公司保存與銷毀規定處理；不在尚未確認 A 新備份成功前刪除唯一最新工作版本 |

A 原正式資料集及路徑未變，核對原快照、B PULL、S3 PUSH 任務仍指向原路徑後，先按順序手動執行：**A 建立包含交回文件的新快照 → B PULL 並確認收到該快照 → A S3 PUSH COPY 並核對預期物件與本次成功回報**。對 B 新快照與 S3 抽樣驗證文件可讀，再恢復原每日 18:00／18:30／19:00 排程。使用手動快照時，名稱須符合原複寫任務的 matching schema，且避免與既有名稱衝突；不符合時先調整本次操作，不以任務 SUCCESS 代替已收到當次文件。

如保留的臨時 Clone 造成快照保留／刪除相依性，按資料保留需求與日誌處理，不強制刪除。B PULL 與必要監控連線保持原授權。

**不新增 A 員工到 B 的跨站 SMB 通道。**若前一版試作曾新增路由或放行規則，先核對紀錄，再撤回「本次新增」部分，不能誤關既有複寫／監控。W11_A 曾新增的錯誤路由若仍存在，需先看 `route print`，確認確為本輪的 10.10.10.0/24 經 192.168.1.10，再移除該筆：

```bat
route delete 10.10.10.0 mask 255.255.255.0 192.168.1.10
route print
```

路由移除不等於安全隔離；W11_A 已使用 192.168.1.1 預設閘道，仍需核對有效存取規則。若已有寬鬆允許，先修正再宣稱平時隔離。確認 W11_A 不能直接使用 B SMB、W11_B 臨時共用已不可用，管理及原監控／複寫仍正常。

**截圖 E05：**B 臨時共用停用、取回帳號 SMB 存取撤回、新快照／B 複寫／S3 當次成功，以及 A 正式文件可用。

### 圖片整合與驗收表

Word 建議用三組合併圖：① E01 告警；② E02＋E03 備份取回與交付；③ E04＋E05 工作檔交回及收尾。其他原圖與日誌留在 GitHub 8.2 演練紀錄；圖號接續 Word 實際順序，不覆蓋既有圖。

| 驗收項目 | 通過條件 | 本輪結果 |
|---|---|---|
| A 離線與告警 | W11_A 原共用失敗、實際 Grafana／Email／Discord 證據 | 待填 |
| 還原點 | 快照名稱、資料時間、指定文件確實存在 | 待填 |
| 金鑰／Clone | A 關閉後仍可用保存金鑰取回，origin 與內容正確 | 待填 |
| B 臨時唯讀 | 授權 W11_B 帳號可讀，新增／修改遭拒，未授權來源／帳號被拒 | 待填 |
| 交付 | W11_A 可開啟文件、交付清單及負責人可追溯 | 待填 |
| 暫時工作 | 指定負責人更新後儲存，版本清楚 | 待填 |
| 交回 A | 先交接後合併、原版本可追溯、新內容與權限正確 | 待填 |
| 收尾 | B 臨時服務撤回，新一輪快照／複寫／S3 驗證通過 | 待填 |

分別記錄事故、快照資料時間、告警、急用資料交付可用、A 正式服務恢復及新備份完成時間。本輪「急用資料交付時間」不能填成全公司接管 RTO。若後面的共用量測表仍使用「B 站接管」名稱，本節紀錄須註明範圍為「緊急取回」，不沿用舊 15 分鐘接管目標或暗示已達成。

參考：[TrueNAS SMB](https://www.truenas.com/docs/scale/25.10/scaletutorials/shares/smb/managesmbshares/)、[群組 GID 建立後不可修改](https://www.truenas.com/docs/scale/credentials/groups/localgroupsscreens/)、[加密複寫目的端金鑰映射](https://www.truenas.com/docs/scale/24.10/scaletutorials/dataprotection/replication/advancedreplication/unlockreplicationencrypteddatasetzvol/)。

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
