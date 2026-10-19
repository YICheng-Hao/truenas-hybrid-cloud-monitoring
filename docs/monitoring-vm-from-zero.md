# 從零建立 Rocky Linux 9／10 監測 VM

本文件使用 2026-10-19 已確認正常的 hrStorage 容量查詢。適用於全新監測 VM；目前正常運作的 VM 不需要重建。安裝器偵測到非本安裝器建立的既有 Prometheus／Grafana 設定時會停止，避免覆寫。

## 1. 建立 VM 與準備資料

在 VMware 建立 Rocky Linux 9／10 x86_64 VM，建議 2 vCPU、4 GiB RAM、40 GiB 系統碟，設定管理 IP、預設閘道與 DNS。下列命令以 root 執行；以一般管理帳號登入後執行 `sudo -i` 即可，不必開放 root SSH 登入。

先準備下列資料。安裝器會逐項詢問；密鑰與密碼使用隱藏輸入，不必修改程式碼。

| 輸入項目 | 本專案預設／取得方式 |
|---|---|
| A 站 Tailscale IP | 100.114.236.88 |
| B 站 Tailscale IP | 100.113.107.95 |
| 管理來源網段 | 例如 192.168.23.0/24；依你的管理端實際來源填寫 |
| Grafana 瀏覽網址 | 自動依 VM 管理 IP 提供，例如 http://192.168.23.158:3000/ |
| S3 儲存桶／Region | truenas-backup-myhome-2026／ap-east-2 |
| TrueNAS A Cloud Sync Task ID | 預設 1；應與實際雲端同步任務 ID 相同 |
| SNMP Community | 預設 public，兩站須一致 |
| 監控專用 IAM Access Key ID／Secret | 使用僅授權目標 bucket 的 s3:ListBucket 帳號，不必給寫入／刪除權限 |
| 寄件 Gmail／Google App Password | 使用應用程式密碼，不能填一般 Gmail 登入密碼 |
| 告警收件 Email | 多個地址以分號分隔 |
| Discord Webhook URL | 在目標 Discord 頻道建立 Webhook |
| Grafana admin 密碼 | 自訂至少 12 字元 |

監控 IAM 政策範例（bucket 名稱若不同，請改成你的名稱）：

```json
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Action": "s3:ListBucket",
    "Resource": "arn:aws:s3:::truenas-backup-myhome-2026"
  }]
}
```

監測 VM、A、B 須加入同一個 Tailscale 網路，且 Tailnet 存取規則允許 VM 對兩站 UDP 161、A 對 VM TCP 9108。管理端須能連線 VM TCP 3000／9090。安裝過程需對外下載 Rocky、Tailscale、GitHub、Grafana、AWS CLI 套件，寄信需出站 TCP 587。

## 2. TrueNAS A／B 的 SNMP 前置設定

如果目前兩站的 SNMP 與磁碟成員監控已正常，保留既有設定，直接進入步驟 3。

全新 TrueNAS 則分別登入 A、B Web UI，在【系統／Settings → 服務 → SNMP → 編輯】設定 Community 為 `public`，在附屬參數（Auxiliary Parameters）加入以下一行，保留其他既有內容：

```text
extend zfs /usr/sbin/zpool status -P
```

儲存、啟動 SNMP、勾選自動啟動；若原本已啟動，重啟 SNMP 套用。不要重複加入同名 `extend zfs`。也可將儲存庫的 `scripts/configure-truenas-snmp-stable.py` 複製至 NAS 後以 root 執行；腳本會備份原附屬參數並保留其他內容。這個 NAS 腳本與監測 VM 安裝器是不同用途。

本流程只依賴標準 hrStorage、TrueNAS 原生健康字串與上述 zfs 成員來源，不依賴先前排錯用的 `zfs_capacity`／`zfsUsablePool` 設定。

## 3. 在全新 Rocky VM 貼上安裝命令

登入 Rocky VM 後，先取得 root shell：

```bash
sudo -i
```

接著整段貼上：

