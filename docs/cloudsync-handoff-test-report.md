# Cloud Sync 設定交接修正與測試

日期：2026-10-20（臺北時間）。

## 現場問題與原因

使用者已能開啟 Grafana，A／B SNMP 與 S3 API 正常，但 Cloud Sync 顯示「尚無紀錄」且成功回報超時告警。NAS 截圖仍指向舊監測 VM，網址缺少 `:9108/success`。監測 VM 重建後，NAS 中的回報位址與 Token 不會自動更新；只產生腳本不等於已套用 NAS 設定。Token 是否相同無法由面板證明，必須以新 VM 的 Receiver 設定為準。

## 修正

- 新增 `scripts/prepare-cloudsync-handoff.py`，讀取監測 VM 現有 Receiver 設定與 Task ID，產生含真實值的 TrueNAS Shell 更新命令，不需手填秘密或遠端 SSH 憑證。
- 在 NAS 本機按 Task ID／PUSH／bucket 核對，先備份舊 Post-script，只透過 `cloudsync.update` 更新 `post_script`，再讀回比對；自訂命令不自動覆寫。
- 新增唯讀 `--check`，分別檢查 Receiver 與 Prometheus 的指定 Task ID 回報，顯示收到時間供對照。
- 教學第 4 節分開標示監測 VM 與 TrueNAS A 各自要執行的命令，以及真實任務驗收。工具產生檔案不等於已修改 NAS；更新設定也不等於已收到真實成功回報。

## 本次實際測試

本次一輪 Python 回歸測試：`python3 -m unittest discover -s tests -p 'test_*.py' -v`，50 項全部通過（先前 43 項＋新增 7 項）。新增工具另經 `py_compile` 檢查。

新增案例驗證：舊 curl 回報替換、600 權限備份、只更新 post_script、不改 Pre-script／排程；重跑不重寫；含自訂命令停止；bucket 不符停止；使用現有 Token 與完整網址；執行實際產生的 NAS 更新程式並驗證 API 更新／讀回流程；以真實 `sh`／`curl` 執行產生的 Post-script，向隔離的真實 Receiver HTTP 程序發送測試 Task ID，確認寫入測試狀態。

NAS API 測試使用 mock，不是實際 TrueNAS。HTTP 測試用假 Token／Task ID 與暫存檔，不會發送至使用者 Receiver，也不會修改使用者成功紀錄。本次沒有在使用者 NAS 執行更新、沒有啟動其同步任務，也沒有重新建立 Rocky VM。現場需依第 4 節套用設定、Run Now、對照成功回報時間後才能認定完成。

正式操作：[從零建置教學第 4 節](monitoring-vm-from-zero.md#4-必做更新-truenas-a-的-cloud-sync-post-script)。
