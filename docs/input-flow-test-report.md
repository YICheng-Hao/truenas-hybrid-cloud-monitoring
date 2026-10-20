# 安裝輸入流程修正驗證

日期：2026-10-20（臺北時間）。本次針對 Tailscale 登入順序、欄位說明、輸入防呆及至少 8 碼的 Grafana 密碼進行修改。

## 本次實際測試

| 輪次 | 指令／範圍 | 結果 |
|---|---|---|
| 1 | `python3 -m py_compile scripts/setup-monitoring-vm.py`；原有 Python 回歸測試 | 語法檢查通過；32 項全部通過 |
| 2 | `python3 -m unittest discover -s tests -p 'test_*.py' -v`；包含新增輸入流程測試 | 43 項全部通過（原有 32＋新增 11） |

新增案例涵蓋：8 碼接受／7 碼拒絕、管理來源必須含明確 CIDR、錯誤 Task ID 與來源 IP 當場重填、空白秘密重填、15 欄全新輸入、修正截圖中的錯誤已存來源值並保留秘密及 600 權限、已登入不再次登入、未登入先執行 `tailscale up` 再讀取 IP、Rocky 10 軟體源、`--tailscale-only` 不詢問秘密，以及節點未核准時停止。

## 修正的實際問題

- 舊流程先詢問所有資料才開始 Tailscale；現在有獨立登入步驟，正式安裝亦先確認登入。
- 單一 IP 原先會被 IPv4Network 隱含視為 /32；現在要求明確輸入網段或管理電腦 IP/32，避免誤填 VM 自己的 IP。
- 舊版格式錯誤直到全部輸入後才發現；現在留在同一欄重填。另提供 `--edit-config` 修正已保存資料。
- 教學明確要求更新 TrueNAS A 的 Post-script，指出截圖回報網址缺少 `:9108/success`，說明 Token 由檔案產生、`${CLOUD_SYNC_ID}` 原樣保留。
- 文件先前同時存在「完整 VM 已測」與「尚未測」的舊段落；現改為指向各自版本的測試報告。

## 驗收邊界

本次 Tailscale 互動分支用 mock 驗證順序，沒有登入使用者的 Tailnet；沒有在這個環境重新建立全新 Rocky VM，也未使用真實 IAM、Gmail、Discord 或 TrueNAS 任務測試。歷史四輪八台 VM 結果保留於 [先前測試報告](installation-test-report.md)，不算作本次完整 VM 重測。

本次提交只調整安裝器、教學與新增測試／報告；容量面板、PromQL、Exporter 與通知設定檔保持原版本。現場仍須依 [建置教學](monitoring-vm-from-zero.md) 驗收真實 S3 API、A／B SNMP、Cloud Sync 任務回報與通知收訊。
