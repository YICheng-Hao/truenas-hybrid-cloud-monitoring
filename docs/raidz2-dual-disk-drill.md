# 災難情境模擬測試 01 雙碟故障自動告警與 RAID-Z2 復原

對應 Word **8.1 雙碟故障自動告警與 RAID-Z2 復原**。本情境模擬公司 NAS 同時發生兩顆資料碟故障：在 VMware 移除 TrueNAS A 同一組 RAID-Z2 的兩顆資料碟，觀察自動告警，加入兩顆新碟並完成 Replace／resilver，最後核對檔案與恢復通知。

**文件狀態：測試程序已建立，真實雙碟演練結果待執行者填寫。** 本次提交是文件更新，未操作你的 VMware／NAS，沒有宣告真實雙碟測試、通知或檔案驗證已通過。先前安裝器的隔離替身測試也不能代替本次實機演練。

## 1. 為何故障後仍是降級

RAID-Z2 在同一組 VDEV 具雙重同位元檢查，可容忍兩顆資料碟故障；在其餘成員及資料正常的前提下，儲存池仍能提供資料存取，但失去進一步的磁碟容錯餘裕。因此預期是 **pool DEGRADED，兩個成員 UNAVAIL／FAULTED 等異常**，而非所有服務立即停止。

一般員工可能還能開啟 SMB 檔案，未必察覺硬碟已故障。監控持續讀取 ZFS 健康與成員狀態，再透過 Email／Discord 通知管理員，讓管理員在故障擴大前處理。SNMP Target 為 UP 只代表可採集，不能代替 pool 健康判斷。

本情境驗證的是「故障後及早發現並處理」，不是預測磁碟何時損壞，也不把兩碟容錯當成備份。

## 2. 在哪裡操作與先完成什麼

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

## 3. 建立故障前基準

### 3.1 在 TrueNAS A 核對磁碟

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

### 3.2 將 NAS 裝置對照到 VMware VMDK

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

### 3.3 在 Windows 建立小型測試檔與外部雜湊紀錄

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

## 4. 在 VMware 模擬同時缺少兩顆資料碟

### 4.1 預設走可重現的關機操作

不假定每種 VMware 控制器都支援開機中移除硬碟：

1. 在 TrueNAS A Web UI 執行正常 **Shut Down**，等 VMware 顯示 **Powered Off**，不是 Suspend。
2. 記錄這次有計畫的停機開始時間，保留監測 VM、B 與 Gateway 正常運作。
3. 到 A 的 **Settings → Hardware**，依 D02 表格選定第一顆目標資料碟，按 **Remove**。
4. 對第二顆目標資料碟執行同樣操作；確認仍保留兩顆開機碟及其餘四顆資料碟。
5. 儲存設定，啟動 A。原 VMDK 只取消連接，仍保留於原位置。
6. 等 A 開機、Tailscale／SNMP 回復，登入確認資料集已解鎖及 SMB 可用；若需要金鑰，使用已安全備份的對應金鑰解鎖。

**此路徑包含人為關機，不能宣稱服務全程不中斷或 RTO＝0。** 關機期間的節點離線、開機後的儲存池降級，分別記錄。它仍能驗證雙碟缺失後 RAID-Z2 及主動告警的行為。

只有已確認支援熱移除的 Workstation 版本、虛擬控制器及 guest 設定，才另開一輪在線拔碟測試；不要為了演示不中斷直接手改執行中 VM 的檔案。兩輪紀錄不可混寫。

### 4.2 確認真正的雙碟降級

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

### 4.3 驗證一般用戶可能還能存取

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

## 5. 核對自動告警，而不只按 Test

### 5.1 實際需要看的規則

到 Grafana **Alerting → Alert rules → TrueNAS_Alerts**，展開 A 的告警實例，核對 instance 與 pool。

| 規則 | 專案 UID | 目前儲存庫設定 | 雙碟故障時預期 |
|---|---|---|---|
| ZFS 儲存池降級（DEGRADED） | alert_zfs_degraded | 評估每 1m，for 1m | mainpool 對應實例進入 Alerting |
| ZFS 磁碟成員或 VDEV 異常 | zfs_member_fault_v1 | 評估每 1m，for 0s | A 對應實例進入 Alerting |
| TrueNAS 節點或 S3 監控離線告警 | alert_node_or_s3_down | for 2m | 關機夠久可能出現；不是降級告警替代品 |
| ZFS 健康指標／成員狀態無法取得 | 對應 missing 規則 | for 2m | 若發生，先查採集；不直接等同兩顆磁碟故障 |

