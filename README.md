# TrueNAS 混合雲備份與監控

整合 TrueNAS A 正式資料與本地快照、B 站 PULL 複寫、AWS S3 備份，搭配 Prometheus、Grafana 及 Email／Discord 告警，建立從發現異常到資料取回的處理流程。

**本儲存庫已公開，瀏覽、下載及 git clone 不需要 GitHub 帳號或 Token。** AWS、Tailscale 與監控服務仍使用自己的憑證。

文件依目前技術文件的章節與環境整理。Word 保留重點流程與圖片；GitHub 保存完整欄位、命令、排錯與驗收方式。範例位址須和自己的環境核對。

## 文件怎麼看

| 要做的事 | 主要文件 |
|---|---|
| 第七章：從零部署、填安裝器、更新 NAS Post-script、驗收通知 | [完整建置指南](docs/monitoring-vm-from-zero.md) |
| 第八章：四項災難情境、詳細操作、收尾及補圖 | [災難復原演練 SOP](docs/disaster-recovery-drill.md) |
| 看懂 Grafana 或查採集問題 | 指南的 [面板說明](docs/monitoring-vm-from-zero.md#panels) 與 [來源排查](docs/monitoring-vm-from-zero.md#diagnostics) |
| 核對第六章備份 IAM 政策 | [完整 JSON](docs/monitoring-vm-from-zero.md#backup-iam)；監控 ListBucket 政策另見指南第 3 節 |
| 查歷史測試及其限制 | [合併測試報告](docs/installation-test-report.md)、[原始證據](docs/test-evidence/2026-10-19/README.md) |
| 開發者執行隔離 VM 測試 | [整合測試說明](tests/integration/README.md) |

NAS 安裝、儲存池、部門帳號、ACL 與原始備份沿用 Word 第五、六章；演練文件補上各情境額外需要的設定。監測 VM 安裝器不會自動建好所有 NAS 設定。

<a id="environment"></a>
## 先確認地端與雲端環境

| 設備 | 本專案位址／資料 | 用途 |
|---|---|---|
| TrueNAS A | LAN `192.168.1.100/24`；Tailscale `100.114.236.88`；`mainpool/data` | 正式 SMB、本地快照、S3 PUSH＋COPY |
| W11_A | `192.168.1.50/24` | 員工存取及復原驗證 |
| Gateway_VM_HQ | 內網 `192.168.1.1`；外網 `192.168.23.156` | A 預設閘道、NAT 與轉發 |
| TrueNAS B | LAN `10.10.10.100/24`；Tailscale `100.113.107.95`；`backuppool/backup_snapshot` | PULL 備份，平時唯讀 |
| W11_B | `10.10.10.50/24` | IT 在 B 站取回急用資料 |
| Gateway_VM_B | 內網 `10.10.10.1`；外網 `192.168.23.157` | B 預設閘道、NAT 與轉發 |
| Rocky Linux 監測 VM | 管理 `192.168.23.159`；Tailscale `100.82.30.20` | SNMP、S3／Cloud Sync 採集、Grafana 與告警 |
| AWS S3 | `ap-east-2`；`truenas-backup-myhome-2026` | COPY 備份及生命週期封存 |

A、B NAS 與各站 Windows 使用各自 Host-Only 網路；Gateway 外側介面採橋接，由 Linux NAT／路由提供上網，不是 VMware NAT。不要假設 Gateway 已加入 Tailscale；原跨站複寫與監控使用 NAS／監測 VM 的 Tailscale。監測 VM 的管理網卡、閘道與 DNS 依實際配置核對。

目前 VM 共用一台實體 VMware 主機，可驗證邏輯分站與 NAS 故障流程，無法證明整台實體主機、電力或網路故障時仍可提供異地服務。

## 第七章：從零建立監測 VM

在全新的 Rocky Linux 9／10 x86_64 VM，依 [完整指南](docs/monitoring-vm-from-zero.md) 操作：

1. 下載專案，先執行 `scripts/setup-monitoring-vm.py --tailscale-only`，完成同一 Tailnet 登入與 IP 核對。已登入而不再顯示登入網址屬正常。
2. 確認 A、B SNMP 及 `extend zfs /usr/sbin/zpool status -P` 已設定。
3. 執行 `scripts/setup-monitoring-vm.py`，逐欄填來源 CIDR、NAS IP、監控 IAM 金鑰、通知及至少 **8 字元**的 Grafana 密碼。
4. 到 **A 原 Cloud Sync 任務的 Post-script**，貼入新 VM 產生的完整 `/root/truenas-cloudsync-postscript.sh`。IP、`:9108/success` 與 Token 都要正確，不是只改網址。
5. 執行真實 Cloud Sync，核對本次回報、Targets、規則及 Email／Discord 收訊，才完成驗收。

安裝器部署四個 Prometheus Job、五個 Target、十個面板與九條告警。正常運作的舊 VM 不必重建；重跑與既有 Grafana 密碼限制見指南。NAS 上傳／還原金鑰與監控 ListBucket 金鑰用途不同。

## 第八章：四個災難情境

| 章節 | 流程 |
|---|---|
| [8.1](docs/disaster-recovery-drill.md#drill-81) | 雙碟故障自動告警與 RAID-Z2 復原：告警後逐顆 Replace／resilver |
| [8.2](docs/disaster-recovery-drill.md#drill-82) | A 離線與異地備份緊急取回：IT 用 W11_B 取回、交付，A 恢復後交回文件及恢復原複寫 |
| [8.3](docs/disaster-recovery-drill.md#drill-83) | 使用者誤刪與本地快照復原：只取回指定文件，保留快照後新增資料 |
| [8.4](docs/disaster-recovery-drill.md#drill-84) | A、B 不可用與 S3 復原：新建地端 NAS，PULL＋COPY 下載 Standard 文件並驗證 |

8.2 採管理員協助取回，不開放全體員工跨站連 B，也不是自動容錯切換。勒索應變及封存解凍列為延伸；未附現場證據的結果維持待驗證。

## 程式與設定入口

- `scripts/setup-monitoring-vm.py`：新監測 VM 安裝與唯讀驗證；重跑保留 Receiver Token 與回報檔。
- `scripts/configure-truenas-snmp-stable.py`：選用，在 NAS 建立 SNMP 成員來源。
- `scripts/prepare-cloudsync-handoff.py`：選用，準備 NAS Post-script 交接及唯讀回報檢查；仍須在 NAS 套用並執行真實同步。
- `configs/snmp-zfs-stable.yml`、`configs/grafana-alerts-stable.yaml`、`configs/grafana-notification-template.tmpl`：來源、告警與通知模板。
- `grafana/TrueNAS_Hybrid_Cloud.json`：十面板；hrStorage 根掛載點不代表整池子資料集與快照總占用。

歷史 `deploy-zfs-capacity.py`、`deploy-zfs-members.py`、`configure-truenas-snmp.py`、`snmp-zfs-modules.yml` 保留為排錯工具／設定，不是從零流程的追加步驟。前次文件彙整保留程式與設定；本輪另同步使用者提供的 Grafana 版面，安裝器、Exporter、Prometheus 與告警規則維持原內容。

## 測試紀錄與資料保護

固定部署版本：SNMP Exporter 0.26.0、Prometheus 2.54.1、Grafana 13.2.4。歷史測試提交、失敗原因及通過範圍見 [合併測試報告](docs/installation-test-report.md)。外部 NAS、S3、通知及 Tailnet 身分使用隔離替身，不代替現場磁碟重建、Windows SMB、AWS 或跨站驗收。本次文件整理沒有重新執行這些災難測試。

元件回歸測試指令：

```bash
python3 -m unittest discover -s tests -p 'test_*.py' -v
```

不要上傳 `/root/monitoring-setup.json`、AWS 金鑰、NAS 加密金鑰、Gmail App Password、Discord Webhook 或 Receiver Token。COPY 與未授予 DeleteObject 不能防止同名物件覆寫；S3 檔案副本不是完整 ZFS 快照或 NAS 設定備份。

## 未來延伸

- **集中帳號與權限：**導入 Active Directory，簡化部門存取與復原後身分對應。
- **備份安全：**評估版本保留、防竄改及管理權限分離。
- **正式網路設備：**由路由器與防火牆承接 Gateway VM 的 NAT、路由與存取控管。
- **實體異地與應變：**部署獨立設備，加入隔離的勒索應變演練，持續量測資料落差與恢復時間。

## 文件合併紀錄

原雙碟獨立教學併入災難 SOP 8.1；面板與監控排查併入建置指南；輸入流程及 Cloud Sync 交接測試併入安裝測試報告。移除五份重複入口，保留原建置指南網址、原始測試證據及開發者測試說明。舊版本可由 Git 歷史查閱。
