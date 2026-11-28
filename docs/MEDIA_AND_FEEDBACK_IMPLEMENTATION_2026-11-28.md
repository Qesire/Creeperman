# 原件读取、映射提取与 RSIforme 反馈实现

2026-11-28，后续于 Creeperman `d5613fb` / RSIforme `92a86fb`。本轮实际取得 PC Press 1996 光盘成员，完成原 URL 映射、离线提取和现有任务账本接入；同时补齐事前声明到 RSIforme 的自动导出。公开汇总为 [media_feedback_20261128.json](../audit/media_feedback_20261128.json)，原件字节、候选和运行数据库只保留在私有执行目录。

## 1. 本轮推进了什么

| 部分 | 当前实现 | 实际验收 |
|---|---|---|
| 取得容器内所需原件 | [media_reader.py](../src/creeperman/media_reader.py)，原生 ISO9660 路径、精确 HTTP Range、SQLite 分块缓存 | 实际读取 2 份 INDEX.LIS 与对应 2 份 HTML；禁止网络后逐字节复核一致 |
| 恢复原 URL | [media_mapping.py](../src/creeperman/media_mapping.py)，PC Press LIS、Archive95 原 JSON 映射、Teleport 属性 | PC Press 格式由真实原件核定；其他格式仅已核源码与合同测试 |
| 复用现有任务系统 | `discovery-job → run-local → collect` | 真实 53 条记录入账；全部保留媒体 provenance 与提取版本 |
| 生产回执进入研究循环 | [discovery_epoch.py](../src/creeperman/discovery_epoch.py) | 完成声明、实际回执、审核逐项记录、冻结 B/A 投影、RSI prepare/evaluate；跨仓执行用合成材料验收 |
| 降低前沿排序开销 | [discovery_rank.py](../src/creeperman/discovery_rank.py) | 真实 `Frontier.choose` 的固定队列对照，选择与特征完全一致 |

本会话没有竞赛真实六年基线与完整累计 A。原件提取不是年度资格审核，53 条不是 53 个网站。当前新增资格与 EED 均未评估，既有累计仍为 **155 个主机年度、100.9875 EED**，组织者尚未复核。

## 2. 从国际项目学习到的具体实现

