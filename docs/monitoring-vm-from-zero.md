# 從零建立 Rocky Linux 9／10 監測 VM

本文件使用 2026-10-19 已確認正常的 hrStorage 容量查詢。適用於全新監測 VM；目前正常運作的 VM 不需要重建。安裝器偵測到非本安裝器建立的既有 Prometheus／Grafana 設定時會停止，避免覆寫。

2026-10-20 已在 Rocky 9.8／10.2 隔離 VM 完成建置、故障／恢復通知、重跑與重新開機驗證；測試輪數及外部服務替身範圍見 [測試報告](installation-test-report.md)。

## 1. 先建立 VM，單獨完成 Tailscale 登入

在 VMware 建立 Rocky Linux 9／10 x86_64 VM，建議 2 vCPU、4 GiB RAM、40 GiB 系統碟。依專案架構保持 Host-Only，透過既有 Gateway VM 上網；先設定管理 IP、預設閘道與 DNS。下列命令只在監測 VM 執行，不是在 TrueNAS Shell。

### 1-1. 下載程式（不會開始詢問 AWS 或 Gmail）

一般管理帳號登入後先執行：

```bash
sudo -i
```

再整段貼上：

```bash
(
  set -e
  dnf install -y git python3 python3-pyyaml
  if [ -d /root/truenas-hybrid-cloud-monitoring/.git ]; then
    git -C /root/truenas-hybrid-cloud-monitoring pull --ff-only origin main
  else
    git clone https://github.com/YICheng-Hao/truenas-hybrid-cloud-monitoring.git /root/truenas-hybrid-cloud-monitoring
  fi
)
```

私人儲存庫會詢問 GitHub Username／Password。Username 填 GitHub 帳號；Password 填有此儲存庫讀取權限的 Personal Access Token，不是 GitHub 登入密碼。輸入 Token 不顯示字元。不要把 Token 放進 clone 網址。

### 1-2. 只安裝並登入 Tailscale

```bash
python3 /root/truenas-hybrid-cloud-monitoring/scripts/setup-monitoring-vm.py --tailscale-only
```

未登入時，`tailscale up` 會在終端機顯示登入網址。用 Windows 瀏覽器開啟它，登入 **A、B 所在的同一個 Tailnet**，必要時在管理頁核准節點，命令才會完成。本步驟不詢問 AWS、Email、Discord、Grafana 密碼，也不安裝監控服務。

若顯示「此 VM 已登入 Tailscale」，不出現新登入網址屬正常情況，直接確認：

```bash
tailscale status
tailscale ip -4
```

`tailscale ip -4` 顯示的是 **監測 VM 自己的 100.x IP**，安裝器自動讀取，不要拿它填 A／B 欄位。A、B 尚未加入 Tailnet 時，請先完成各 NAS 的 Tailscale 設定；本命令只處理監測 VM。

| 位址用途 | 本專案範例 | 用在哪裡 |
|---|---|---|
| TrueNAS A Tailscale IP | 100.114.236.88 | 安裝器 A 站欄位；請核對 Tailscale 管理頁的 NAS 節點 |
| TrueNAS B Tailscale IP | 100.113.107.95 | 安裝器 B 站欄位；請核對 B 站 NAS 節點 |
| 監測 VM 管理 IP | 截圖為 192.168.23.158 | Grafana 網址 http://192.168.23.158:3000/ |
| 管理電腦的來源網段 | 管理電腦在該網段時用 192.168.23.0/24 | 防火牆允許誰開 Grafana／Prometheus |
| 監測 VM Tailscale IP | 依 tailscale ip -4 的結果 | 安裝器自動產生 Cloud Sync 回報網址 |

**你的截圖中 `可管理此 VM 的來源網段` 填了 `192.168.23.158`，這是 VM 位址。** 若管理電腦確實在 192.168.23.0/24，填 `192.168.23.0/24`。若只開給單台電腦，填「該管理電腦 IP/32」。不要把監測 VM 的 IP 當作管理來源。使用其他 Host-Only 網段或經 Gateway 路由時，依實際管理來源填寫；預設 /24 只是建議，不代表安裝器已確認你的網路。

監測 VM、A、B 必須可經 Tailnet 互通，存取規則允許 VM 對 NAS UDP 161、A 對 VM TCP 9108。管理端須能連 VM TCP 3000／9090。安裝需對外下載套件，Gmail 寄信需出站 TCP 587。

