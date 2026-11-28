# 已接入真实前沿的发现策略

2026-11-28。基于 Creeperman `6831270`、RSIforme `639153b`。本轮把策略加载、路径反馈和具体原件起点接入现有执行器，并实际取得三个公开条目的元数据。没有执行历史候选查询或年度裁决，累计仍为 155 项、100.9875 EED，组织者尚未复核。

## 1. 已应用的部分

| 机制 | 实现入口 | 验收边界 |
|---|---|---|
| 有出处的种子及版次任务 | `config/discovery_bootstrap.json`、`discovery_bootstrap.initialize` | 4 个原始采集家族、7 个版次原件；只加入已观察的公开页面、条目和文件位置。库存未知不等于未处理 |
| 策略驱动真实前沿 | `source_frontier.Frontier.choose`、`source_pages.PageFrontier.run/reuse_queued` | `--policy` 读取 RSIforme 导出的白名单排序；原有 scope、robots、配额、冷却和本地复用继续生效 |
| URL、锚文本与上下文学习 | `discovery_policy.LivePolicy` | 记录真实父子边，完整裁决后沿祖先衰减反馈，更新可解释词项权重；这是受 ACHE 启发的轻量实现，未复现其完整分类器 |
| 全局唯一奖励 | `LivePolicy.import_settlement` | 先绑定可信累计 A；校验六年文件、权重、规则及审核记录，再扣除已见 exact hostname-year。路径学习不重复增加 EED |
| 完整零收益与未知区别 | 同上，`--complete --scope-id` | `settle` 本身只证明入选记录；还须声明具体范围已完整裁决并给出实测成本。HTTP 错误、目录解析成功、无结果或未知范围均不自动产生负标签 |
| 来源探索 | `LivePolicy.select` | 当前先验每五次选择保留一次低尝试家族探索。此参数尚未验证，不是 Good-UCB 理论保证，也不是已学得的最优值 |
| RSIforme 研究结果交付 | `examples/creeperman_replay/export_live.py` | 校验原候选、search、新 confirmation、profile、epoch 与封存证据；合成数据只可显式降级为 bootstrap，不能变成真实生产胜者 |

未加载策略时保留原有排序。加载后的每次选择保存实际策略摘要、选择模式和当时可见特征。普通资料元数据不写年度主表。

## 2. 起始任务为何是这些

[种子分析与原文引用](DISCOVERY_SEEDS_2026-11-28.md)说明 ACHE、ArchiveTeam、Arquivo 如何构造初始集合，以及这四类原件的具体映射关系。

第一步是查本地库存：PC Press 1996 的逐文件原 URL 表、Packard Bell 1998 的 Teleport 原链接属性、World Online Digest Burgundy 3 的目录—网址—本地正文对应，以及 IUCr Nexus 的 1997/2000/2001 出版方原件。先取得小型清单和映射，不在身份未知时下载全部容器。已有完整原件则复用，只补未完成操作。

新配置不重启 WebBase 全量名单或已消费 DMOZ 版次。`completed_operations` 只接受确切原件 SHA-256、算子及范围的完成收据，不能以家族名称关闭未见版本。DMOZ 六月 2001 版仍有损坏尾部，配置登记表已更正原来的“完整主目录尚未测”陈述。

这些是有真实输入、下一条边和结束条件的工作起点；尚无四类材料的基线外产率，不能把它们解释为足以补齐门槛的新矿。

## 3. 本轮真实执行

完整公开汇总见 [audit/discovery_live_20261128.json](../audit/discovery_live_20261128.json)。原始响应和私有执行库留在执行目录。

| 项目 | 实际结果 |
|---|---|
| 目录请求 | 3 次，PC Press、Packard Bell、WOD 的 IA metadata 均 HTTP 200 并完成解析 |
| 文件身份 | 取得三个实际容器的精确名称、大小、提供方声明 SHA-1/MD5；已写入种子配置，尚未用本地字节验算 |
| 窄范围页面爬取 | 3 次 robots 获取尝试均在 DNS 解析处失败；没有页面正文，4 个页面任务继续排队 |
| 策略选择 | 6 次实际选择：5 次按当前排序、1 次探索。选择次数不等于成功 HTTP 请求数 |
| 私有库存与旧累计 A | 本会话未绑定；全部 7 个原件仍为 `needs_inventory_match` |
| 历史候选查询、裁决批次、新增 | 均为 0；不能据此估计来源命中率或 EED/请求 |