```bash
(
  set -e
  dnf install -y git python3 python3-pyyaml
  if [ -d /root/truenas-hybrid-cloud-monitoring/.git ]; then
    git -C /root/truenas-hybrid-cloud-monitoring pull --ff-only origin main
  else
    git clone https://github.com/YICheng-Hao/truenas-hybrid-cloud-monitoring.git /root/truenas-hybrid-cloud-monitoring
  fi
  python3 /root/truenas-hybrid-cloud-monitoring/scripts/setup-monitoring-vm.py
)
```

若儲存庫仍為私人，`git clone` 需要你的 GitHub 帳號與可讀取此儲存庫的存取權；HTTPS 驗證不能使用 GitHub 一般登入密碼。不要將 Token 寫入網址或提交到儲存庫。

依畫面逐項輸入步驟 1 的資料。預設值正確就按 Enter；出現 Tailscale 登入網址時，用瀏覽器開啟並完成登入／核准節點，讓命令繼續。

安裝器會完成：

- 安裝 chrony、firewalld、Tailscale、AWS CLI v2。
- 停用 Cockpit，釋放 TCP 9090。
- 安裝 SNMP Exporter 0.26.0、Prometheus 2.54.1、Grafana 13.2.4。Prometheus 與 SNMP Exporter 下載檔比對官方 SHA256 清單。
- 部署 S3 清單／費用估算 Exporter 與 Cloud Sync Receiver。
- 自動帶入監測 VM Tailscale IP、A／B 位址、bucket 與 task ID。
- 自動載入 Prometheus 資料源、10 個面板、9 條告警、繁體中文通知模板、Email＋Discord 聯絡點與預設通知路由。
- 依管理來源網段開放 3000／9090，並加入僅 A 站可連入 9108 的來源規則；保留其他既有防火牆規則。
- 啟用服務開機自動啟動，檢查 S3 API 及兩站容量、磁碟成員指標。
- 實際檢查 Grafana Prometheus 資料源與九條規則的評估結果；規則僅載入但評估出錯時，不會宣告安裝通過。

所有輸入保存於 `/root/monitoring-setup.json`，權限 600。檔案含有秘密，不可上傳 GitHub。Receiver Token 自動產生；重跑時保留，不會任意更換。安裝器也不會刪除既有成功回報檔。

若因網路、IAM、SNMP 等原因中斷，修正畫面指出的原因後，重跑同一命令即可，不必重新 clone：

```bash
python3 /root/truenas-hybrid-cloud-monitoring/scripts/setup-monitoring-vm.py
```

若上次輸入有誤，以 `vi /root/monitoring-setup.json` 修正對應欄位後再重跑。此重跑方式適用於由本安裝器建立的 VM。

## 4. 將真實 Cloud Sync 成功回報接回新 VM

在監測 VM 執行以下命令，顯示安裝器已帶入實際 IP 與 Token 的 Post-script：

```bash
cat /root/truenas-cloudsync-postscript.sh
```

複製顯示的完整腳本，貼到 TrueNAS A【資料保護 → 雲端同步作業 → 編輯你的 S3 任務 → 進階選項 → Post-script】，取代舊 VM 的回報腳本並儲存。腳本內沒有要你自行補的 IP／Token。

接著在 TrueNAS A 對該任務按【Run Now】，確認任務 SUCCESS。回 Grafana 檢查「Cloud Sync 距成功回報」是否取得最近成功時間。此欄顯示的是實際任務回報；在第一次真實成功回報以前顯示無資料是預期狀態。

不要在監測 VM 執行 Post-script，也不要手動發送 `/success` 假造成功回報。

## 5. 登入 Grafana、測試通知並完成驗收

開啟安裝器最後顯示的 Grafana 網址，帳號 `admin`，密碼為剛才輸入的值。面板已自動載入，不必再手動匯入 JSON。到【Dashboards → TrueNAS_Alerts】開啟面板。

到【Alerting → Contact points → NAS_Alerts_Email_Discord】分別對 Email 與 Discord 執行 Test，確認兩邊收到通知。安裝成功只代表設定已載入，不代表 Gmail／Discord 已實際收訊；這一步必須驗收。

