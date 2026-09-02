---
name: zotero-collections
description: Zotero 分类树的单一事实源：把「教授分类层级」的路径计算 + find-or-create（防重）+ 映射文件（_zotero_collections.json）读写 固定在这一处。全树快照 → path→key 映射 → 只补缺失路径，逐级用父 key + 叶子名 create。供 professor-collection-preparer 建分类、professor-worker 读映射直接操作分类、日后 topic-clusterer 复用。加载本 skill 时：按路径计算规则算出目标路径 → find-or-create 拿 key → 写/读映射文件。Use when 需要创建/定位 Zotero 分级分类（<大学>/<専攻>/<lab>/<教授名>）、避免并行重复建分类、或读取分类 key 映射文件。
compatibility: opencode
license: MIT
metadata:
  author: custom
  version: 1.0.0
---

## What this skill is

Zotero **分类树**的唯一实现地。它只负责三件事，其余一律不管（不建条目、不挂附件、不抓网页）：

1. **路径计算** — 从教授的 lab/labs 算出完整分类路径。
2. **find-or-create（防重核心）** — 幂等定位/创建层级分类：先全树快照建 path→key 映射，已存在直接复用，只补缺失层；**绝不同路径建两次**。
3. **映射文件读写** — `<program_root>/教授研究/_zotero_collections.json`（path→key 映射）的 schema 与读写约定，供 prep 写、worker 读。

## 设计背景

并行调用若各自执行 `search_collections {"q":"<完整路径>"}` + `create_collection`：
- zotero-mcp 的 `search_collections` **只按叶子名子串匹配**（源码 `collection.name.includes(q)`），按完整路径查**永远返回 `[]`** → 每次都落到 create 分支；
- 并行 worker 对共享祖先（学校→専攻→研究領域）同时 search-then-create = TOCTOU → 可能建出同名分类副本。

**结论**：分类创建必须由**单一串行执行者**（professor-collection-preparer）用本 skill 完成；其余角色只读映射文件拿 key。

## Zotero MCP 会话（curl，与 zotero-save 同套约定）

```bash
HDR=$(mktemp)
curl -s -D "$HDR" -X POST http://127.0.0.1:23120/mcp \
  -H "Content-Type: application/json" -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-03-26","capabilities":{},"clientInfo":{"name":"zotero-collections","version":"1"}}}' -o /dev/null
SID=$(grep -i 'Mcp-Session-Id' "$HDR" | tr -d '\r' | awk '{print $2}')
```

```bash
curl -s --max-time 60 -X POST http://127.0.0.1:23120/mcp \
  -H "Content-Type: application/json" -H "Accept: application/json, text/event-stream" \
  -H "Mcp-Session-Id: $SID" \
  -d '{"jsonrpc":"2.0","id":N,"method":"tools/call","params":{"name":"<工具>","arguments":<JSON>}}'
```

响应的 `content[].text` 是**嵌套 JSON 字符串**，需再 parse 一次。一次会话可复用 SID。

## 路径计算规则（与 professor-worker Step 5A 一字不差）

| 条件 | 分类路径 |
|---|---|
 | 有 lab（`professor.lab` 非空） | `<university>/<specialization>/<lab>/<教授名>` |
 | 无 lab，有 specialization | `<university>/<specialization>/<教授名>` |
| 无 lab 无 specialization，有 department | `<university>/<department>/<教授名>` |
| 以上皆空 | `<university>/<教授名>` |
| 多 lab（`labs[]` 多个） | **每个 `labs[i]` 各一条**：`<university>/<specialization>/<labs[i]>/<教授名>`；`lab`（=labs[0]）是主分类，仅决定本地主目录，不改变 Zotero 结构 |

- 分段都取**官方分组名原文**（如 `Example Research Area` / `研究領域A`），不自行发明/简化。
- `lab_type` 只作记录，不改路径结构。

## find-or-create（防重核心流程）

> 两条铁律：
> 1. **绝不用斜杠全路径当 `name` 传 `create_collection`** — 会把 `"大学/専攻/.../教授名"` 整个字面量建成一个 **depth=0 顶层错名分类**。
> 2. **不用 `search_collections` 按完整路径查** — 它只 `name.includes(q)`，全路径永远 miss；用它查叶子名会命中同名多副本、无父级限定，不可靠。

正确流程（单次全树快照 + 逐级建链）：