## 2. TrueNAS A／B 的 SNMP 前置設定

如果目前兩站的 SNMP 與磁碟成員監控已正常，保留既有設定，直接進入步驟 3。

全新 TrueNAS 則分別登入 A、B Web UI，在【系統／Settings → 服務 → SNMP → 編輯】設定 Community 為 `public`，在附屬參數（Auxiliary Parameters）加入以下一行，保留其他既有內容：

```text
extend zfs /usr/sbin/zpool status -P
```

儲存、啟動 SNMP、勾選自動啟動；若原本已啟動，重啟 SNMP 套用。不要重複加入同名 `extend zfs`。也可將儲存庫的 `scripts/configure-truenas-snmp-stable.py` 複製至 NAS 後以 root 執行；腳本會備份原附屬參數並保留其他內容。這個 NAS 腳本與監測 VM 安裝器是不同用途。

本流程只依賴標準 hrStorage、TrueNAS 原生健康字串與上述 zfs 成員來源，不依賴先前排錯用的 `zfs_capacity`／`zfsUsablePool` 設定。

## 3. 確認每個欄位，再啟動監控安裝

### 3-1. 必填資料與取得方式

這個安裝器建立完整的 S3、Email、Discord 監控，以下欄位皆必填，不能直接留白。一般欄位顯示 `[預設值]` 時，確認正確才按 Enter；密碼／金鑰為隱藏輸入，不顯示星號。不要把真實秘密貼到 GitHub 或截圖分享。

| 安裝器欄位 | 要填什麼 | 從哪裡取得／範例 |
|---|---|---|
| A／B 站 Tailscale IP | 各 NAS 的 100.x IPv4 | Tailscale 管理頁找 A、B NAS；不是監測 VM IP |
| 可管理此 VM 的來源網段 | 管理電腦所在 CIDR | 例如 192.168.23.0/24；單台電腦用其 IP/32；必須含斜線 |
| Grafana 瀏覽網址 | 監測 VM 網頁完整位址 | 截圖環境可用 http://192.168.23.158:3000/；不是 Tailscale 登入網址 |
| S3 儲存桶 | 目的 bucket 名稱 | AWS S3 → Buckets；例如 truenas-backup-myhome-2026；不加 s3:// |
| AWS Region | bucket 實際區域代碼 | AWS S3 bucket 內容確認；預設 ap-east-2，不能只依預設猜測 |
| TrueNAS A Cloud Sync Task ID | S3 同步任務的 id 數字 | 依下方 TrueNAS Shell 命令確認；不是任務名稱或暫時的執行 job ID |
| 兩站 SNMP Community | NAS SNMP 設定的相同 Community | 本流程為 public；若你改過，兩站與此欄都要一致 |
| 監控 IAM Access Key ID | IAM 存取金鑰 ID | AWS IAM → Users → 監控使用者 → Security credentials → Access keys |
| 監控 IAM Secret Access Key | 同一把 IAM 金鑰的秘密值 | 建立 Access key 時顯示／下載的憑證；不是回報 Token |
| 寄件 Gmail 帳號 | 寄出告警的完整 Gmail | 可以用你自己的 Gmail |
| Google App Password | 該寄件帳戶的 16 碼應用程式密碼 | Google 帳戶 → 安全性 → 啟用兩步驟驗證 → 應用程式密碼；不可用一般登入密碼 |
| 告警收件 Email | 接收通知的完整地址 | 可以和寄件信箱相同；多個用分號，例如 a@example.com;b@example.com |
| Discord Webhook URL | 完整 Webhook 網址 | 目標伺服器／頻道 → 編輯頻道 → 整合 → Webhooks → 建立 → 複製 URL；需有管理 Webhook 權限 |
| Grafana admin 密碼 | 自行設定至少 8 字元 | 這是新 Grafana 的登入密碼；不是 NAS、GitHub 或 Gmail 密碼 |

Google 應用程式密碼可從 https://myaccount.google.com/apppasswords 開啟；如果沒有此功能，先確認兩步驟驗證及帳戶政策。兩個 IAM 欄位須來自同一把金鑰；Secret 遺失時無法重新查看，需建立新金鑰。不要為了監控填 AWS root 金鑰。

在 **TrueNAS A → 系統 → Shell** 貼上以下唯讀命令，僅顯示辨識任務需要的欄位：

