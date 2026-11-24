# v0.1 运行验收记录

2026-11-24，冻结代码/CI 提交 [a2fa24a](https://github.com/Qesire/Creeperman/commit/a2fa24a4d15a2666313b449e4971029175facb1d)。[GitHub Actions run 45389386120](https://github.com/Qesire/Creeperman/actions/runs/45389386120) 已完成，offline 与 temporal 两个 job 均 success；读取实际 job 日志。

| 验收 | 实际日志 |
|---|---|
| Python 3.11 / pytest tests/test_v1.py | 9 passed in 0.19s |
| CLI census / discovery-job / run-local / collect / plan | 整个 CLI 步骤 success |
| Python 3.11 / temporalio 1.36.1 / RUN_TEMPORAL_SMOKE=1 pytest tests/test_temporal.py | 1 passed in 1.04s，真实 Temporal 测试服务、Worker 和 Workflow |
| 安装依赖 | pytest 9.2.0、boto3 1.44.10、botocore 1.44.10、temporalio 1.36.1（Temporal job） |

合成 fixture 的实际 census：8 个全局唯一 hostname、39 个理论缺失 hostname-year、4 个带年份提示的缺口；全缺口条件 EED 上界 30.9375，带年份提示上界 2.5284。qualified_new_eed = null。CLI 本地发现和导入：1 个 manifest、6 个唯一发现 hostname、8 条结果（含拒绝记录）、0 条潜在捕获见证。固定样例只用于运行与集合语义的验收。

本轮没有取得完整竞赛基线、模型原件、candidate_pool 和新来源原始文件。因此真实残余容量、生产级差集吞吐、S3 实际存取、跨地区 Temporal 部署、真实 IA 查询与证据判定均未验收。在线代码只通过构造响应、模拟请求及检查点测试；没有发起真实档案请求。下一步按 [运行手册](IMPLEMENTATION_V1.md) 在持有任务包的机器执行一次联合 census，将真实 report.json 作为后续准入和投入决策的输入。
