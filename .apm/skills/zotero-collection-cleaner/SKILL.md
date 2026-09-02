---
name: zotero-collection-cleaner
description: Detect and clean duplicate or invalid Zotero collections while preserving the canonical collection mapping.
---

# zotero-collection-cleaner

清理 Zotero 分类树中的**重复/无效分类**（Tier 1：大学→専攻→lab→教授 层级）的唯一实现地。它以 `professor-collection-preparer` 产出的 `_zotero_collections.json`（path→key 映射）为权威锚点，检测同路径多副本、合并到 canonical、修复 parent 分裂、以清理结果为准更新映射文件，并自动验证。

## 范围分层（铁律）

| 层级 | 内容 | 本 skill 职责 |
|---|---|---|
| **Tier 1** | `大学/専攻/lab/教授`（及无 lab 的 `大学/専攻/教授`） | **本次清理的范围**：检测重复、合并、re-parent、删除、更新映射 |
| **Tier 2** | 教授分类下的研究方向分类（topic-clusterer 产物：`研究方向总结`、各研究方向等） | **范围外**：仅在报告中列出（标注「范围外，待结合 topic-clusterer 逻辑」），**绝不动作** |

- 判定：路径 P 是 Tier-1 当且仅当 **P == 某期望路径 或 P 是某期望路径的前缀**（期望路径见下）。期望路径最深到教授层；比教授层更深的重复组 = Tier-2。
- 删除的唯一依据：**同路径多副本（重复组）的 victim**。期望路径/目录/mapping **绝不作为删除依据**（只用于 canonical 优先级与 Tier-1 分类）。

## 期望路径集合（per program root）

| 来源 | 用途 |
|---|---|
| `<root>/教授研究/_zotero_collections.json`（prep 产物）`collections` 的路径 | **权威**（有则用；含 canonical key 与 parent 参考） |
| `<root>/教授研究/` 目录结构 | **并集补充**：教授文件夹 = 含 `papers.json` 或 `_done.json` 的目录；lab 文件夹 = 不含但子目录为教授文件夹；平铺的教授文件夹 → `大学/専攻/教授名`；嵌套 → `大学/専攻/<lab>/<教授名>` |
| `papers.json` 顶层 `zotero_collection`/`zotero_collections`（路径值） | 并集补充（无 mapping 时尤其重要） |

- `大学`/`専攻` 段：优先 `<root>/info.json`（`university`/`specialization` 或目录名解析）；缺失时从任一 `papers.json` 的 `zotero_collection` 路径取前缀（seg[0]=大学, seg[1]=専攻）。
- **所有名字匹配必须 NFKC 归一化**，避免兼容字符造成误判或悬挂。映射文件写入时用 **Zotero 快照里的原名**（不写入目录名）。

## Zotero MCP 会话（curl，与 zotero-collections 同套约定）

```bash
HDR=$(mktemp)
curl -s -D "$HDR" -X POST http://127.0.0.1:23120/mcp \
  -H "Content-Type: application/json" -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-03-26","capabilities":{},"clientInfo":{"name":"zotero-collection-cleaner","version":"1"}}}' -o /dev/null
SID=$(grep -i 'Mcp-Session-Id' "$HDR" | tr -d '\r' | awk '{print $2}')
```

```bash
curl -s --max-time 60 -X POST http://127.0.0.1:23120/mcp \
  -H "Content-Type: application/json" -H "Accept: application/json, text/event-stream" \
  -H "Mcp-Session-Id: $SID" \
  -d '{"jsonrpc":"2.0","id":N,"method":"tools/call","params":{"name":"<工具>","arguments":<JSON>}}'
```

响应的 `content[].text` 是**嵌套 JSON 字符串**，需再 parse 一次。一次会话可复用 SID。

**用到的工具**：`get_collections {"recursive":true}`（全树快照，唯一事实源）、`get_collection_details {"collectionKey":K}`（`meta.numItems`/`meta.numCollections`，**重复组成员逐个查**，不做全树详情）、`get_collection_items`（迁条目用）、`add_items_to_collection`、`update_collection`、`delete_collection`。

## 检测（快照内比较，无需期望路径参与删除判定）

1. `get_collections {"recursive":true}` → 归一化 `" > "`→`"/"` → 建 `normalized_path → [{key,name,parent}]` 列表。
2. **被管子树作用域**：找顶层分类中 NFKC 等于 `大学` 名的集合（唯一 → 作用域根；多个 → 报错让调用方处理；零 → error）。
3. 在作用域内分组：**同归一化路径 >1 个 key = 重复组**。
4. 每个重复组成员调 `get_collection_details` 拿 `numItems`/`numCollections`；为计划文件记录的条目数（重复组才有明细，不做全树详情）。
5. 分类（报告用）：
   - 重复组路径是 Tier-1 → **Tier-1 重复组**（本 skill 处理）
   - 重复组路径非 Tier-1（比教授层更深）→ **Tier-2 重复组**（报告列出，标「范围外」）
   - 唯一路径但非任何期望路径前缀 → **悬挂/未管理**（报告列出，不动作）
   - 期望路径中 0 条目 0 子分类 → **空分类**（报告列出，不动作；空分类可能是合法状态——还没跑 topic-clusterer 的教授）

## canonical 判定（确定性优先级，per 重复组）

1. **mapping 记录**：`_zotero_collections.json` 的 `collections` 对该路径记录过 key **且该 key 在本次快照中仍存在** → canonical（跨运行稳定，不因遍历顺序漂移）。
2. **直接条目更多**（`numItems` 更大）。
3. **直接子分类更多**（`numCollections` 更大；canonical 通常承载更完整的子树）。
4. **快照顺序第一**（检测遍历序）。
5. ①②③④ 全部打平（当前 schema 下实际不可能；防御未来变化）→ **question 工具问用户**（推荐选项 = 快照第一个），在**计划生成阶段**解决，绝不拖到执行阶段。