```bash
midclt call cloudsync.query | python3 -c 'import json,sys; print(json.dumps([{k:t.get(k) for k in ("id","description","path","direction","transfer_mode")} for t in json.load(sys.stdin)],ensure_ascii=False,indent=2))'
```

依說明及來源路徑找出你要監控的 S3 任務，例如 `/mnt/mainpool/data`；以該列的 `id` 填入安裝器。若有多個相似任務，回雲端同步作業核對；本流程只監控填入的一個 Task ID。

監控 IAM 使用以下政策，bucket 不同時替換 Resource 最後的名稱；它只需列舉，不需寫入／刪除權限。此金鑰與 TrueNAS 上傳 S3 使用的憑證可以分開。

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


### 3-1-1. 建立監控專用 IAM 使用者並申請金鑰

Word 第七章僅保留建置順序、必要欄位及驗收證據；本節保存完整 AWS 操作與監測 VM 設定說明。

1. 使用有 IAM 管理權限的 AWS 身分登入主控台；不需另註冊一個 AWS 帳戶。原有 S3 bucket、TrueNAS 備份使用者與同步作業沿用。
2. 開啟 **IAM → Policies → Create policy → JSON**，貼上前述政策。Resource 改成實際 bucket ARN，格式為 `arn:aws:s3:::桶名`，不要加 `/*`；政策命名為 `S3-ListBucket-Only`。只授權目標桶的 `s3:ListBucket`，不需 GetObject、PutObject、DeleteObject 或 CloudWatch API 權限。
3. 開啟 **IAM → Users → Create user**，輸入 `prometheus-cloudwatch-reader`。不啟用主控台存取；選擇直接附加上述政策，建立後到 Permissions 確認。
4. 開啟該使用者 **Security credentials → Access keys → Create access key**。依本專案在 AWS 外部 Rocky Linux VM 使用 AWS CLI 的情境選擇 **Command Line Interface (CLI)**，閱讀並確認提示，描述標籤可自行填寫。
5. 建立後保存同一組 **Access Key ID** 與 **Secret Access Key**，可下載 CSV。Secret 只在建立時顯示；遺失需重新建立金鑰，再更新安裝器。不要把 CSV、金鑰或含秘密的截圖上傳 GitHub。
6. 將兩個值分別填入安裝器的監控 IAM 欄位。這是重複第六章「申請存取金鑰」的流程，但使用監控專用身分，不沿用備份寫入憑證。若已有該監控使用者的有效金鑰，可直接使用。

| 身分 | 所在位置 | 用途 |
|---|---|---|
| 原有 AWS 帳戶 | AWS | 管理既有 S3 與 IAM，不另註冊帳戶 |
| `truenas-backup-user` | AWS IAM | 原有 TrueNAS 備份寫入身分 |
| `prometheus-cloudwatch-reader` | AWS IAM | 專用 S3 清單讀取金鑰 |
| `cloudwatch_exporter` | Rocky Linux | 安裝器建立的系統帳號，不用於登入 AWS |

### 3-1-2. S3 Exporter 由安裝器部署的內容

AWS IAM 政策、使用者及存取金鑰須先由管理員建立。監測 VM 的以下部分已由安裝器處理，使用安裝器流程時不要再重複手動建立另一套服務：

| 項目 | 路徑或值 |
|---|---|
| Linux 系統使用者 | `cloudwatch_exporter`，不允許一般登入 |
| AWS 憑證目錄 | `/etc/cloudwatch_exporter`，權限 750 |
| AWS 憑證檔 | `/etc/cloudwatch_exporter/credentials`，擁有者 cloudwatch_exporter，權限 600 |
| Exporter 程式 | `/usr/local/bin/s3_realtime_exporter.py` |
| 環境變數檔 | `/etc/s3-exporter.env` |
| systemd 服務 | `s3_realtime_exporter.service` |
| 指標入口 | `http://127.0.0.1:9107/metrics`，僅本機 |

唯讀檢查服務及 S3 指標：

```bash
systemctl status s3_realtime_exporter --no-pager
curl -fsS http://127.0.0.1:9107/metrics
```

需要直接核對物件數與容量時，在監測 VM 的 root Shell 執行以下命令，將 Region、bucket 改成安裝時使用的值：

