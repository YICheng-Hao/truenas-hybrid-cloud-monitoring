# 企業級 NAS 與儲存安全管理方案 — 混合雲監控中心 (Prometheus & Grafana)

本儲存庫收納「企業級 NAS 與儲存安全管理方案建置」專案第七章之 Rocky Linux 9 監控中心程式碼與設定檔：
- `exporters/s3_realtime_exporter.py`：AWS S3 即時容量、物件數與月費估算 Exporter (`:9107`)
- `exporters/cloudsync_success_receiver.py`：TrueNAS Cloud Sync 成功回報接收器 (`:9108`)
- `systemd/`：各監控服務之 Systemd Unit 設定檔（含安全沙箱）
- `configs/`：Prometheus 四大採集任務設定檔與 Grafana 自動資料源配置
- `aws-iam/`：AWS IAM 唯讀監控最小權限 Policy JSON
- `grafana/`：TrueNAS 3-2-1 十面板極簡監控儀表板 JSON
- `install.sh`：監控中心一鍵部署腳本
