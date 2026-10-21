# 第八章：災難情境模擬與復原 SOP

依技術文件目前版本整理為 **四個獨立情境**。每節列出操作設備、帳號、設定、驗證與補圖位置；共用建置步驟引用 Word 或 [監測 VM 指南](monitoring-vm-from-zero.md)，不重複安裝。

**狀態：這是操作與驗收程序，不是四項演練皆已成功的測試報告。** 本次文件整理沒有登入你的 VMware、NAS 或 AWS；真實演練結果需填入下方表格。歷史隔離測試另見 [測試報告](installation-test-report.md)。

| Word 章節 | 情境與操作入口 | 驗證重點 |
|---|---|---|
| 8.1 | [雙碟故障與 RAID-Z2 復原](#drill-81) | 自動告警、逐顆換碟、重建與資料驗證 |
| 8.2 | [A 離線與異地備份緊急取回](#drill-82) | IT 在 W11_B 取回、交付急用資料，再交回 A |
| 8.3 | [誤刪與本地快照復原](#drill-83) | 只取回單一文件，保留快照後的新資料 |
| 8.4 | [A、B 不可用與 S3 復原](#drill-84) | 新建地端 NAS，PULL 雲端文件並驗證 |

## 演練前共同確認

- 先完成 [環境與位址核對](../README.md#environment)、監控建置、實際通知收訊及可用備份確認。只在演練環境操作測試文件與測試磁碟。
- 離線保管 NAS 設定、來源加密金鑰及 AWS 還原憑證。ZFS 資料複寫不會自動重建本機帳號、SMB 共用或網路設定。
- A 為 `mainpool/data`；B 為 `backuppool/backup_snapshot`。原排程：A 快照 18:00、B PULL 18:30、S3 PUSH＋COPY 19:00。實際現場不同時先修正紀錄。
- 對照磁碟序號及 VMware 裝置，區分 RAID-Z2 資料碟與兩顆開機 Mirror。移除連接不等於刪除 VMDK。
- 各系統時鐘同步；記錄時間須含時區，UTC 日誌與 Asia/Taipei 通知先換算再比較。
- 演練彼此獨立。上一輪恢復健康、服務與備份後，再做下一輪。所有 VM 同處一台實體主機，只能呈現邏輯分站，不能當作實體異地存活證據。

<a id="drill-81"></a>
## 8.1 雙碟故障自動告警與 RAID-Z2 復原

對應 Word **8.1 雙碟故障自動告警與 RAID-Z2 復原**。本情境模擬公司 NAS 同時發生兩顆資料碟故障：在 VMware 移除 TrueNAS A 同一組 RAID-Z2 的兩顆資料碟，觀察自動告警，加入兩顆新碟並完成 Replace／resilver，最後核對檔案與恢復通知。

**文件狀態：測試程序已建立，真實雙碟演練結果待執行者填寫。** 本次提交是文件更新，未操作你的 VMware／NAS，沒有宣告真實雙碟測試、通知或檔案驗證已通過。先前安裝器的隔離替身測試也不能代替本次實機演練。

### 1. 為何故障後仍是降級

RAID-Z2 在同一組 VDEV 具雙重同位元檢查，可容忍兩顆資料碟故障；在其餘成員及資料正常的前提下，儲存池仍能提供資料存取，但失去進一步的磁碟容錯餘裕。因此預期是 **pool DEGRADED，兩個成員 UNAVAIL／FAULTED 等異常**，而非所有服務立即停止。

一般員工可能還能開啟 SMB 檔案，未必察覺硬碟已故障。監控持續讀取 ZFS 健康與成員狀態，再透過 Email／Discord 通知管理員，讓管理員在故障擴大前處理。SNMP Target 為 UP 只代表可採集，不能代替 pool 健康判斷。

本情境驗證的是「故障後及早發現並處理」，不是預測磁碟何時損壞，也不把兩碟容錯當成備份。

### 2. 在哪裡操作與先完成什麼

| 操作位置 | 本流程用途 |
|---|---|
| Windows 主機的 VMware Workstation | 移除 A 的兩顆資料碟、建立並接上兩顆新 VMDK |
| TrueNAS A Web UI／Shell | 核對 pool／磁碟、掃描新碟、Replace 及追蹤重建 |
| A 站 Windows SMB 用戶端 | 建立測試檔、核對讀寫與 SHA-256 |
| Rocky Linux 監測 VM／Grafana | 查詢採集指標、規則狀態與通知時間 |
| TrueNAS B | 保持正常運作，作為未受本次磁碟操作影響的對照站 |

請只在備份已確認可用的演練 VM 執行。此次只移除 **A 的資料池成員**；兩顆開機 Mirror、B 的磁碟與 Gateway／監測 VM 都保留。VMware 的 Remove 是移除 VM 的磁碟連接，**保留原 VMDK 檔案，不從 Windows 刪除磁碟檔**，以便辨識及必要時回復連接。

前置設定不重做，依既有文件確認：

- A 的 mainpool 是同一組 RAID-Z2、正常狀態 ONLINE；參照 Word 5.3。
- A／B Tailscale、SNMP 與 `extend zfs /usr/sbin/zpool status -P` 已完成；見 [監測 VM 教學第 2 節](monitoring-vm-from-zero.md#2-truenas-ab-的-snmp-前置設定)。
- Grafana 面板、九條規則與 Email／Discord Test 已完成；見 [監測 VM 教學第 5 節](monitoring-vm-from-zero.md#5-登入-grafana測試通知並完成驗收)。
- SMB 測試使用具讀寫權限的 IT／高層測試帳號；唯讀員工帳號不適合建立演練檔案。
- 記下 A／B 的實際位址。下列 PromQL 使用專案 A 範例 `100.114.236.88`、pool `mainpool`，環境不同須一起替換。
- A、監測 VM 與 Windows 時鐘同步；命令日誌用 UTC，Email／Discord 若顯示台北時間，核對時轉成同一時區。

若連平時的採集或通知都失敗，先修好監控再開始，不用移除磁碟來測試通知設定。

### 3. 建立故障前基準

#### 3.1 在 TrueNAS A 核對磁碟

開啟 **A 的 Web UI → 系統／System → Shell**。一般管理員先升為 root：

```bash
sudo -i
date -u --iso-8601=seconds
zpool status -P mainpool
zpool status -LP mainpool
zpool status -g mainpool
zpool status -P boot-pool
lsblk -d -b -o NAME,SIZE,MODEL,SERIAL,HCTL,TYPE
ls -l /dev/disk/by-id/
```

- `mainpool`／`boot-pool` 名稱若不同，先以 `zpool list` 確認再換成實際名稱。
- `zpool status -LP` 用來核對目前解析後的成員路徑；`-g` 顯示 VDEV GUID，故障後可能用 GUID 代替舊路徑。
- `lsblk -b` 顯示 bytes，後面選新碟容量時要比較實際容量，不能只看 GB／GiB 名稱。
- 完成條件：mainpool 為 ONLINE、同一個 raidz2 VDEV 有預期的六顆資料碟，沒有正在進行的 resilver 或未處理錯誤；開機池另行辨識。

#### 3.2 將 NAS 裝置對照到 VMware VMDK

在 VMware **選取 TrueNAS A → Edit virtual machine settings／Settings → Hardware**，逐顆選 Hard Disk，記錄：

1. Disk file 的完整 VMDK 路徑。
2. Capacity。
3. Advanced 中的 Virtual device node，例如 SCSI 0:2。介面名稱依 Workstation 版本確認。
4. 對應 NAS 的裝置名稱、序號／by-id、mainpool 成員 GUID。

需要時在 A Shell 針對候選裝置查看屬性；`/dev/sdX` 必須換成前一步實際看到的**整顆資料碟**：

```bash
udevadm info --query=property --name=/dev/sdX
```

可參考 ID_PATH、序號及 HCTL，但不同控制器的編號不一定一對一；**不能直接認定 VMware 的第三顆 Hard Disk 就是 Linux sdc**。如果虛擬磁碟序號缺失、同容量而無法明確對照，先停止本輪，補齊裝置對照再操作，不能猜測移除。

| 角色 | VMware device node | VMDK 路徑 | NAS 裝置／by-id | 成員 GUID | 容量 bytes |
|---|---|---|---|---|---|
| 開機碟 1／2，保留 | 待填 | 待填 | 待填 | 待填 | 待填 |
| 資料碟故障目標 1 | 待填 | 待填 | 待填 | 待填 | 待填 |
| 資料碟故障目標 2 | 待填 | 待填 | 待填 | 待填 | 待填 |
| 其餘四顆資料碟，保留 | 待填 | 待填 | 待填 | 待填 | 待填 |

**截圖 D01：** mainpool ONLINE 與六個成員；**D02：** 兩個目標 VMDK／device node 的對照。可遮蔽主機私人目錄，保留磁碟辨識資訊。

#### 3.3 在 Windows 建立小型測試檔與外部雜湊紀錄

在有 A 站 SMB 讀寫權限的 Windows 用戶端開 PowerShell。下列 UNC 要填**實際 SMB 共用名稱**，不是 ZFS 資料集路徑。例如 `\\192.168.1.100\你的共用名稱`；不要直接照抄未知的 share 名稱。

```powershell
$Share = Read-Host '輸入 A 站可讀寫的 SMB UNC 路徑'
$RunId = Get-Date -Format 'yyyyMMdd-HHmmss'
$Evidence = Join-Path $env:USERPROFILE "Desktop\raidz2-drill-$RunId"
$TestDir = Join-Path $Share "raidz2-drill-$RunId"
New-Item -ItemType Directory -Path $Evidence -ErrorAction Stop | Out-Null
New-Item -ItemType Directory -Path $TestDir -ErrorAction Stop | Out-Null
$Baseline = Join-Path $TestDir 'baseline.txt'
"RAID-Z2 drill baseline $RunId" |
    Set-Content -LiteralPath $Baseline -Encoding UTF8 -ErrorAction Stop
$BaselineHash = (Get-FileHash -LiteralPath $Baseline -Algorithm SHA256).Hash
$BaselineHash | Set-Content (Join-Path $Evidence 'baseline.sha256')
$TestDir | Set-Content (Join-Path $Evidence 'nas-test-directory.txt')
Get-Date -Format o | Set-Content (Join-Path $Evidence 'baseline-time.txt')
Get-Content -LiteralPath $Baseline
Get-FileHash -LiteralPath $Baseline -Algorithm SHA256
```

保持此 PowerShell 視窗開啟，後續沿用變數。若關閉，從桌面紀錄取得 `$Evidence`、`$TestDir`，重新設定 `$Baseline` 並讀回 `baseline.sha256`；不必重新產生基準內容。雜湊紀錄放在 Windows，避免只留在待測 NAS。

**截圖 D03：** 基準檔案與 SHA-256。

### 4. 在 VMware 模擬同時缺少兩顆資料碟

#### 4.1 預設走可重現的關機操作

不假定每種 VMware 控制器都支援開機中移除硬碟：

1. 在 TrueNAS A Web UI 執行正常 **Shut Down**，等 VMware 顯示 **Powered Off**，不是 Suspend。
2. 記錄這次有計畫的停機開始時間，保留監測 VM、B 與 Gateway 正常運作。
3. 到 A 的 **Settings → Hardware**，依 D02 表格選定第一顆目標資料碟，按 **Remove**。
4. 對第二顆目標資料碟執行同樣操作；確認仍保留兩顆開機碟及其餘四顆資料碟。
5. 儲存設定，啟動 A。原 VMDK 只取消連接，仍保留於原位置。
6. 等 A 開機、Tailscale／SNMP 回復，登入確認資料集已解鎖及 SMB 可用；若需要金鑰，使用已安全備份的對應金鑰解鎖。

**此路徑包含人為關機，不能宣稱服務全程不中斷或 RTO＝0。** 關機期間的節點離線、開機後的儲存池降級，分別記錄。它仍能驗證雙碟缺失後 RAID-Z2 及主動告警的行為。

只有已確認支援熱移除的 Workstation 版本、虛擬控制器及 guest 設定，才另開一輪在線拔碟測試；不要為了演示不中斷直接手改執行中 VM 的檔案。兩輪紀錄不可混寫。

#### 4.2 確認真正的雙碟降級

A Shell 執行：

```bash
date -u --iso-8601=seconds
zpool status -P mainpool
zpool status -g mainpool
lsblk -d -b -o NAME,SIZE,MODEL,SERIAL,HCTL,TYPE
```

預期 **mainpool DEGRADED、同一 raidz2 VDEV 有兩個異常／缺失成員**，其他四顆資料碟仍在，boot-pool 沒有被誤動。成員可能顯示 UNAVAIL、FAULTED 或數字 GUID，名稱依偵測結果而異。

若 pool 為 FAULTED／UNAVAIL、少於預期成員、開機碟出問題或資料無法讀取，先停止並核對磁碟對照，不把其他異常硬寫成「雙碟降級成功」，也不以 `zpool clear` 掩蓋錯誤。

**截圖 D04：** 兩個缺失成員及 DEGRADED，記錄第一次確認降級的時間。

#### 4.3 驗證一般用戶可能還能存取

回到 Windows 的同一個 PowerShell：

```powershell
Get-Date -Format o
$CurrentHash = (Get-FileHash -LiteralPath $Baseline -Algorithm SHA256 -ErrorAction Stop).Hash
$CurrentHash -eq $BaselineHash
$During = Join-Path $TestDir 'degraded-write.txt'
"Written while two data disks are missing: $(Get-Date -Format o)" |
    Set-Content -LiteralPath $During -Encoding UTF8 -ErrorAction Stop
$DuringHash = (Get-FileHash -LiteralPath $During -Algorithm SHA256).Hash
$DuringHash | Set-Content (Join-Path $Evidence 'degraded-write.sha256')
Get-Content -LiteralPath $During
```

預期基準 hash 比對為 True，且可新增／讀回測試檔；失敗就記錄錯誤與時間，不宣告服務可用。這是指定時間點的讀寫驗證，不是全時段無中斷的連續量測。

**截圖 D05：** DEGRADED 期間基準檔 hash 一致及新檔可讀寫。此階段不做大型壓力寫入，重點是觀察服務與監控。

### 5. 核對自動告警，而不只按 Test

#### 5.1 實際需要看的規則

到 Grafana **Alerting → Alert rules → TrueNAS_Alerts**，展開 A 的告警實例，核對 instance 與 pool。

| 規則 | 專案 UID | 目前儲存庫設定 | 雙碟故障時預期 |
|---|---|---|---|
| ZFS 儲存池降級（DEGRADED） | alert_zfs_degraded | 評估每 1m，for 1m | mainpool 對應實例進入 Alerting |
| ZFS 磁碟成員或 VDEV 異常 | zfs_member_fault_v1 | 評估每 1m，for 0s | A 對應實例進入 Alerting |
| TrueNAS 節點或 S3 監控離線告警 | alert_node_or_s3_down | for 2m | 關機夠久可能出現；不是降級告警替代品 |
| ZFS 健康指標／成員狀態無法取得 | 對應 missing 規則 | for 2m | 若發生，先查採集；不直接等同兩顆磁碟故障 |

依據 [正式告警設定](../configs/grafana-alerts-stable.yaml)。倉庫的 [Prometheus 範例](../configs/prometheus.yml) 中 NAS 採集為 15s；**實際 VM 若調整過，依現場配置為準**。這些數字不是「一分鐘內必定收到通知」的 SLA；仍包含採集、評估邊界、Pending、通知分組與傳送時間。不要為了錄影把 for 任意改成 0。

#### 5.2 唯讀查詢 Prometheus 已採集的證據

以下在 **監測 VM** 執行，不是在 TrueNAS。A 的 instance／pool 若改過，先改查詢值：

```bash
date -u --iso-8601=seconds

curl -fsSG http://127.0.0.1:9090/api/v1/query \
  --data-urlencode 'query=up{job="truenas_snmp",instance="100.114.236.88"}' \
  | python3 -m json.tool

curl -fsSG http://127.0.0.1:9090/api/v1/query \
  --data-urlencode 'query=zpoolHealthStr{job="truenas_snmp",instance="100.114.236.88",zpoolName="mainpool"}' \
  | python3 -m json.tool

curl -fsSG http://127.0.0.1:9090/api/v1/query \
  --data-urlencode 'query=max by (instance) (zfsMemberFault{job="truenas_snmp",instance="100.114.236.88"})' \
  | python3 -m json.tool

curl -fsSG http://127.0.0.1:9090/api/v1/query \
  --data-urlencode 'query=zfsStatusCommandExit{job="truenas_snmp",instance="100.114.236.88"}' \
  | python3 -m json.tool
```

A 已開機且採集正常時，預期 up＝1、帶 DEGRADED 標籤的有效健康序列值為 1、成員異常值為 1、狀態命令退出值為 0。若有多個健康狀態序列，核對哪個標籤的值是 1，不只看字串是否出現。這些查詢讀取 Prometheus 已採集資料，不會因每次開查詢就重新對 NAS 做一次全盤掃描。

#### 5.3 驗證兩種通知都到達

1. 留存規則實例 Alerting 的時間、A instance／pool 與規則名稱。
2. 到指定 Email 信箱與 Discord 頻道確認收到**本次真實異常**通知，分別記錄時間。
3. 區分關機離線通知、pool 降級通知及成員異常；同一封／則通知可能分組包含多個告警。
4. 如果只有 Contact point Test 收到，還不能通過本步。若規則已 Alerting 但沒通知，檢查 Contact point、Notification policies、Silence／Mute timings 及傳送日誌，見 [原教學第 5 節](monitoring-vm-from-zero.md#5-登入-grafana測試通知並完成驗收)。

**截圖 D06：** Grafana Alerting；**D07：** Email／Discord 真實告警。保留時間與 instance，遮蔽私人地址、Webhook 及秘密。

### 6. 在 VMware 加入兩顆新資料碟

收到告警並保存 D04–D07 證據後，再開始修復：

1. 依控制器能力選擇加碟方式。預設使用正常關機、等 A Powered Off 後到 Settings 操作；若現場已驗證支援熱加入，可在線加入。
2. 在 A **Settings → Hardware → Add → Hard Disk**，選與原環境相容的控制器類型。
3. 選 **Create a new virtual disk**。新碟實際 bytes 容量須符合 Replace 要求；最簡單是選比原資料碟稍大的容量，避免 GB／GiB 或分割開銷差異。不要只因兩邊都寫 500 就假定足夠。
4. VMDK 命名如 `raidz2-replacement-01.vmdk`，記下新的 device node、路徑與容量。
5. 再加入 `raidz2-replacement-02.vmdk`。它們是兩顆新虛擬磁碟，不是重新接回原本移除的舊 VMDK。
6. 確認 Windows 主機承載 VMDK 的磁碟有足夠空間；薄配置仍需為後續實際寫入預留空間。
7. 啟動 A，必要時解鎖資料集，等管理、Tailscale／SNMP 與 SMB 回復。

虛擬硬碟建立完成後交給 TrueNAS 的 Replace 流程使用；不在 Windows 磁碟管理初始化或格式化這兩顆 NAS 虛擬磁碟，也不在 TrueNAS 用它們另建 pool 或 Add VDEV。

**截圖 D08：** 兩個新 VMDK／device node／容量。關機加碟的停機另記錄，不混算成 ZFS 一定中斷或全程不中斷。

### 7. 新碟未顯示時，在 A 掃描裝置

在 **要更換磁碟的 TrueNAS A Shell** 執行，一般管理員先 `sudo -i`：

```bash
sudo -i
date -u --iso-8601=seconds
lsblk -d -b -o NAME,SIZE,MODEL,SERIAL,HCTL,TYPE
for h in /sys/class/scsi_host/host*; do
  echo "- - -" > "$h/scan"
done
udevadm trigger
udevadm settle
midclt call disk.sync_all
lsblk -o NAME,SIZE,MODEL,SERIAL,TYPE
lsblk -d -b -o NAME,SIZE,MODEL,SERIAL,HCTL,TYPE
```

`sudo -i` 輸入管理員登入密碼，輸入不顯示字元；已為 root 可省略。此處用 `udevadm settle` 等待裝置事件完成，不只固定睡兩秒。

對照掃描前後，確認新加入的**兩顆**磁碟與容量、序號／device node。裝置名稱可能重排，不能因為叫 sdc／sdd 就認定它們是新碟。若沒有 SCSI host、沒有看到新碟，先核對虛擬控制器／加碟是否真的成功，必要時正常重新啟動；不要無限重試掃描。

這些命令只更新偵測與 TrueNAS 清單，**不會自動把新碟加入原 RAID-Z2，也不會啟動 Replace**。

**截圖 D09：** 掃描後辨識到兩顆新碟，補齊對照：

| 故障成員 GUID | 新 VMDK | 新 device node | 新 NAS 裝置／序號 | 新碟容量 bytes |
|---|---|---|---|---|
| 目標 1，待填 | replacement-01 | 待填 | 待填 | 待填 |
| 目標 2，待填 | replacement-02 | 待填 | 待填 | 待填 |

### 8. 逐顆 Replace 並追蹤 resilver

#### 8.1 先替換第一顆

1. 到 **A Web UI → 儲存／Storage → mainpool → 管理裝置／Manage Devices（或 View VDEVs）**。選項名稱依 25.10 實際介面確認。
2. 展開原 raidz2 VDEV，依 D04 的 GUID／舊序號選第一個故障成員。
3. 按 **Replace**，選 D09 的第一顆新碟，再次核對容量、序號及不屬於 boot-pool。
4. 確認會清除該新碟內容後提交。若系統要求 Force，先確認是在清除正確的**空白替換碟**；不為了越過容量或磁碟身分錯誤而強行操作。
5. 觀察 Jobs／pool 的 resilver，或在 A Shell 執行：

```bash
date -u --iso-8601=seconds
zpool status -P mainpool
```

以約 30–60 秒間隔人工查看即可，不需高頻反覆執行。記錄掃描／修復進度與完成時間；等待第一顆重建結束後再處理第二顆。**第一顆完成時，另一顆仍故障，pool 預期仍是 DEGRADED，成員異常告警也可能持續。**

#### 8.2 再替換第二顆

1. 依同一 UI 路徑選第二個故障成員。
2. Replace 指向第二顆新碟，不能誤選已投入重建的第一顆。
3. 追蹤第二次 resilver，等完成後核對 mainpool。
4. 若新碟無法選取，先確認未屬於其他 pool、實際容量足夠、沒有因裝置名稱重排而選錯；不以 Add VDEV／重新建立 pool 代替 Replace。

**截圖 D10：** 第一顆 Replace／重建；**D11：** 第二顆 Replace／重建完成。故障成員與新碟對應清楚，不能只有磁碟清單。

### 9. 驗證修復與告警恢復

#### 9.1 TrueNAS A

```bash
date -u --iso-8601=seconds
zpool status -P mainpool
zpool status -g mainpool
zpool status -x mainpool
lsblk -d -b -o NAME,SIZE,MODEL,SERIAL,HCTL,TYPE
```

完成條件：

- mainpool／原 raidz2 VDEV 及六個有效成員均 ONLINE。
- 兩個舊故障成員已被兩顆新碟替換；沒有仍在進行的 replacing／resilver。
- 核對錯誤欄位及 permanent data errors；若有錯誤，保留原始結果處理，不先 clear 再截圖。
- boot-pool 與 B 仍正常；若 A 再開機後資料集為 Locked，先核對金鑰狀態，不能把未解鎖造成的 SMB 失敗當作資料已遺失。

#### 9.2 Windows 檔案完整性

同一 PowerShell 視窗執行：

```powershell
Get-Date -Format o
$FinalBaselineHash = (Get-FileHash -LiteralPath $Baseline -Algorithm SHA256 -ErrorAction Stop).Hash
$FinalDuringHash = (Get-FileHash -LiteralPath $During -Algorithm SHA256 -ErrorAction Stop).Hash
[pscustomobject]@{
    File = 'baseline.txt'
    SHA256Matches = ($FinalBaselineHash -eq $BaselineHash)
}
[pscustomobject]@{
    File = 'degraded-write.txt'
    SHA256Matches = ($FinalDuringHash -eq $DuringHash)
}
$After = Join-Path $TestDir 'recovered-write.txt'
"Written after recovery: $(Get-Date -Format o)" |
    Set-Content -LiteralPath $After -Encoding UTF8 -ErrorAction Stop
Get-Content -LiteralPath $After
```

兩個 SHA256Matches 預期均 True，且重建後可新增／讀回檔案。任何一個 False、讀寫例外或缺檔，都記為未通過，不只靠 ONLINE 就宣告資料正確。

#### 9.3 Grafana 與雙管道

重跑第 5.2 節的唯讀查詢，核對 A 的 up＝1、有效 ONLINE 健康序列值為 1、成員異常＝0、狀態命令退出值＝0。到 Grafana 看**A／mainpool 對應實例**恢復 Normal，不能因 B 或其他規則還在告警而誤判本輪，也不能只看整個資料夾總狀態。

接著核對 Email／Discord 的恢復通知；若 contact point 的「停用恢復訊息／Disable resolved message」有啟用，恢復通知就不會送出，需要依實際設定處理並記錄。規則恢復不代表通知一定已送達，記下兩者時間。

**截圖 D12：** ONLINE／兩顆替換後成員；**D13：** hash 與恢復後讀寫；**D14：** 規則 Normal 與 Email／Discord resolved。

### 10. 本輪結果怎麼填

本頁提供流程，以下先保持待填；執行後以實際日誌及截圖補齊，不預填成功。

| 階段 | UTC 時間 | 畫面／日誌 | 結果 |
|---|---|---|---|
| 故障前 ONLINE／兩個基準資訊 | 待填 | D01–D03 | 待驗證 |
| 正常關機移除磁碟，若有 | 待填起訖 | VMware／連線紀錄 | 待記錄 |
| A 再啟動後確認雙碟 DEGRADED | 待填 | D04 | 待驗證 |
| 降級期間讀寫及 hash | 待填 | D05 | 待驗證 |
| pool／member 規則 Alerting | 分別待填 | D06 | 待驗證 |
| Email／Discord 真實異常通知 | 分別待填 | D07 | 待驗證 |
| 加入兩顆新碟／掃描完成 | 待填 | D08–D09 | 待驗證 |
| 第一顆 Replace／resilver | 待填起訖 | D10 | 待驗證 |
| 第二顆 Replace／resilver | 待填起訖 | D11 | 待驗證 |
| pool 與成員 ONLINE | 待填 | D12 | 待驗證 |
| 檔案 hash／讀寫通過 | 待填 | D13 | 待驗證 |
| A 對應規則 Normal | 待填 | D14 | 待驗證 |
| Email／Discord 恢復通知 | 分別待填 | D14 | 待驗證 |

另外記錄：

- 本輪編號、VMware／TrueNAS 版本、控制器、冷移除或已驗證熱移除。
- 拔除的兩個 GUID、舊 VMDK、新 VMDK 與序號對照。
- 降級發現延遲：首次觀察／採集到降級至收到各通知的時間。若未量到真正缺失生效時間，不把它當作精確的硬體故障發生時間。
- 服務可用性：指定時間點讀寫成功／失敗；冷操作的停機起訖獨立列出。
- 冗餘恢復時間：雙碟缺失生效至全部成員 ONLINE。
- 任何錯誤、重試、資料差異或未收到通知的原因。
- 若這兩顆虛擬碟都位於同一顆 Windows 實體磁碟，這是虛擬成員故障演練，不能據此宣稱已驗證兩顆獨立實體硬碟或整台宿主機故障。

**通過標準：雙碟缺失確實被偵測、規則自動 Alerting、Email／Discord 收到真實告警、兩顆新碟依序替換與重建、資料 hash／讀寫通過、pool／成員 ONLINE、對應規則與恢復通知完成。**

沒有量測就不填 RTO＝0、RPO＝0 或「兩分鐘內保證通知」。本輪測試檔 hash 通過也不等於所有歷史資料已全量校驗。

### 11. Word 與簡報該保留哪些證據

Word 圖 8-1 的合併圖可選四格：**D04 雙碟降級 → D07 真實通知 → D10／D11 換碟重建 → D12／D13 ONLINE 與檔案核對**。完整磁碟對照、時間表與 D01–D14 留在 GitHub／演練紀錄，紙本只放關鍵證據。

展示說明可寫：「RAID-Z2 讓雙碟故障後仍有機會維持資料服務，監控則主動指出看不見的冗餘損失，讓管理員提早更換磁碟並完成復原。」若本輪採關機操作，另外說明 VMware 人為停機時間，不宣稱全程無中斷。

### 官方操作依據

- [TrueNAS Replacing Disks](https://www.truenas.com/docs/scale/storage/disks/replacingdisks/)：Replace 與重建。
- [TrueNAS Managing Pools](https://www.truenas.com/docs/scale/storage/pools/managepools/)：RAID-Z2 容錯與 pool 操作。
- [Broadcom VMware Workstation 新增虛擬磁碟](https://knowledge.broadcom.com/external/article/344712/creating-and-adding-a-new-virtual-disk-t.html)：只引用 VM 關機、Settings、新建 VMDK 的部分；該文章後段 Windows 初始化磁碟不適用於此 NAS Replace 流程。
- [Broadcom Workstation 虛擬硬體設定](https://knowledge.broadcom.com/external/article/315640/removing-unnecessary-hardware-from-vmwar.html)。
- 專案依據：[SNMP／ZFS 與通知建置](monitoring-vm-from-zero.md)、[正式告警](../configs/grafana-alerts-stable.yaml)、[Prometheus 範例](../configs/prometheus.yml)。

<a id="drill-82"></a>
## 8.2 A 站離線與異地備份緊急取回


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

### 1. 關閉 A，暫停 B 的原複寫排程

1. 在 VMware 關閉 **TrueNAS A**；B、Gateway、監控 VM 與 Windows 保持運作。W11_A 確認原 A 共用無法存取，記錄實際告警收訊時間。正常關機的模擬不寫成突然斷電實測。
2. 在 W11_B 瀏覽器開啟 **B 的管理頁 `http://10.10.10.100`**，以 B 管理員登入。
3. 到【**資料保護 → 複寫作業／Replication Tasks**】，依來源 `mainpool/data`、目的 `backuppool/backup_snapshot` 找到原本向 A 拉取資料的 **PULL** 任務，先記錄最後成功時間及排程。
4. 將該列 **Enabled／啟用** 關閉；若版本在編輯頁提供此選項，按 Edit 後取消 Enabled／啟用並儲存。回清單確認已停用。這是保留任務、暫停自動執行，不是刪除任務或備份。
5. 若顯示 Running，先查看工作狀態；必要時使用該工作的 Stop／Abort 停止，等工作結束再操作備份。停用排程不代表已停止執行中的工作。不要按 Run Now 測試已離線的 A。

本步不要求額外占用 Word 圖片頁面，記錄任務名稱與停用狀態即可。

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

### 6. 關閉臨時服務，恢復原複寫流程

1. 先確認 **A 儲存池 ONLINE、mainpool/data 已解鎖且可用，員工可從原 SMB 開啟交回的新文件**。最新工作檔應已確認並放回原專案位置。
2. 在 B 關閉本輪開啟的文件與 SMB 連線，停用 `takeover_work` 共用；B 無其他 SMB 用途才停止 SMB。專用取回帳號停用 SMB 存取，保留必要群組與管理員。
3. 核對原複寫的 **來源仍為 A 的 mainpool/data，目的仍為 B 的 backuppool/backup_snapshot，方向仍為 PULL**，不是臨時 Clone 或交接資料夾。不重建任務、不做整份反向覆寫。
4. A 建立包含交回文件的新快照。名稱須符合原任務的 **auto-%Y-%m-%d_%H-%M** matching schema，或等原 18:00 快照完成；記下本次名稱，避免同分鐘重名。
5. 回 **B → 資料保護 → 複寫作業**，重新開啟原任務 **Enabled／啟用**，確認原 18:30 排程未變，按 **Run Now**。等待 SUCCESS，並在 B 快照清單確認確實收到本次新快照；不能只看成功字樣。
6. 核對 A 快照 18:00、B PULL 18:30、A S3 PUSH＋COPY 19:00 排程與原路徑正常。S3 手動同步後，確認交回文件及本次成功回報。B 原備份維持唯讀保護。
7. Clone、交付副本及紀錄先保留，待新備份確認可用後依保存規定清理。不要強制刪除 Clone 依賴的快照。

本流程使用 W11_B 取回、核准管道交付，**不新增 W11_A 經 Gateway／Tailscale 直連 B SMB 的路由或放行**。若先前試作曾開通，只撤回有紀錄的臨時設定；保留原監控與複寫連線。另確認臨時共用已不能存取。

**補圖位置 E05：**A 正式文件可用，以及 B 原複寫來源／目的、本次新快照與成功結果；其他收尾記錄可留在演練紀錄。

### 圖片整合與驗收表

Word 建議優先保留兩組合併圖：① E02＋E03 備份取回與交付；② E04＋E05 工作檔交回及原複寫恢復。告警時間留在紀錄即可。其他原圖與日誌留在 GitHub 8.2 演練紀錄；圖號接續 Word 實際順序，不覆蓋既有圖。

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

分別記錄事故、快照資料時間、告警、急用資料交付可用、A 正式服務恢復及新備份完成時間。本輪「急用資料交付時間」不能填成全公司接管 RTO。本節量測範圍為「緊急取回」，不沿用全公司接管的時間目標。

參考：[TrueNAS SMB](https://www.truenas.com/docs/scale/25.10/scaletutorials/shares/smb/managesmbshares/)、[群組 GID 建立後不可修改](https://www.truenas.com/docs/scale/credentials/groups/localgroupsscreens/)、[加密複寫目的端金鑰映射](https://www.truenas.com/docs/scale/24.10/scaletutorials/dataprotection/replication/advancedreplication/unlockreplicationencrypteddatasetzvol/)。

<a id="drill-83"></a>
## 8.3 使用者誤刪與本地快照復原

baylen 刪掉一份重要文件後，由 IT 從事故前快照取回。只救回這份文件，保留快照之後新增的資料。本節在 **A 與 W11_A** 操作，A 必須正常運作。

### 1. 建立測試文件與事故前快照

1. 在 W11_A 以 baylen 連入 A 原本的 SMB 共用，在共用內建立一般資料夾 **`drill-83`**，新增 `important-project.txt`，輸入「這是刪除前的重要專案內容」，儲存並重新開啟確認。保留內容截圖；本演示不強制計算雜湊。
2. 管理員登入 **A Web UI → 資料集 → mainpool/data → 快照／Manage Snapshots → 製作快照**，名稱填 `drill-83-before-delete`，確認完整名稱為 `mainpool/data@drill-83-before-delete`。同名快照已存在時停止，改用本輪唯一名稱，後續選取相同名稱。
3. 確認快照已出現在清單後，在 W11_A 的 `drill-83` 新增 `after-backup.txt`，輸入「這是快照之後新增的資料」並儲存。這份檔案用來證明復原沒有回退整個資料集。

### 2. 模擬誤刪

在 W11_A 以 baylen 刪除 **`important-project.txt`**，保留 `after-backup.txt`。重新整理，確認前者消失、後者仍存在，記錄開始處理時間。只操作本次測試文件。

### 3. 從快照建立副本，只複製回指定文件

1. 在 **A Web UI → mainpool/data → 快照清單**，選取步驟 1 的快照，按 **Clone to New Dataset**。
2. 父層選 `mainpool`，名稱填 `data_recovery_83`，確認完整資料集是 `mainpool/data_recovery_83`。同名資料集已存在時先查用途，不覆蓋既有副本。
3. 在 **A Shell** 逐段執行，`sudo -i` 輸入管理員登入密碼，畫面不顯示輸入字元：

```bash
sudo -i
zfs get origin,mounted,mountpoint mainpool/data_recovery_83
cat /mnt/mainpool/data_recovery_83/drill-83/important-project.txt
```

確認 origin 是本輪快照、mounted=yes，且顯示刪除前內容。檔案不存在時，回頭核對資料夾名稱與所選快照，不繼續複製。

4. 確認原位置仍缺少這個檔案，才複製：

```bash
ls -la /mnt/mainpool/data/drill-83/
cp -ai -- \
  /mnt/mainpool/data_recovery_83/drill-83/important-project.txt \
  /mnt/mainpool/data/drill-83/
```

若詢問是否覆寫，先回答 `n`，核對是否有人已建立同名文件。`-a` 用於保留可保留的屬性；仍須以實際使用者檢查權限。**本輪不對 mainpool/data 執行 Rollback。**

### 4. 在 Windows 驗證，再收尾

回 W11_A 重新整理並確認：

- `important-project.txt` 已出現，開啟內容與事故前截圖一致。
- baylen 可以開啟、編輯及儲存復原文件；其他部門權限依原 ACL 維持。
- `after-backup.txt` 仍存在，內容沒有改變。

無法存取時，管理員比較復原文件與同資料夾正常文件的擁有者、群組及 ACL；依原部門權限修正該檔案，不遞迴放寬整份正式資料集。記錄驗證完成時間，先保留 Clone。確認不再需要後，才在資料集畫面核對名稱、刪除 **data_recovery_83 這份臨時 Clone**；不要勾選刪除來源資料集，也不強制刪除相依中的快照。

**補圖位置：**一組合併圖呈現誤刪前後、快照／Clone 名稱，以及兩份文件同時存在和重要文件可開啟的結果。

**通過條件：**原文件內容可用、baylen 權限正常、快照後新增文件保留。只看到檔名不等於內容已驗證。

<a id="drill-84"></a>
## 8.4 A、B 站不可用與 S3 雲端備份復原

將 A、B NAS 關閉，另建 **TrueNAS_Recovery**，從 S3 下載文件，再由 W11_A 開啟。本輪使用 **S3 Standard**；不進行 Glacier 解凍或完整公司檔案服務接管。

### 1. 先確認雲端有可用副本，再關閉 A、B

1. 在 W11_A 以 baylen 連入 A 原 SMB，建立一般資料夾 `drill-84`，新增 `cloud-recovery.txt`，輸入「這是雲端復原測試文件，A、B 不可用時仍需從 S3 取回」，儲存、重新開啟並截圖。
2. 在 **A → 資料保護 → 雲端同步作業** 找原有 **PUSH＋COPY** 任務，按 **Run Now**，等待 SUCCESS 並核對日誌。
3. 在 AWS S3 開啟 bucket `truenas-backup-myhome-2026`，確認物件 **`drill-84/cloud-recovery.txt`** 存在、大小合理，Storage class 為 **Standard**。抽樣下載開啟，確認內容；若已封存，先看本頁「延伸：封存資料取回」。
4. 在 VMware 關閉 **TrueNAS A 與 TrueNAS B**。兩台 Gateway、監控 VM、W11_A 及主機網路保持運作。本輪模擬兩台 NAS 不可用，沒有模擬整個據點斷電。

### 2. 建立新的地端復原 NAS

依 Word 5.1–5.2 安裝新的 TrueNAS VM，差異如下：

| 項目 | 本輪設定 |
|---|---|
| VM 名稱 | TrueNAS_Recovery |
| CPU／記憶體 | 2 vCPU／8 GB RAM |
| 開機碟 | 新建 64 GB VMDK |
| 資料碟 | 新建兩顆 100 GB VMDK，僅存本輪小型測試資料 |
| 網卡 | 與 W11_A 相同的 A 站 Host-Only VMnet |
| 管理 IP | 192.168.1.110/24；先確認未被使用 |
| 預設閘道／DNS | 192.168.1.1／8.8.8.8；依現場核對 |
| 資料池 | 兩顆新資料碟建立 Mirror：restorepool |
| 資料集 | restorepool/s3_restore，預設 Generic，使用 POSIX 權限 |

使用新 VMDK，不連接原 A、B 的磁碟。在 W11_A 開啟 `http://192.168.1.110`，設定本機管理員。確認池 ONLINE、`/mnt/restorepool/s3_restore` 是**空白接收目錄**，新 NAS 可透過原 HQ Gateway 連 AWS；無法驗證憑證時先查 IP、閘道、DNS、時間與 HTTPS 出站。

### 3. 加入可下載的 AWS 憑證

在 **新 NAS → 認證 → 備份憑證 → 雲端憑證 → 新增**：

- 名稱 `s3-restore-test`，Provider 選 **Amazon S3**。
- 填 Word 6.3 已安全保存、具下載權限的備份 IAM 金鑰，若顯示區域則選 bucket 實際區域 `ap-east-2`，驗證後儲存。
- 至少要有目標 bucket 的 `s3:ListBucket`、物件的 `s3:GetObject`；不能使用只有 ListBucket 的 **prometheus-cloudwatch-reader 監控金鑰**。TrueNAS 的憑證驗證亦可能需要原備份政策中的列舉儲存桶／區域權限，完整 JSON 見 [建置指南](monitoring-vm-from-zero.md#backup-iam)。

本專案既有備份為 SSE-S3，下載時由 S3 處理靜態加密，**不用 A 的 ZFS 金鑰**。若原任務另外啟用 Cloud Sync Remote Encryption，須帶入原本的遠端加密密碼等設定；不能套用本輪「不啟用 Remote Encryption」的設定猜測還原。

### 4. 建立獨立的 PULL＋COPY 任務

在 **新 NAS → 資料保護 → 雲端同步作業 → 新增**：

| 欄位 | 設定 |
|---|---|
| Description | S3 還原測試 drill-84 |
| Direction | **PULL：雲端下載到本地** |
| Transfer Mode | **COPY** |
| Cloud Credentials | s3-restore-test |
| Bucket | truenas-backup-myhome-2026 |
| Region（若顯示） | ap-east-2 |
| 雲端資料夾 | 選取／輸入 bucket 內的 **drill-84** |
| 本地目標 | /mnt/restorepool/s3_restore |
| Remote Encryption | 本輪未使用，保持停用 |
| Pre-script／Post-script | 留白，不貼 A 的成功回報腳本 |
| 自動排程 | 關閉，僅手動執行 |

再核對一次方向與空白目標才儲存，按 **Run Now**。COPY 仍可能覆寫同名本地文件，因此不直接下載到既有工作資料夾。原 A 的日常 PUSH 任務保持原設定。

等待 SUCCESS，打開日誌，確認沒有下載失敗。於 **新 NAS Shell** 檢查：

```bash
sudo find /mnt/restorepool/s3_restore -maxdepth 3 -type f -print
sudo cat /mnt/restorepool/s3_restore/cloud-recovery.txt
```

本輪選的是遠端 **drill-84 資料夾的內容**，預期文件直接在 `s3_restore/cloud-recovery.txt`。若實際多了一層目錄，先核對遠端資料夾選擇與日誌，再使用查到的正確路徑，不在空目錄上宣告成功。

**補圖位置：**PULL＋COPY、來源／目的路徑、SUCCESS 及下載文件；不要拍 Access Key／Secret。

### 5. 讓 W11_A 讀取復原文件

1. 在 **新 NAS → 認證 → 本機群組** 建立 `executives`，GID **3000**，啟用 SMB Group；若編號已被占用，先查清用途，不覆蓋既有群組。
2. 建立 `baylen`，UID **3000**、主要群組 executives，設定本輪密碼並啟用 SMB Access；不給管理員或 sudo 權限。這是新 NAS 的本機帳號，不會因下載文件自動出現。
3. 在 **新 NAS Shell** 確認資料集為本輪 Generic／POSIX 目標，再設定此目錄的讀取權限：

```bash
sudo -i
id baylen
zfs get mountpoint,acltype restorepool/s3_restore
chown -R root:executives /mnt/restorepool/s3_restore
find /mnt/restorepool/s3_restore -type d -exec chmod 750 {} +
find /mnt/restorepool/s3_restore -type f -exec chmod 640 {} +
```

以上遞迴命令**只用於這個新建、專用的 POSIX 測試資料集**；若 acltype 是 nfsv4，先停止並核對建立選項，不用 chmod 直接處理。這是新設測試權限，沒有宣稱還原了原 NAS 的擁有者與完整 ACL。

4. 在 **共用 → Windows Shares（SMB）→ 新增**，Name 填 `s3_restore`，Path 填 `/mnt/restorepool/s3_restore`，Purpose 選 Default Share，啟用共用、**Read Only／Export Read Only**，不開 guest，再啟動 SMB。
5. W11_A 按 Win+R，輸入：

```text
\\192.168.1.110\s3_restore
```

以**新 NAS 的 baylen 帳密**登入。開啟 `cloud-recovery.txt`，和備份前截圖比對。嘗試新增／修改應遭拒；若可寫，回查 SMB 唯讀設定。若登入失敗，先關閉該 NAS 的視窗及既有 SMB 連線，再重試，不使用 `net use * /delete` 清除所有業務連線。

**補圖位置：**A、B VM 關閉，以及 W11_A 從 `192.168.1.110` 開啟正確內容；另留唯讀驗證紀錄。

### 6. 記錄結果，恢復原環境

記錄事故、下載開始、任務完成與文件驗證完成時間，保存 S3 物件路徑、類別及日誌。通過條件是 **A、B 關閉期間，新 NAS 確實下載成功，W11_A 可讀到正確內容，唯讀限制有效**，不能只以任務 SUCCESS 判定。

完成後關閉文件、停用新 NAS 的臨時 SMB 共用、測試帳號 SMB 存取與還原任務；不再使用時移除新 NAS 儲存的 AWS 憑證。若與 A 共用備份金鑰，不停用 AWS 端仍供 A 使用的金鑰。保留證據後才處理測試 VM 與資料。

啟動 A、B，確認原儲存池、SMB、快照、B PULL 與 S3 PUSH 排程正常，來源與目的路徑仍是原設定。此演練驗證**文件取回與臨時唯讀存取**；正式重新上線仍須補齊帳號、部門 ACL、完整資料驗證與新備份。


## 延伸：封存資料取回（非本輪 Standard 演示）


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

<a id="measurements"></a>
## 演練結果與時間紀錄

每輪另存日期、操作人、檔案相對路徑、快照／物件名稱、任務日誌與截圖。檔名可用 `8-2_日期_步驟`；不把密碼、金鑰、Token 或 Webhook 放入證據。

- **RPO：**事故時間與實際可用還原點的資料時間之差；以實際備份為準，不能只填排程間隔。
- **RTO：**事故至指定服務通過內容與權限驗證的時間。8.2 分開記「急用資料交付」與「A 正式服務恢復」；8.4 的範圍是文件下載與臨時唯讀存取。
- RAID-Z2 容錯不等於 RTO 為零。計畫性關機、resilver、等待解凍與下載都須獨立記錄，未量測不預填成功數值。

| 情境 | 事故／開始時間 | 還原點／資料時間 | 告警收訊 | 文件／服務驗證完成 | 保護恢復 | 結果與證據 |
|---|---|---|---|---|---|---|
| 8.1 雙碟故障 | 待填 | 待填 | 待填 | 待填 | 待填 | 待驗證 |
| 8.2 異地緊急取回 | 待填 | 待填 | 待填 | 交付與 A 恢復分填 | 待填 | 待驗證 |
| 8.3 本地快照 | 待填 | 待填 | 不以告警為本輪條件 | 待填 | 待填 | 待驗證 |
| 8.4 S3 至新 NAS | 待填 | 待填 | 另存 NAS 離線通知 | 待填 | 待填 | 待驗證 |

## 未來延伸：勒索軟體應變

本版不執行病毒或真實加密程式。後續可在隔離環境演練：先隔離受感染用戶端、暫停受影響 SMB／同步並保存證據，再從事故前快照建立 Clone 驗證正常內容。若評估整個資料集 Rollback，須先保護快照後的合法變更，核對新快照、Clone 與增量複寫相依性；回滾會丟失還原點之後的資料變更。由乾淨用戶端驗證後才恢復服務。此項不列為本次四情境已完成成果。

依據：[TrueNAS snapshot rollback API](https://api.truenas.com/v25.10/api_methods_pool.snapshot.rollback.html)。

## 快照、複寫與雲端操作依據

- [TrueNAS 25.10 複寫任務畫面](https://www.truenas.com/docs/scale/25.10/scaleuireference/dataprotection/replicationscreensscale/)：Enabled 與 Run Now。
- [TrueNAS 快照管理](https://www.truenas.com/docs/scale/datasets/snapshots/managesnapshots/)：從快照建立 Clone。
- [TrueNAS 25.10 Cloud Sync](https://www.truenas.com/docs/scale/25.10/scaletutorials/dataprotection/cloudsynctasks/)：PULL、COPY 與 Remote Encryption。
- [AWS 封存物件取回](https://docs.aws.amazon.com/AmazonS3/latest/userguide/restoring-objects.html)：解凍與暫時副本期限。
