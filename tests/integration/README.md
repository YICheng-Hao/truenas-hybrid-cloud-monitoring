# 隔離 VM 整合測試

這個目錄是開發測試用途，正式監測 VM 請使用 `docs/monitoring-vm-from-zero.md`。測試會建立可拋棄的 Rocky VM，使用假 NAS SNMP、假 S3、假 SMTP／Discord 端點；不需要也不能填真實帳號。Tailscale RPM 與 daemon 會安裝，但 Tailnet 身分及狀態由替身提供，未驗證真實跨站連線。

GitHub Actions 的 **Monitoring VM integration** 分別建立 Rocky 9、10 VM，執行正式安裝器，然後驗收：

- 五個正式監控服務、SELinux Enforcing、九條規則、十個面板、五個採集目標。
- A／B 合成容量精確為 2,000,000,000,000 bytes；不代表使用者實際池容量。
- 真正 AWS CLI 經本地 S3 XML 端點取得兩個物件與 3072 bytes。
- Receiver 拒絕錯誤 Token；正式產生的 Post-script 能寫入並採集成功回報。
- 所有 Grafana 規則完成實際評估，並且沒有評估錯誤；資料源查詢真正取得資料框架。
- 原生 ONLINE 但成員 OFFLINE：面板狀態 3、實際成員告警 Firing、SMTP 與 Discord 收到該告警；恢復後兩管道收到解除通知。
- 原生 DEGRADED：面板狀態 1、降級規則 Firing、雙管道收訊及恢復。
- 重跑安裝器、重新開機：Token／成功回報檔雜湊保留，服務與規則仍正常。

通知驗收要求內文包含真正的告警名稱，不能用含有原規則說明文字的 `DatasourceError` 冒充成功。

在可使用 QEMU 的 Ubuntu 開發主機，以一般帳號執行：

```bash
sudo apt-get update
sudo apt-get install -y qemu-system-x86 qemu-utils cloud-image-utils openssh-client
sudo chmod a+rw /dev/kvm  # 若主機提供 KVM
python3 tests/integration/run-vm-test.py --major 9
```

請使用全新工作目錄。執行器使用 TCP 18080 與 2222，將下載大型映像並建立 40 GiB 稀疏測試碟；可用 KVM 時使用 KVM，否則使用較慢的 TCG。測試證據在 `_lab/`。不要提交該目錄，內含測試用私鑰、磁碟及假憑證。

CI 只上傳文字日誌、驗收 JSON 與合成通知紀錄，排除磁碟、私鑰與憑證。故障切換修改的是合成 SNMP 回應，沒有實際拔除使用者硬碟，也不驗證 Resilver 或真實 S3／Gmail／Discord 服務。