```bash
su -s /bin/bash -c 'AWS_SHARED_CREDENTIALS_FILE=/etc/cloudwatch_exporter/credentials AWS_DEFAULT_REGION=ap-east-2 aws s3 ls s3://truenas-backup-myhome-2026/ --recursive --summarize' cloudwatch_exporter | tail -5
```

此命令只列舉物件，不下載或修改物件；大型 bucket 列舉可能較久並產生請求費。應看到 Total Objects 與 Total Size。若 AccessDenied，核對金鑰對應使用者、附加政策及 bucket ARN；若 bucket policy、SCP 或 permissions boundary 有明確拒絕，也需由 AWS 管理員檢查。錯誤時不要改用 root 金鑰或直接授予完整 S3 權限。

監控新增的是清單讀取權限；原有 bucket、生命週期及 TrueNAS 上傳憑證不需因本章重新建立。費用指標只依容量及設定單價估算，不等於 AWS 帳單。

### 3-2. 在監測 VM 執行安裝

```bash
python3 /root/truenas-hybrid-cloud-monitoring/scripts/setup-monitoring-vm.py
```

安裝器先確認 Tailscale 已登入，再逐欄詢問。格式有誤會留在同一欄重填，避免全部填完才得知錯誤。這是格式檢查；IAM 權限、S3 存取與 NAS 指標會在安裝驗證時確認，Gmail／Discord 必須在步驟 5 實測收訊。

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

若上次填錯，使用逐欄修改模式，不必自己改 JSON：

```bash
python3 /root/truenas-hybrid-cloud-monitoring/scripts/setup-monitoring-vm.py --edit-config
```

一般欄位按 Enter 保留顯示的舊值；秘密欄位按 Enter 保留舊值，輸入新值則替換。完成後會繼續安裝。此方式適用於由本安裝器建立的 VM。既有 Grafana 資料庫的 admin 密碼不會因重跑而重設；修改其他欄位時保留原 Grafana 密碼，若忘記密碼需另做 Grafana 密碼重設。

## 4. 必做：更新 TrueNAS A 的 Cloud Sync Post-script

### 4-1. 手動寫入 TrueNAS Post-script（建議先使用此方式）

**這一步需要管理員在 TrueNAS A 完成。監測 VM 安裝器只產生回報腳本，不會自動改寫 NAS 的雲端同步作業。每次重建監測 VM、變更 Receiver IP 或 Token 後，都要重新核對並更新 NAS。**

1. 在**監測 VM 的 root 終端機**執行：

   ```bash
   cat /root/truenas-cloudsync-postscript.sh
   ```

2. 複製輸出的**完整短腳本**：從第一行 `#!/bin/sh` 到最後一行包含 `Cloud Sync callback failed` 的命令。不要複製終端機提示字元或 Markdown 的三個反引號。
3. 在 **TrueNAS A Web UI** 開啟【資料保護 → 雲端同步作業 → 編輯對應 S3 任務 → 進階選項 → **Post-script**】。
4. 若欄位中只有舊監控回報腳本，先全選刪除，再貼上剛才的完整短腳本。**網址與 Authorization Token 必須一起替換，不能只改 IP。** 若還有其他業務用途的命令，先保留它們，只完整替換舊監控回報區塊。
5. 按【儲存】，重新開啟任務，確認 Post-script 已保存。不是貼到 Pre-script，也不是只在監測 VM 終端機把內容顯示出來就完成。
6. 依第 4-3 節執行一次真實同步並核對回報。

| 貼入內容 | 核對重點 |
|---|---|
| `Authorization: Bearer` 後面的值 | 使用這台監測 VM 產生的完整新 Token；不要保留舊 VM 的 Token，不是 AWS 金鑰 |
| 回報網址 | 完整為 `http://監測VM的TailscaleIP:9108/success`，含連接埠與路徑；以產生檔案為準 |
| `${CLOUD_SYNC_ID}` | 原樣保留，由 TrueNAS 執行任務時提供，不改成手填數字 |
| 行末反斜線 `\` | 完整保留，不貼入 `&#x20;` 或自行折斷命令 |
| 結尾的 logger 命令 | 完整保留，回報失敗時留下訊息 |

例如本次新監測 VM 的回報位址為 `http://100.108.201.34:9108/success`；這只是現場案例，其他人應使用自己產生檔案中的位址。GitHub 文件不保存真實 Token。B 站不需加入這個 A 站 S3 任務的回報。