本轮证明了“RSIforme 策略 → Creeperman 真实目录执行 → 文件描述符”可以运行。成功路径回授改变下一次取页顺序由合成合同测试验证，生产收益学习尚缺本地完整审核收据。没有启动模型自主修改策略，也没有把 bootstrap 称作已赢得真实对照的策略。

## 4. 直接运行

在 Creeperman 根目录，新运行目录均为私有输出：

```bash
python -m creeperman.discovery_bootstrap \
  --db ../private-discovery/source.sqlite \
  --manifest config/discovery_bootstrap.json

python -m creeperman.source_frontier \
  --db ../private-discovery/source.sqlite bind-local \
  --inventory ../private-input/inventory.tsv --root ../private-input/originals \
  --receipt ../private-input/download-receipts.json

python -m creeperman.source_frontier \
  --db ../private-discovery/source.sqlite run --providers ia \
  --policy config/discovery_policy_bootstrap.json \
  --max-requests 3 --interval 4 --max-depth 0 --max-pages 1 --max-children 1 \
  --user-agent 'CreepermanResearch/0.2 (+https://github.com/Qesire/Creeperman)' \
  --allow-public-catalog

python -m creeperman.source_frontier \
  --db ../private-discovery/source.sqlite export --out ../private-discovery/precheck
```

`precheck.jsonl` 保留每项库存判断，`acquisition_queue.jsonl` 是待处理意见，不自动下载。公开清单声明的哈希与本地实际字节一致，才允许复用。不要把样例路径当已存在的输入。

先将**当前全部累计 A**通过既有可信流程整理成 `settle` 输出，再绑定；只拥有汇总数不能伪造逐项记录：

```bash
python -m creeperman.discovery_policy --db ../private-discovery/source.sqlite \
  import-settlement --settlement ../private-input/cumulative-settlement \
  --model ../private-input/language-model.json --prior
```

每个新范围完成证据审核和结算后，导入其真实节点、范围与请求/字节/耗时成本：

```bash
python -m creeperman.discovery_policy --db ../private-discovery/source.sqlite \
  import-settlement --settlement "$SETTLEMENT_DIR" --model "$WEIGHT_MODEL" \
  --node-id "$OBSERVED_NODE_ID" --scope-id "$COMPLETED_SCOPE_ID" --complete \
  --requests "$ACTUAL_REQUESTS" --bytes "$ACTUAL_BYTES" --wall-millis "$ACTUAL_MILLIS"
```

上例变量必须来自真实收据。未完成范围不能使用 `--complete`。这会更新下一次排序和独立反馈台账；不替代正式年度提交与组织者审核。

## 5. 当前还缺什么

公开资料不能替代执行机上的 G 盘库存、155 项累计账本及原始审核证据。本轮已把可取得的文件身份查实；接下来先对账并定位容器内真实映射，按原件制作适配器，再走已有差集与裁决。`pcpress-url-map-v1` 等是登记的待执行操作标识，不表示四种容器解析器已经完成。

此外，生产请求、审核记录与完整范围到 RSIforme recorded epoch 的自动导出尚未实现；当前有经过测试的可信输入合同。现有全球 worker 可以执行独立批次，单提供者仍只有一个预算所有者。本轮没有新部署全球节点。

是否形成稳定增量，要由同一操作在多个未消费批次上的完整净收益和剩余库存判断。已有一次成功获取链足以决定从哪里开始，不能证明下一批的分数。

## 6. 验证结果

[验证汇总](../audit/discovery_integration_validation_20261128.json)：Creeperman 81 项离线测试通过，现有六步 CLI 合成流程全部 exit 0；RSIforme 共 128 项，124 项通过、4 项原有可选依赖测试跳过。10 项在线导出/跨仓桥接测试通过；其中真正调用 Archive、评价、确认、策略导出及 Creeperman 选择入口。后代裁决改变下一次取页选择的测试使用合成原件和固定 HTTP 响应。没有运行本轮真实 Temporal 集群或模型研究 worker。