依據 [正式告警設定](../configs/grafana-alerts-stable.yaml)。倉庫的 [Prometheus 範例](../configs/prometheus.yml) 中 NAS 採集為 15s；**實際 VM 若調整過，依現場配置為準**。這些數字不是「一分鐘內必定收到通知」的 SLA；仍包含採集、評估邊界、Pending、通知分組與傳送時間。不要為了錄影把 for 任意改成 0。

### 5.2 唯讀查詢 Prometheus 已採集的證據

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

### 5.3 驗證兩種通知都到達

1. 留存規則實例 Alerting 的時間、A instance／pool 與規則名稱。
2. 到指定 Email 信箱與 Discord 頻道確認收到**本次真實異常**通知，分別記錄時間。
3. 區分關機離線通知、pool 降級通知及成員異常；同一封／則通知可能分組包含多個告警。
4. 如果只有 Contact point Test 收到，還不能通過本步。若規則已 Alerting 但沒通知，檢查 Contact point、Notification policies、Silence／Mute timings 及傳送日誌，見 [原教學第 5 節](monitoring-vm-from-zero.md#5-登入-grafana測試通知並完成驗收)。

**截圖 D06：** Grafana Alerting；**D07：** Email／Discord 真實告警。保留時間與 instance，遮蔽私人地址、Webhook 及秘密。

## 6. 在 VMware 加入兩顆新資料碟

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

## 7. 新碟未顯示時，在 A 掃描裝置

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

## 8. 逐顆 Replace 並追蹤 resilver

### 8.1 先替換第一顆

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

### 8.2 再替換第二顆

1. 依同一 UI 路徑選第二個故障成員。
2. Replace 指向第二顆新碟，不能誤選已投入重建的第一顆。
3. 追蹤第二次 resilver，等完成後核對 mainpool。
4. 若新碟無法選取，先確認未屬於其他 pool、實際容量足夠、沒有因裝置名稱重排而選錯；不以 Add VDEV／重新建立 pool 代替 Replace。

**截圖 D10：** 第一顆 Replace／重建；**D11：** 第二顆 Replace／重建完成。故障成員與新碟對應清楚，不能只有磁碟清單。

## 9. 驗證修復與告警恢復

### 9.1 TrueNAS A

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

### 9.2 Windows 檔案完整性

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

### 9.3 Grafana 與雙管道

重跑第 5.2 節的唯讀查詢，核對 A 的 up＝1、有效 ONLINE 健康序列值為 1、成員異常＝0、狀態命令退出值＝0。到 Grafana 看**A／mainpool 對應實例**恢復 Normal，不能因 B 或其他規則還在告警而誤判本輪，也不能只看整個資料夾總狀態。

接著核對 Email／Discord 的恢復通知；若 contact point 的「停用恢復訊息／Disable resolved message」有啟用，恢復通知就不會送出，需要依實際設定處理並記錄。規則恢復不代表通知一定已送達，記下兩者時間。

**截圖 D12：** ONLINE／兩顆替換後成員；**D13：** hash 與恢復後讀寫；**D14：** 規則 Normal 與 Email／Discord resolved。

## 10. 本輪結果怎麼填

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

## 11. Word 與簡報該保留哪些證據

Word 圖 8-1 的合併圖可選四格：**D04 雙碟降級 → D07 真實通知 → D10／D11 換碟重建 → D12／D13 ONLINE 與檔案核對**。完整磁碟對照、時間表與 D01–D14 留在 GitHub／演練紀錄，紙本只放關鍵證據。

展示說明可寫：「RAID-Z2 讓雙碟故障後仍有機會維持資料服務，監控則主動指出看不見的冗餘損失，讓管理員提早更換磁碟並完成復原。」若本輪採關機操作，另外說明 VMware 人為停機時間，不宣稱全程無中斷。

## 官方操作依據

- [TrueNAS Replacing Disks](https://www.truenas.com/docs/scale/storage/disks/replacingdisks/)：Replace 與重建。
- [TrueNAS Managing Pools](https://www.truenas.com/docs/scale/storage/pools/managepools/)：RAID-Z2 容錯與 pool 操作。
- [Broadcom VMware Workstation 新增虛擬磁碟](https://knowledge.broadcom.com/external/article/344712/creating-and-adding-a-new-virtual-disk-t.html)：只引用 VM 關機、Settings、新建 VMDK 的部分；該文章後段 Windows 初始化磁碟不適用於此 NAS Replace 流程。
- [Broadcom Workstation 虛擬硬體設定](https://knowledge.broadcom.com/external/article/315640/removing-unnecessary-hardware-from-vmwar.html)。
- 專案依據：[SNMP／ZFS 與通知建置](monitoring-vm-from-zero.md)、[正式告警](../configs/grafana-alerts-stable.yaml)、[Prometheus 範例](../configs/prometheus.yml)。