[Archive95 的固定版本原始导入器](https://github.com/WumboSpasm/archive95-server/blob/9f6789d6c78db6d6cb2dee4d8c05ce67cc4f64ff/src/build.js) 将 `url/path` 显式映射到原始文件，并根据下载工具恢复重写链接。其 Packard Bell 分支把 `tppabs` 还原到紧邻的前一个属性，`error` 表示下载失败。Creeperman 实现这些可核对的绑定，不复制展示层的 `www` 合并或猜测修复。

PC Press 的实际 LIS 格式由这次原始成员确认：每一行是下载器保存路径与原始绝对 URL，编号文件与 LIS 位于同一 ISO 目录。下载器 namespace 不当作 ISO 路径，也不加入候选主机。网页开头还保有下载器插入的 META 日期；Archive95 的展示代码会移除它，而本项目保留原字节和日期断言以供裁决。

ISO 结构使用 [pycdlib](https://clalancette.github.io/pycdlib/api/pycdlib.html) 的卷描述符与目录记录解析器。本轮先尝试其通用 `open_fp`，实际发现它会预加载完整目录树；随后改为只遍历所选成员的祖先目录。格式校验仍交给成熟解析器，选择性 I/O 由本项目执行。

此前已接入的来源优先与路径反馈继续复用，文献与种子依据见[起点分析](DISCOVERY_SEEDS_2026-11-28.md)及[发现工作流](SOURCE_DISCOVERY_CRAWLER_WORKFLOW.md)。本轮没有宣称复现 ACHE 全部分类器，也没有从合成评分推断线上收益。

## 3. 真实原件执行与口径

精确容器为 [PC_PRESS.ISO](https://archive.org/download/pc-press-internet-cd/PC_PRESS.ISO)，提供方给出的大小是 522,053,632 bytes。本轮未完整下载、未核验整盘 SHA-1；局部读取由相同最终对象 URI、强 ETag、精确 Range 及每块 SHA-256 绑定。

| 指标 | 实际结果 |
|---|---:|
| HTTP 请求，包含重定向及前期试行 | 27 |
| 响应体读取总量 | 6,815,744 bytes，即 6.5 MiB |
| 完整提取成员 | 4：2 份 LIS、2 份 HTML |
| LIS 显式原 URL 映射 | 75 |
| 不支持的 LIS 行 | 0 |
| 已处理 HTML | 2 |
| 输出线索 | 53：2 条源页面提示、51 条链接或资源引用 |
| 不同 exact hostname | 3 |
| 映射存在、正文尚未取得 | 73 |
| 适配器读取原件成员字节 | 10,134 |
| 适配器新增网络请求 | 0 |

最初全目录加载的请求与字节没有从总成本中扣除。`members-02` 回执中的 3 请求/786,432 bytes 只是第二次打开缓存后的新增成本，不是整个获取过程。首轮主动暂停用于切换实现，不是服务端 429/503。

同一组原件实际经过既有 `discovery-job`、`run-local`、`collect` 三步，全部 exit 0。账本的 53 条均保留 `media_provenance` 和 `extraction_version`，所有 `observed_year` 为 null。原始 META 日期没有时区，本轮仅保存未经裁决的日期声明；不会从光盘出版日期或外链存在推断目标网站年度。

### 已实测的优化

- **选择性读取：**优化后的四成员解析只触达 6 个 256 KiB 块，共 1.5 MiB。断网缓存复放为 0 请求、0 新响应体字节、57 ms，四成员 SHA 均一致。这是已选范围的局部结果，不是整盘吞吐测试。
- **语法缓存：**按 HTML 字节、字符集与解析版本保存语法；每个原 URL、成员和映射仍分别解析绝对地址。重开缓存后 2 次命中、0 次正文重解析，三份输出 SHA 与首次一致；17/9 ms 只是两个页面的小样时间。
- **前沿批量评分：**同一个实际 `Frontier.choose`、1,000 个合成候选、3 次重复，旧实现中位 120.47 ms、新实现 84.03 ms，约 1.43 倍；SQLite 语句从 30,003 降至 9,007。每次选择重新读取反馈，不缓存跨选择的旧收益。该优化不代表网络或 EED 吞吐提高 1.43 倍。
- **基线投影：**导出回放时，对 outcome 键 K 涉及的每个年份只读取一次完整年度文件，到 EOF 验算摘要、顺序和行数；不按 action 重扫，也不把整个 B 放进 Python 集合。未涉及的年份单列为未扫描，K 的投影仍完整。

## 4. 完成发现与完成取证分别记录

`discovery_epoch` 在执行前固定输入、执行器文件 SHA、scope、预算上界、当时可见特征与初始前沿。父操作实际发现子节点后，须先声明这些子操作，再封存父回执中的 `reveals`。这样策略不会提前看到最终完整任务图。

| 操作类型 | 完成条件 | 对评分与学习的意义 |
|---|---|---|
| `discovery` | 事前输入/执行器/scope 与实际回执一致，输出文件逐项验算 SHA | 直接证据集合为空，可以揭示子动作；不调用 `import_settlement`，不生成负收益标签 |
| `evidence_review` | 声明之后生成的完整 settlement；节点、scope、实际成本一致；逐项网站证据与摘要可复核 | 导出已审核记录，由同一冻结 B/A 扣重；已知贡献全局只计一次 |
| 未执行 / 未完成 | 没有执行回执，或还有失败、截断、待审查范围 | `unobserved` / `incomplete`；保留实耗和原因，不改成零收益 |

媒体提取使用 `--scope-id` 时，输入 manifest 必须事前包含 `operation_scope`，绑定所选 mapping members、格式、root 和链接模式。该 manifest 的 SHA 再进入动作声明。只处理其中一个 LIS 或更换模式不能继续声称原 scope 完成。

媒体操作的完成只指 **所选映射文件已分类，且其中已取得、可明确绑定的 HTML 已处理**。缺体、冲突和不支持的行继续留在 review；本轮 73 个缺体不因两个 HTML 处理完而消失，整个光盘也没有关闭。

本轮另一次真实本地复放已先冻结上述参数，再生成计划并执行；回执通过桥接端的输入、执行器、scope 与真实输出 SHA 检查，2 个正文全部命中语法缓存、没有网络请求。由于仍未绑定真实 B/A，这只是实际操作回执接合验证，不是可排名的生产 epoch。

自动导出保留原始执行回执、封存 outcome、逐项审核证据定位、B/A 完整投影，再真实调用 RSIforme `prepare.py`；指定 `--evaluate-policy` 时还实际调用 `run.py`，其成功与失败结果均留档。此前没有事前声明的真实运行不能被追认为有效 recorded epoch；当前真实原件只验证输入输出接合，不伪装成完成了生产策略排名。

## 5. 运行入口

安装：

```bash
python -m pip install -e ".[media,source,test]"
python -m creeperman.media_reader --help
python -m creeperman.media_mapping --help
python -m creeperman.discovery_epoch --help
```

已有完整原件时优先本地读取，不重新下载：

```bash
python -m creeperman.media_reader \
  --local ../private-originals/PC_PRESS.ISO \
  --directory /WORLDWEB/WWW \
  --member '/WORLDWEB/WWW/10/INDEX.LIS;1' \
  --member '/WORLDWEB/WWW/10/00000001.HTM;1' \
  --source-id pcpress-1996-selected --origin-family pcpress-internet-cd \
  --out ../private-run/members

python -m creeperman.media_mapping \
  --manifest ../private-run/members/members.json \
  --mapping-format pcpress-lis --mapping-member '/WORLDWEB/WWW/10/INDEX.LIS;1' \
  --cache ../private-run/syntax.sqlite --out ../private-run/mapped
```

以上仅做提取，没有声明生产 epoch。远程模式另需精确 `--url --size --cache --allow-network`，每次实际访问都检查当前允许的对象 host；跨运行的请求与字节预算累计，忽略 Range 的 200 响应不触发整盘下载。当前 reader 支持 2048 字节扇区主 ISO9660 路径；多区段、交错及扩展属性等结构明确停止，不猜测解析。

获取预算按同一缓存累计，提供者唯一预算所有者由上层保证。字节指标是程序实际取得的响应体，不含 HTTP/TLS 开销；传输被进程中断而未完成记录时保留未决请求，禁止继续取块，其未知消耗不能当作精确零。

真实年度处理继续使用现有 `discovery-job` / `run-local` / `collect` / `census` / 审核 / `settle`。输入是 `observations.jsonl`，来源祖源为 `pcpress-internet-cd`；存放位置是 IA 不改变它的原始采集家族。

RSIforme 的完整声明与导出顺序见 [LIVE_POLICY_BRIDGE](https://github.com/Qesire/RSIforme/blob/main/examples/creeperman_replay/LIVE_POLICY_BRIDGE.md)。基本入口为：

```bash
python -m creeperman.discovery_epoch --db ../private-run/frontier.sqlite --epoch-id EPOCH_ID \
  init --baseline BASELINE_DIR --audit AUDIT_JSON --model MODEL_JSON \
  --rules RULES_FILE --budget BUDGET_JSON
python -m creeperman.discovery_epoch --db ../private-run/frontier.sqlite --epoch-id EPOCH_ID \
  declare --plan ACTION_PLAN_JSON
# 执行已声明的实际操作，再登记其回执；取证操作还需完整审核 batch。
python -m creeperman.discovery_epoch --db ../private-run/frontier.sqlite --epoch-id EPOCH_ID \
  finish --action-id ACTION_ID --execution-receipt EXECUTION_RECEIPT
python -m creeperman.discovery_epoch --db ../private-run/frontier.sqlite --epoch-id EPOCH_ID \
  export --out ../private-run/epoch --rsiforme-root ../RSIforme --evaluate-policy POLICY_JSON
```

大写项必须来自执行机真实输入。初始化之前，必须将当前全部累计已审核集合通过 `discovery_policy import-settlement --prior` 绑定，不能拿累计数量替代逐项 A。`evidence_review` 的 finish 必须另带 `--batch-id`；无完整审核则带具体 `--reason`，输出保持 incomplete。

## 6. 下一批按什么顺序做

PC Press 的已观察目录仍有其他条目，数量不等于不同主机数量。下一批先核对本地原件库存与完成范围，再读取尚未消费的 LIS，按真实 URL 建立 exact hostname 和原件位置索引；在执行机用真实 B/A 筛出需要补正文与日期裁决的范围。已有线索指向的未知本地主页继续作为显式成员任务，下载器 namespace、同站深层路径及 www 变体都不作为新站自动扩张。

保留两个目标：一是尚缺年度的直接原件，二是通向未处理原件的真实外链。基线内源页面如果能提供新链接或映射，仍可作为发现载体；它自身不能重复计分。只有多个未消费范围完成净增审核，才能估计稳定 EED/成本及剩余可得容量。

本轮没有新部署全球节点，没有绕过提供者限速，也没有继续此前中止的 IA 候选试验。当前单提供者仍只有一个预算所有者；全球 worker 可并行执行独立离线批次，跨机来源前沿的配额与租约调度尚未接入。

## 7. 验证与适用边界

全量验证结果及精确命令保存在[公开汇总](../audit/media_feedback_20261128.json)。测试覆盖 Range 实耗与缓存身份、真实格式合同、相对 URL 还原、同正文多 URL、冻结 scope、批量评分等价，以及发现父操作到审核子操作的跨仓 prepare/evaluate。

本地 Creeperman 129 项离线测试通过，六步 CLI 合成流程全部 exit 0；RSIforme 共 128 项，124 项通过、4 项原有可选原生依赖测试跳过，CPU demo exit 0。Creeperman CI 新增 media extra，并获取固定版本 RSIforme 以实际执行跨仓测试，避免仓库缺席时跳过桥接。

真实 PC Press 字节运行、合成策略比较和本地性能对照分别报告。没有把合成测试的 EED 写入生产账本，也没有以本轮三个主机推断整盘或全球来源产率。