## 合并算法（自底向上：按重复组路径深度降序处理）

对每个 Tier-1 重复组（路径 P，canonical C，victims V[]）：

1. **迁移直接条目**（每个 victim）：`get_collection_items` 拿 itemKeys → `add_items_to_collection {collectionKey:C.key, itemKeys}`。Zotero 集合成员是 (item,collection) 唯一约束，重复 add 幂等；条目在库里仍保留一份，删分类不删条目（`delete_collection` 默认 `deleteItems:false`）。
2. **处理直接子分类**（每个 victim V 的每个直接子分类 S）：
   - S.key == canonical(S.path)（S 是其路径的 canonical，即 S.path 的重复组已处理完且 S 保留）→ `update_collection {collectionKey:S.key, parentCollection:C.key}`（re-parent 到本组的 canonical）。
   - S 是 victim（其路径的重复组更深，已按深度降序先处理 → S 已被删）→ 断言 S 已不在快照，跳过。
   - S.path 唯一且仍属于 Tier-1（如挂在 victim 下的独生子分类）→ re-parent 到 `canonical(P)` = C.key；Tier-2 子分类只报告，绝不 re-parent。
3. **删除前重查**（防御中间态）：`get_collection_details` 确认 `numItems==0 && numCollections==0`；非空 → **跳过删除并报错**（fail-stop，记入日志）。
4. **删除 victim**：`delete_collection {collectionKey:V.key}`（默认不删条目）。

深度降序保证：更深的重复组先合并删除，其父级副本随后只剩空壳 → 删除。

## 执行纪律

- **fail-stop**：任何一步 API 失败 → 立即停止；已执行动作保留（快照已变，重跑时已完成动作自然 no-op 幂等）；**不写** `_zotero_collections.json`；报告已完成/未完成清单。
- **动作级日志**（append-only）：每个动作一行 JSON 追加到 `<root>/教授研究/_zotero_cleanup_actions.jsonl`：`{"ts":...,"action":"reparent|add_items|delete","key":"...","path":"...","args":{...},"result":"ok|error","error":...}`。写入用 `>>` 追加（不覆盖）。
- 删除动作在执行时**逐个串行**，不并行（同一棵树 TOCTOU 禁止）。
- 执行前必须已获得用户确认（两步式：计划文件 → 用户确认 → 执行）。

## 计划文件与报告

- `<root>/教授研究/_zotero_cleanup_plan.json`：
```json
{
  "generated_at": "<ISO-8601 UTC>",
  "program_root": "<abs>",
  "university": "<大学>",
  "mapping_file": "<abs or null>",
  "snapshot_before": {"<key>": {"path": "...", "name": "...", "parent": "...", "items": N, "subs": N}},
  "dup_groups": [{
    "path": "...", "tier": "1|2", "keys": ["..."],
    "canonical": {"key": "...", "reason": "mapping_record|more_items|more_subs|snapshot_order|user_choice"},
    "victims": [{"key": "...", "items_to_move": N, "subs_to_reparent": [{"key": "...", "path": "...", "to_parent": "..."}]}]
  }],
  "reparents": [{"key": "...", "path": "...", "from_parent": "...", "to_parent": "...", "reason": "..."}],
  "deletes": [{"key": "...", "path": "..."}],
  "tier2_groups": ["<path> ..."],
  "hanging": ["<path> ..."],
  "empty_expected": ["<path> ..."],
  "summary": {"dup_groups": N, "deletes": N, "reparents": N, "item_moves": N, "tier2_groups": N, "hanging": N, "empty_expected": N}
}
```
- `<root>/教授研究/_zotero_cleanup_report.md`：人类可读报告（重复组明细表、canonical 理由、悬挂清单、空分类清单、Tier-2 清单标范围外、执行结果）。

## 收尾：以清理结果为准更新映射 + 自动验证

1. **验证**（写 JSON 之前）：
   a. 重新 `get_collections` 快照 → **断言 Tier-1 重复组 = 0**。
   b. 预写映射校验：每个将写入的 key 在快照中存在；每条映射的 `parent` 字段 = 快照中实际父 key；每条映射路径的祖先链段名（NFKC）与快照一致。
    - 任一失败 → **不写映射文件**，返回 error；重跑时先修复失败原因再写入。
2. **更新/生成 `<root>/教授研究/_zotero_collections.json`**（schema 与 zotero-collections 完全一致）：
   - 已有 mapping：`collections` 中每条路径的 key 统一为清理后 canonical、`parent` 修正为清理后实际父 key；`professors` 不变（路径不变）。**不是重写**——只改 key/parent 字段，保留其余（program_root/university/specialization/updated_at 刷新）。
   - 无 mapping：按快照生成全量 `collections`+`professors`（教授层路径，key 用快照原名对应 key；无重复则天然唯一）。
   - `updated_at` 刷新为当前 UTC。
3. 幂等契约：清理完成后重跑 → 检测重复 = 0 → 计划为空（报告「已干净」），映射重写幂等（内容不变）。

## 已知限制

- 不处理 Tier 2（研究方向分类）重复——设计上属于 topic-clusterer 逻辑的后续任务；本 skill 仅报告。
- 不重命名、不合并"不同名字的同一教授"（NFKC 相同视为同一路径会自然进入重复组，名称实质不同的不合并）。
- 不主动清扫空分类（空 = 合法状态）；仅报告。
- 不处理被管子树之外的任何分类（顶层其他分类均保持不变）。
