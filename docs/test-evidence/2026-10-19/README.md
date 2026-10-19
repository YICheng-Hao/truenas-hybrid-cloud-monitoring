# 測試證據索引

檔名中的 ci1／ci2／ci3／ci4 對應 [測試報告](../../installation-test-report.md) 的四輪固定提交。所有通知與憑證皆屬隔離測試資料。

- `ci*-rocky*-summary.json`：該 VM 整體結果；成功需同時具有 fresh_install、fault_and_recovery、reinstall_preserves_state、reboot=true。
- `ci*-rocky*-acceptance.json`：早期中斷時的逐項結果，最後會保留 FAILED／TypeError，不能因前面有通過就稱整輪成功。
- `ci*-rocky*-full-acceptance.json`：完整故障／恢復檢查 34 項。
- `ci*-rocky*-fault-recovery.log`、`reinstall.log`、`after-reboot.log`：對應階段原始日誌。
- `ci*-rocky*-image.json`：官方映像來源與 SHA256 校驗。
- `unit-local-final.log`：加入 S3 離線修正前的 31 項階段性結果；`unit-alert-fix.log` 才是 32 項的最新結果。
- `s3-down-before.log`／`s3-down-after.log`：相同五個情境在修正前出現兩個漏報、修正後通過。
- `promql-final-25.log`：包含現行容量與可用性情境的 25 項結果；`promql-local.json` 保留較早的 17 項紀錄。
- `snmp-protocol.log`：真正 SNMP Exporter 解析三種合成 NAS 狀態。
- `native-grafana-environment-error.log`：測試主機禁止 Unix socket 的原始證據；與後續真正 KVM VM 結果分開。

CI 線上完整 artifact 保存 14 天；此目錄保留精簡且可追溯的文字／JSON 證據，不保存測試碟、私鑰或真實秘密。