再到【Alerting → Alert rules → TrueNAS_Alerts】確認九條規則。實際儲存池仍 DEGRADED 時，相應規則應告警，不必為了截圖強行讓它 Normal。告警群組每分鐘評估一次，規則各有持續時間；不是拔碟後立刻寄信。

| 規則 | 持續時間 |
|---|---|
| TrueNAS／S3 採集離線 | 2 分鐘 |
| 根掛載點使用率超過 85% | 5 分鐘 |
| 主備已用空間差異超過 10 GiB（參考） | 15 分鐘 |
| Cloud Sync 成功回報超過 28 小時 | 5 分鐘 |
| 儲存池 DEGRADED | 1 分鐘 |
| 儲存池其他異常狀態 | 1 分鐘 |
| 儲存池健康指標缺失 | 2 分鐘 |
| 磁碟成員／VDEV 異常 | 0 秒；仍需等下一次評估與通知分組等待 |
| 磁碟成員來源缺失／執行失敗 | 2 分鐘 |

整體唯讀驗證：

```bash
python3 /root/truenas-hybrid-cloud-monitoring/scripts/setup-monitoring-vm.py --verify-only
systemctl is-active snmp_exporter s3_realtime_exporter cloudsync-monitor prometheus grafana-server
curl -fsS http://127.0.0.1:9090/-/ready
curl -fsS http://127.0.0.1:3000/api/health
```

瀏覽 `http://監測VM管理IP:9090/targets`，應看到 4 個 Job、5 個 Target（TrueNAS SNMP 含 A／B 兩個 Target）均為 UP。

若某服務未啟動，讀取對應服務日誌，例如：

```bash
journalctl -u grafana-server -n 80 --no-pager
journalctl -u snmp_exporter -n 80 --no-pager
journalctl -u s3_realtime_exporter -n 80 --no-pager
journalctl -u cloudsync-monitor -n 80 --no-pager
```

## 6. 面板數值的正確意義

容量沿用已驗證的 hrStorage 根掛載點查詢，不用六顆磁碟原始容量相加，因此不會把 RAID-Z2 原始磁碟容量直接當作可用容量。根掛載點「已用」不等於整個 ZFS 池所有子資料集、快照的總占用量；例如根資料集本身只有少量資料，其已用數字可能很小。兩站差異也不能據此判定複寫失敗。完整面板解釋見 [dashboard-panels.md](dashboard-panels.md)。

容量顯示單位為二進位 bytes。六顆 500 GiB RAID-Z2 的名目資料容量約 2000 GiB（約 1.95 TiB），還需扣 ZFS 保留與其他開銷；六顆 500 GB 則是約 2000 GB（約 1.82 TiB），兩種磁碟標示不能混用。面板顯示 SNMP 實際取得的值，不硬寫成 2 TB。

S3 費用是單一儲存單價 × 目前物件容量的估算，不含請求、取回、生命週期、最低保存期與流量費，不等於 AWS 帳單。

本次驗證包含設定產生測試、Prometheus／SNMP 設定檢查，以及 Grafana 13.2.4 真實程序載入九規則、十面板與雙通知聯絡點。尚未在全新 Rocky VM 完成整套系統級安裝演練；現場仍須依步驟 4、5 驗收真實 Cloud Sync 與通知收訊。

Rocky 10 支援修正：依實際主版本選用 Tailscale 官方 RHEL 9／10 軟體源。版本偵測測試涵蓋 Rocky 10.2；尚未在完整 Rocky 10 VM 做端到端安裝驗證。官方來源：https://pkgs.tailscale.com/stable/ 。安裝命令使用子 Shell，失敗時不會因 `set -e` 結束目前 SSH Shell；已有專案目錄時採快轉更新，不重複 clone。

## 內部測試紀錄

本流程的測試輪數、發現問題與修正結果見 [安裝測試報告](installation-test-report.md)。完整 VM 整合測試使用真實 Rocky／systemd／SELinux 與正式監控程式；外部服務與 Tailnet 身分使用隔離替身，不代表已驗證你的真實帳號、跨站網路或硬碟重建。
