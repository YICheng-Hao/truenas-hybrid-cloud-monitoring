# 監測 VM 從零安裝測試紀錄

狀態：進行中，尚未宣告完整 VM 驗收通過。測試基準為 `f529e7f450c68f6d5e26a657ec0a8b48f95e2cd5`。

## 本輪可重現測試

| 測試 | 次數／案例 | 結果 |
|---|---:|---|
| 修正後元件測試第一輪 | 27 項 | 全數通過 |
| 補入執行中二進位重裝的元件測試第二輪 | 28 項 | 全數通過 |
| 相同 28 項對照 GitHub 基準版 | 28 項 | 3 個失敗、3 個錯誤，成功重現缺陷 |
| 加入 Grafana 評估驗證後的元件測試 | 31 項 | 全數通過；四輪共 114 次案例執行 |
| PromQL 測試 | 1 輪／17 個情境 | 全數通過 |
| 真正 SNMP Exporter 協定測試 | 2 輪 | 首輪驗收誤要求已移除的索引標籤；修正測試後，3 種狀態全部通過 |
| 主機原生 Grafana + Prometheus 評估 | 1 輪 | 未通過；測試主機禁止 Unix socket，Prometheus 外掛不能啟動 |
| Rocky 9.8 真實 QEMU VM 完整安裝 | 進行中 | 官方映像 SHA256 已核對，已啟動真實 Rocky 核心與 systemd |

以上是本輪有可重現證據的計數；環境準備與下載重試不算完整安裝成功。早先中斷的測試環境未保留完整輸出，不納入本表成功數。

## 已修正問題

1. 安裝器直接覆寫執行中的 SNMP Exporter／Prometheus，重跑會出現 `ETXTBSY`。改成相同目錄暫存、fsync、設定權限後原子替換 inode，舊程序繼續執行。
2. Receiver 解析無效 UTF-8 或不合法表單時拋出例外並斷線。改成回應 HTTP 400，且不寫入成功紀錄。
3. S3 CLI 雖然回傳 0，輸出為空、缺少摘要、解析失敗或負值時仍可能顯示健康。改為必須取得非負物件數與總位元組數；失敗時健康值為 0、容量與估算值為 NaN。空桶的合法 0／0 摘要仍視為正常。
4. 安裝驗證原本只檢查 Grafana HTTP 存活。補入資料源健康檢查及九條規則實際評估，避免將「檔案載入成功」寫成「告警可用」。

## 驗收邊界

完整 VM 使用真實 Rocky Linux、systemd、SELinux、SNMP Exporter、Prometheus、Grafana、AWS CLI 及兩支自研服務。外部 TrueNAS SNMP、S3 API、SMTP 與 Discord 使用隔離測試端點，所有憑證均為無效測試值，不傳送真實通知。Tailscale 登入與 Tailnet 身分使用測試替身，不能據此宣稱真實跨站網路與使用者帳號已通過驗收。

容量面板 `grafana/TrueNAS_Hybrid_Cloud.json` 保留原內容，SHA256 為 `af19259d3b2c6da6e4a862837bf66e6cad8332abf4ad2ab6d80b4bfb07afbdc2`。

## 重跑元件測試

```bash
python3 -m unittest discover -s tests -p 'test_*.py' -v
```

完整 VM、故障通知、恢復通知、重跑與重新開機結果將在完成後追加；目前不能將本報告引用為「從零建置全部通過」。

## 自動整合測試

已加入 `.github/workflows/monitoring-vm-test.yml` 與 `tests/integration/`。執行器會建立真實 Rocky 9／10 VM，測正式安裝器、合成故障與雙管道通知、重跑及重新開機。工作流程是否通過應以實際執行結果與 artifact 為準；加入工作流程本身不算通過。