1. **全树快照**：`get_collections {"recursive":true}` → 递归树（每节点含 `key/name/path/subcollections`，path 用 `" > "` 分隔）。归一化 `" > "`→`"/"` 后建 `path → key` 字典。
2. **对每个目标路径**：
   - 快照中已存在（`normalized_path` 精确命中）→ 直接复用其 key。**同路径多副本 → canonical 选择顺序：① 上一版 `_zotero_collections.json` 记录过、且该 key 在本次快照中仍存在的旧 key（跨运行稳定，不因遍历顺序漂移）；② 否则取快照第一个**。非 canonical 副本留给存量清理，不 merge。
   - 不存在 → **逐级建链**，每级只做两步：
     a. 定位父 key：快照里按父路径查；查不到就递归先建父级。
     b. `create_collection {"name":"<该级叶子名>","parentCollection":"<父key>"}` → 拿新 key 并**立即写回快照字典**（后续级直接可见）。
   - 级序固定：`<学校>`（无 parentCollection）→ `<専攻>` → `<lab>` → `<教授名>`。
3. **create 失败 / 父 key 失效** → 立即停止，返回 error（不静默跳过、不重试循环）。

## 映射文件 `_zotero_collections.json`

**路径**：`<program_root>/教授研究/_zotero_collections.json`

```json
{
  "program_root": "<abs>",
  "university": "<大学>",
  "specialization": "<専攻名 or null>",
  "updated_at": "<ISO-8601 UTC>",
  "collections": {
    "<完整路径>": { "key": "8CHARKEY", "name": "<叶子名>", "parent": "<父key or null>" }
  },
  "professors": {
    "<教授名>": ["<完整路径>", "..."]
  }
}
```

- `professors[教授名]` = 该教授的全部分类路径（多 lab 教授多条）。键用完整路径天然防重。
- 写：prep 建完分类后**整体覆写**（live 快照是权威）；**canonical 稳定**：写前读上一版文件，对已存在路径若其旧 key 在本次快照仍存在则沿用旧 key（防遍历顺序漂移导致 canonical 跳变），只有旧 key 失效/新路径才取快照第一个。
- 读（worker）：`professors[<我的教授名>]` → 路径列表 → 每条从 `collections` 取 key。读不到 → 返回 error「分类不存在，由 professor-collector 重新处理」，绝不自行重建。

## 幂等性契约

- 本 skill 的 find-or-create **天然幂等**：全量快照是唯一事实源，已存在永远复用、只补缺失。同 program 重跑（pdf_only / force / 新教授加入）安全。
- **canonical 跨运行稳定**：上一版 `_zotero_collections.json` 记录的 key 若在本次快照仍存在则优先沿用（防遍历顺序漂移导致 canonical 跳变）；只有旧映射缺失/旧 key 失效的路径才取快照第一个。
- 快照只取一次；之后每 create 一条都写回快照，保证同一次运行内后续查找可见。
- 不删除、不 merge、不 rename 任何已有分类（存量重复清理是独立任务，不归本 skill）。

## 调用约定

- **professor-collection-preparer**（agent）加载本 skill 执行：输入 = 教授列表（含 lab/labs）+ university/specialization/program_root；输出 = 建好的 `_zotero_collections.json` + 结果 JSON。
- **professor-worker**（agent）加载本 skill 只为**读**映射文件拿 key（或理解 key 失效时的 error 语义）；正常路径不调用任何 create。
- **topic-clusterer**（现行）复用同一 find-or-create 定位教授分类，不再自己写一套：读 `<program_root>/教授研究/_zotero_collections.json` 拿主 lab 与各镜像 lab 的 key；映射缺失时才全树快照兜底。新建方向子分类/「研究方向总结」笔记分类时在快照内核对重名，保证新建不重复。

## 已知限制（写给后续维护者）

- `search_collections` 只匹配叶子名子串、不匹配路径（zotero-mcp 源码 `handleSearchCollections`）。任何需要「按路径精确查」的场景都用 `get_collections recursive:true` 快照，不要用 search。
- `create_collection` 无唯一性约束（永远 `new Zotero.Collection()` + saveTx）——所以「先查后建」必须串行且以快照为据；并行创建是重复的根源。
- `get_collections` 不传 `recursive` 时只返回顶层（默认分页 limit）；层级解析必须 `recursive:true`。