**現場已遇到的錯誤：只把舊網址改成新網址，卻保留舊 Token。** Receiver 會拒絕驗證；本專案 Receiver 的 Token 不符時回傳 HTTP 403。使用 `curl -f` 時，HTTP 錯誤可能呈現 `Post-script failed with exit code 22`；22 本身不能單獨判斷為 403，需配合任務日誌確認。本次截圖可直接確認兩端 Token 不一致，完整替換腳本後，使用者回報已恢復正常。不能僅將 `|| true` 加回去讓任務表面成功，必須確認 Receiver 收到新的成功回報。

### 4-2. 可選：透過 TrueNAS Shell 更新（與手動方式擇一）

**監測 VM 安裝與 NAS 設定是兩個步驟，安裝器不會自行登入 NAS 修改 Cloud Sync。** 在監測 VM 的 root Shell 執行：

```bash
git -C /root/truenas-hybrid-cloud-monitoring pull --ff-only origin main
python3 /root/truenas-hybrid-cloud-monitoring/scripts/prepare-cloudsync-handoff.py
cat /root/truenas-cloudsync-apply-command.sh
```

工具會讀取 VM 已安裝的 Receiver IP／Token 及已保存的 Task ID，產生更新命令；此時尚未修改 NAS。

複製最後一行顯示的全部輸出（從 `python3 - <<'TRUENAS_CLOUDSYNC_UPDATE'` 到最後獨立一行 `TRUENAS_CLOUDSYNC_UPDATE`），貼到 **TrueNAS A 的 root Shell**。一般管理帳號開 Shell 時先執行 `sudo -i`。不要把這份更新命令貼進 Post-script 欄位；它是修改該欄位的 NAS 管理命令，和 curl 回報腳本用途不同。

命令會按 Task ID 讀取任務，確認是預期 bucket 的 PUSH 任務，先將舊 Post-script 備份到 NAS 的 `/root/cloudsync-postscript-backups/`（權限 600），再只更新 `post_script`，最後讀回核對。排程、來源、目的、COPY／SYNC 模式及 Pre-script 不變。已一致就不重寫；若舊內容包含無法辨識的自訂命令，會停止，改用上方 Web UI 方式保留其他命令。

工具不用手填 IP／Token，不會輪替 Token、啟動同步、假造成功回報或重裝 Grafana。產生的命令含秘密，只在你的 VM／NAS 間複製，不要提交 GitHub 或分享截圖。NAS root 目錄的備份應另依你的備份政策保存。

### 4-3. 執行真實同步，再核對 Receiver 與 Prometheus

兩種更新方式完成後，都要在 TrueNAS A 對該任務按【Run Now】，等待任務 SUCCESS。接著在**監測 VM**執行：

```bash
python3 /root/truenas-hybrid-cloud-monitoring/scripts/prepare-cloudsync-handoff.py --check
```

此命令唯讀檢查指定 Task ID 是否出現在 Receiver `/metrics` 與 Prometheus，並顯示 Receiver 收到回報的 UTC 時間。應對照剛才任務完成時間；只有歷史紀錄不代表本次成功回報。Prometheus 尚未採集時，等待約 1 分鐘重試，之後回 Grafana Refresh。告警解除仍需等待規則評估及通知排程。

**Cloud Sync 任務 SUCCESS 不能單獨證明回報成功。** 舊腳本的 `|| true` 會吞掉 curl 錯誤；新腳本在回報失敗時記錄 logger 訊息，但也不會把已完成的資料傳輸改成失敗。首次真實回報前顯示「尚無紀錄」且超時規則告警，表示監控未收到證據，不等於已證明 S3 傳輸失敗。

| 異常 | 檢查方式 |
|---|---|
| 仍然使用舊網址 | 重新開啟 NAS 任務確認，網址應是新 VM 的 Tailscale IP 加 `:9108/success` |
| 連線逾時／拒絕 | 核對 NAS 到 VM 的 Tailnet 權限、TCP 9108、防火牆、Receiver 狀態與監聽 IP |
| HTTP 403／只改網址後仍失敗 | 依第 4-1 節完整替換 Post-script，包含新 Token；不要只改 IP |
| HTTP 400／未提供 CLOUD_SYNC_ID | 確認在真正 Cloud Sync Post-script 執行，保留 `${CLOUD_SYNC_ID}` |
| Receiver 有紀錄、Grafana 尚無紀錄 | 比對安裝設定 Task ID 與實際任務 id，確認 Prometheus 的 cloudsync_success Target 為 UP |

