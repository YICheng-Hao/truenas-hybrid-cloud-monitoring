# 監測 VM 從零建置測試報告

日期：2026-10-20（臺北時間；GitHub 日誌為 2026-10-19 UTC）。

歷史狀態（下述提交）：完整 VM 驗收通過。測試提交為 `a1e5093bfcdac1f81c5876c514c710270dd99a67`；最新一輪 Rocky 9.8 與 Rocky 10.2 的建置、故障／恢復、重跑與重開機均成功。外部服務為隔離替身，範圍見下方。

本文彙整歷史 VM、輸入流程與 Cloud Sync 交接測試，各節的提交、日期與替身範圍分開記錄；不表示本次文件整理重新執行這些測試。

正式流程：[從零建置與複製貼上命令](monitoring-vm-from-zero.md)。

## 完整 VM 測試輪數

每輪分別建立一台全新 Rocky 9 與 Rocky 10 VM，使用固定提交的正式安裝器。不是只驗證 YAML，也不是在同一台已安裝好的 VM 上假裝從零開始。

| 輪次 | 提交 | Rocky 9 | Rocky 10 | 原因／結果 |
|---|---|---|---|---|
| [第一輪](https://github.com/YICheng-Hao/truenas-hybrid-cloud-monitoring/actions/runs/39295492867) | `c948750` | 完整流程失敗 | 完整流程失敗 | 兩版正式安裝及前 22 項驗收通過；測試程式保存路徑時發生 TypeError，後續步驟未執行 |
| [第二輪](https://github.com/YICheng-Hao/truenas-hybrid-cloud-monitoring/actions/runs/39295989943) | `1e3cea3` | 完整流程失敗 | 完整流程失敗 | 補入 CI 日誌與 PromQL；兩版再次重現相同測試程式錯誤 |
| [第三輪](https://github.com/YICheng-Hao/truenas-hybrid-cloud-monitoring/actions/runs/39296984465) | `a82802d` | 完整通過 | 完整通過 | 故障與恢復、重跑安裝、重新開機均通過 |
| [第四輪](https://github.com/YICheng-Hao/truenas-hybrid-cloud-monitoring/actions/runs/39299129639) | `a1e5093` | 完整通過 | 完整通過 | 最終 S3 漏報修正版本，兩版完整驗收再次通過 |

共 4 輪、8 台全新 VM：八台的正式安裝全部通過；第 3、4 輪共四台完成全部驗收，其餘四台在已定位的測試程式錯誤處中斷，不列完整通過。每台完整通過的 VM 完成 34 項故障／恢復檢查、重跑後 18 項、重開機後再 18 項，並核對兩個狀態檔雜湊。合計實際完成四次重裝與四次重新開機驗證。

## 驗收內容

- 真正 Rocky Linux、systemd、SELinux Enforcing，以及五個正式監控服務。
- SNMP Exporter 0.26.0、Prometheus 2.54.1、Grafana 13.2.4、真正 AWS CLI v2 與兩支 Python 服務。
- 九條規則、十個面板、雙通知聯絡點、五個採集 Target 全部 UP；Grafana 資料源真正回傳資料框架，規則已實際評估且沒有錯誤。
- A／B 合成根掛載點容量各為 2,000,000,000,000 bytes；實際資料流經 SNMP、Exporter、Prometheus。這是測試資料，不是將正式面板容量硬編碼為 2 TB。
- AWS CLI 向隔離 S3 XML 端點列舉兩個物件、3072 bytes；Receiver 拒絕錯誤 Token，產生的 Post-script 可以成功回報並被採集。
- 原生 ONLINE、成員 OFFLINE：面板值為 3，成員規則 Firing，Email／Discord 收到該規則及恢復通知。
- 原生 DEGRADED：面板值為 1，降級規則 Firing，兩管道收到該規則及恢復通知。
- 重跑正式安裝器後服務正常；Receiver Token 與成功回報 JSON 內容雜湊保持一致。
- 真正重新開機後，五服務、九規則、十面板、指標及資料源再次通過檢查；狀態檔保留。

通知驗收比對真正的告警名稱與觸發／解除標題；不能把帶有原規則說明文字的 `DatasourceError` 當作磁碟故障通知。

## 發現的問題與修正

| 問題 | 修正與驗證 |
|---|---|
| 重跑安裝直接覆寫執行中的二進位檔，出現 ETXTBSY | 同目錄暫存、fsync、設定權限後原子替換 inode；元件測試保留舊程序持續執行，完整 VM 亦實際重跑 |
| Receiver 遇無效 UTF-8／表單時斷線 | 改回 HTTP 400，不寫入成功紀錄；有效回報及錯誤 Token 另行驗證 |
| S3 CLI 空白、缺摘要、解析失敗或負值時仍可能顯示健康 | 必須取得非負物件數與大小才設健康 1；失敗時健康 0、容量及估算為 NaN；合法空桶 0／0 仍正常 |
| Grafana 網頁可開、規則已載入，卻可能無法實際評估 | 安裝最後新增資料源健康檢查與九條規則實際評估；錯誤時停止，不宣告通過 |
| S3 Exporter 整支停止、健康指標消失時，舊規則只剩正常 NAS 序列，造成漏報 | 新增依 job／instance 配對的 0 值備援。真正 promtool 重現兩個漏報案例，修正後五種可用性情境全部通過；穩定版與整合版告警檔同步 |
| 測試程式以 Path 加字串保存故障快照，讓後續驗收中斷 | 改成先組合檔名再接路徑；保留第一、二輪失敗紀錄，第三輪完整通過 |
| 舊故障文件混入歷史容量模組與增量更新步驟 | 統一 README、從零建置及故障測試文件，現行容量沿用 hrStorage；歷史工具不屬於從零流程 |

S3 漏報修正使用 `or on (job, instance) (0 * up{job="aws_s3"})`：有有效 API 健康指標就沿用，缺失時回傳異常 0。沒有更改正式評估週期與 Pending 時間。

## 元件與查詢測試

| 測試 | 紀錄 |
|---|---|
| 本機 Python 回歸測試 | 五輪，案例數依序 27、28、28、31、32；其中對 GitHub 舊版的 28 項對照測試重現 3 失敗、3 錯誤；最後 32 項全通過 |
| GitHub Python 回歸測試 | 第 1～3 輪各 31 項，第 4 輪 32 項，均通過 |
| 最終 PromQL | 25 個情境全部通過，包含原生健康、成員、現行容量、S3 可用性；其中 1 項為保留的歷史容量回歸 |
| 現行容量新增情境 | 不同 role 的 A／B 正確配對、忽略子資料集、根掛載點缺失時不代入子資料集 |
| 真正 SNMP Exporter 協定測試 | 兩輪；第一輪驗收誤要求已移除的索引標籤，修正測試後三種狀態均通過 |

元件測試指令：

```bash
python3 -m unittest discover -s tests -p 'test_*.py' -v
```

## 環境問題與驗收邊界

原生測試主機禁止 Unix socket，導致 Grafana Prometheus 外掛無法初始化；此為測試環境限制，後改用真正 KVM VM 驗證，不能把它誤認為使用者規則錯誤。本機 TCG VM 首次前置作業曾遭代理 HTTP 403，重試後安裝 Tailscale、進入正式安裝並安裝 Grafana；因軟體模擬耗時，收集紀錄後關閉，沒有將它算為完整通過。

正式 CI 使用真實 Rocky VM、RPM、systemd、SELinux 及正式監控程式。外部 TrueNAS SNMP、S3 API、SMTP／Discord 使用隔離替身；Tailscale 安裝真實 RPM，但身分／狀態回覆由替身提供，沒有驗證真實登入與跨站 Tailnet。輸入為預先準備的假憑證 JSON，不測使用者的 GitHub 互動登入、AWS IAM、Gmail 或 Discord 帳號有效性。測試 VM 停用 kdump，避免首次開機巡檢與安裝競爭資源。

這些測試不代替實際 TrueNAS 硬碟故障、Resilver、Windows SMB 可用性、ZFS 複寫或真實 Cloud Sync 任務。現場仍依教學執行一次真實任務與外部通知收訊驗收。

最新一輪兩份下載 artifact 已比對 GitHub 提供的 SHA256；逐台結果見 [VM 測試清單](test-evidence/2026-10-19/vm-test-ledger.json)。

容量面板檔保持原內容，SHA256：`af19259d3b2c6da6e4a862837bf66e6cad8332abf4ad2ab6d80b4bfb07afbdc2`。

長期證據：[docs/test-evidence/2026-10-19](test-evidence/2026-10-19/)。CI 完整 artifact 另保留 14 天。早先中斷環境的未完整保存輸出不計入本表成功數。

<a id="input-flow"></a>
## 安裝輸入流程修正驗證

日期：2026-10-20（臺北時間）。本次針對 Tailscale 登入順序、欄位說明、輸入防呆及至少 8 碼的 Grafana 密碼進行修改。

### 本次實際測試

| 輪次 | 指令／範圍 | 結果 |
|---|---|---|
| 1 | `python3 -m py_compile scripts/setup-monitoring-vm.py`；原有 Python 回歸測試 | 語法檢查通過；32 項全部通過 |
| 2 | `python3 -m unittest discover -s tests -p 'test_*.py' -v`；包含新增輸入流程測試 | 43 項全部通過（原有 32＋新增 11） |

新增案例涵蓋：8 碼接受／7 碼拒絕、管理來源必須含明確 CIDR、錯誤 Task ID 與來源 IP 當場重填、空白秘密重填、15 欄全新輸入、修正截圖中的錯誤已存來源值並保留秘密及 600 權限、已登入不再次登入、未登入先執行 `tailscale up` 再讀取 IP、Rocky 10 軟體源、`--tailscale-only` 不詢問秘密，以及節點未核准時停止。

### 修正的實際問題

- 舊流程先詢問所有資料才開始 Tailscale；現在有獨立登入步驟，正式安裝亦先確認登入。
- 單一 IP 原先會被 IPv4Network 隱含視為 /32；現在要求明確輸入網段或管理電腦 IP/32，避免誤填 VM 自己的 IP。
- 舊版格式錯誤直到全部輸入後才發現；現在留在同一欄重填。另提供 `--edit-config` 修正已保存資料。
- 教學明確要求更新 TrueNAS A 的 Post-script，指出截圖回報網址缺少 `:9108/success`，說明 Token 由檔案產生、`${CLOUD_SYNC_ID}` 原樣保留。
- 文件先前同時存在「完整 VM 已測」與「尚未測」的舊段落；現改為指向各自版本的測試報告。

### 驗收邊界

本次 Tailscale 互動分支用 mock 驗證順序，沒有登入使用者的 Tailnet；沒有在這個環境重新建立全新 Rocky VM，也未使用真實 IAM、Gmail、Discord 或 TrueNAS 任務測試。歷史四輪八台 VM 結果保留於 [上方完整 VM 測試](#完整-vm-測試輪數)，不算作本次完整 VM 重測。

當時的輸入流程修正提交調整安裝器、教學與新增測試／報告；容量面板、PromQL、Exporter 與通知設定檔保持原版本。現場仍須依 [建置教學](monitoring-vm-from-zero.md) 驗收真實 S3 API、A／B SNMP、Cloud Sync 任務回報與通知收訊。

<a id="cloudsync-handoff"></a>
## Cloud Sync 設定交接修正與測試

日期：2026-10-20（臺北時間）。

### 現場問題與原因

使用者已能開啟 Grafana，A／B SNMP 與 S3 API 正常，但 Cloud Sync 顯示「尚無紀錄」且成功回報超時告警。NAS 截圖仍指向舊監測 VM，網址缺少 `:9108/success`。監測 VM 重建後，NAS 中的回報位址與 Token 不會自動更新；只產生腳本不等於已套用 NAS 設定。Token 是否相同無法由面板證明，必須以新 VM 的 Receiver 設定為準。

### 修正

- 新增 `scripts/prepare-cloudsync-handoff.py`，讀取監測 VM 現有 Receiver 設定與 Task ID，產生含真實值的 TrueNAS Shell 更新命令，不需手填秘密或遠端 SSH 憑證。
- 在 NAS 本機按 Task ID／PUSH／bucket 核對，先備份舊 Post-script，只透過 `cloudsync.update` 更新 `post_script`，再讀回比對；自訂命令不自動覆寫。
- 新增唯讀 `--check`，分別檢查 Receiver 與 Prometheus 的指定 Task ID 回報，顯示收到時間供對照。
- 教學第 4 節分開標示監測 VM 與 TrueNAS A 各自要執行的命令，以及真實任務驗收。工具產生檔案不等於已修改 NAS；更新設定也不等於已收到真實成功回報。

### 本次實際測試

本次一輪 Python 回歸測試：`python3 -m unittest discover -s tests -p 'test_*.py' -v`，50 項全部通過（先前 43 項＋新增 7 項）。新增工具另經 `py_compile` 檢查。

新增案例驗證：舊 curl 回報替換、600 權限備份、只更新 post_script、不改 Pre-script／排程；重跑不重寫；含自訂命令停止；bucket 不符停止；使用現有 Token 與完整網址；執行實際產生的 NAS 更新程式並驗證 API 更新／讀回流程；以真實 `sh`／`curl` 執行產生的 Post-script，向隔離的真實 Receiver HTTP 程序發送測試 Task ID，確認寫入測試狀態。

NAS API 測試使用 mock，不是實際 TrueNAS。HTTP 測試用假 Token／Task ID 與暫存檔，不會發送至使用者 Receiver，也不會修改使用者成功紀錄。本次沒有在使用者 NAS 執行更新、沒有啟動其同步任務，也沒有重新建立 Rocky VM。現場需依第 4 節套用設定、Run Now、對照成功回報時間後才能認定完成。

正式操作：[從零建置教學第 4 節](monitoring-vm-from-zero.md#4-必做更新-truenas-a-的-cloud-sync-post-script)。