2026-10-20 現場問題與修復：NAS 最初指向舊 VM 且缺少連接埠／路徑；改網址後仍保留舊 Token，回報驗證失敗。依第 4-1 節完整替換 Post-script 後，使用者回報已可正常使用。這是使用者現場結果，並非新增一輪自動化 VM 測試。新增工具的驗證範圍見 [Cloud Sync 設定交接測試](cloudsync-handoff-test-report.md)。

API 依據：[TrueNAS 25.10 cloudsync.update](https://api.truenas.com/v25.10/api_methods_cloudsync.update.html) 的 `post_script` 欄位；工具在 NAS 本機透過 `midclt` 呼叫。

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

歷史完整 VM 測試的範圍及提交見下方報告；其中 Tailnet 身分、NAS、S3、通知服務使用隔離替身。本次輸入流程調整的測試另外記錄於 [輸入流程修正驗證](input-flow-test-report.md)，不把歷史 VM 通過結果當作本次真實 Tailscale 登入已通過。

## 內部測試紀錄

本流程的測試輪數、發現問題與修正結果見 [安裝測試報告](installation-test-report.md)。完整 VM 整合測試使用真實 Rocky／systemd／SELinux 與正式監控程式；外部服務與 Tailnet 身分使用隔離替身，不代表已驗證你的真實帳號、跨站網路或硬碟重建。

## Word 精簡版對照與補充操作

Word 第七章保留建置順序，完整操作依本文件各節執行：

| Word 項目 | GitHub 對應 |
|---|---|
| VM 建立、套件與 GitHub 下載／私人儲存庫登入 | 第 1、1-1 節 |
| Tailscale 登入網址、已登入而無新網址、A／B 與 VM IP 區分 | 第 1-2 節 |
| 安裝器全部欄位與 Cloud Sync Task ID 唯讀查詢 | 第 3-1 節 |
| IAM 政策、專用使用者、重新申請 Access Key／Secret | 第 3-1、3-1-1 節 |
| Linux 系統帳號、AWS 憑證與 S3 Exporter 路徑及檢查指令 | 第 3-1-2 節 |
| NAS SNMP 附屬參數與重啟 | 第 2 節 |
| 重跑、逐欄改設定與既有 Grafana 密碼限制 | 第 3-2 節 |
| A 站 Post-script 手動貼入、IP 與 Token 一起更新 | 第 4-1 節 |
| 可選 NAS Shell 更新與真實同步後回報核對 | 第 4-2、4-3 節 |
| Targets、服務、面板、Email／Discord 與告警持續時間 | 第 5、6 節 |

**依 Word 的「安裝器 → NAS 設定」順序操作時**：若兩站尚未設定 SNMP，安裝器末段的真實指標驗證可能停止；不是已通過。完成 Word 7.4（本文件第 2 節）的兩站 SNMP 後，回監測 VM 重跑同一安裝命令，沿用保存設定再驗證。安裝前先完成 SNMP 則可減少一次中斷。

### Grafana Web UI 無法連入時

先確認瀏覽器使用的是監測 VM 可達的管理 IP 加 `:3000/`，不是 Tailscale 登入網址。在監測 VM 的 root 終端機唯讀檢查：

```bash
ip -br addr
systemctl is-active grafana-server
curl -fsS http://127.0.0.1:3000/api/health
ss -lntp | grep ':3000'
firewall-cmd --list-all
journalctl -u grafana-server -n 80 --no-pager
```

- 本機 health 失敗：先依服務狀態及日誌修正 Grafana，再檢查管理端網路。
- 本機正常、管理端無法連入：檢查 Host-Only／Gateway 路由、來源 CIDR 及 TCP 3000；防火牆應放行**管理電腦的來源網段或該電腦 IP/32**。
- 安裝器來源 CIDR 填成 VM 自己的 IP 時，依第 3-2 節用 `--edit-config` 修正並套用，不需重建全部 VM。
- 出現登入畫面但密碼不符：既有 Grafana 資料庫的密碼不會因重跑而重設；這與 Web UI 無法建立連線是不同問題。

第八章刪減的磁碟掃描、快照 Clone／Rollback、B 接管／回切、S3 解凍指令、權限與 RPO／RTO 量測，改收錄於 [災難復原演練完整流程](disaster-recovery-drill.md)。
