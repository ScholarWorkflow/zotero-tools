---
name: zotero-read
description: Read and search literature stored in the local Zotero library — browse collection trees, search by metadata / full-text / annotations, deep-read individual papers (metadata + abstract + PDF full text + notes + highlights) — and answer the user's questions with citations. Read-only, no API key, all via curl to the local zotero-mcp plugin (127.0.0.1:23120). Use when the user asks to find, summarize, explain, or quote papers stored in Zotero. Complement to zotero-save: zotero-save WRITES (search & import), this skill only READS.
---

# Skill: zotero-read

## What I do

读取与检索**本地 Zotero 库**中的文献（**只读、零写入**）：浏览分类树、按元数据/全文/标注搜索、深读单篇文献（元数据+摘要+PDF 全文+笔记+高亮标注），并带引用（zoteroUrl）回答用户问题。全程 curl 直连本地 zotero-mcp 插件（127.0.0.1:23120），无 API key、不碰云。

与 zotero-save（写入：搜索/导入/归类）互补——本 skill 只用读工具，绝不调用 write_* 系列。

Pipeline:

1. **健康检查**：Zotero 在跑（23119 ping）+ MCP 插件通（23120）
2. **定位**：`get_collections` / `search_collections` / `get_collection_items`
3. **检索**：`search_library` / `search_fulltext` / `search_annotations`
4. **深读**：`get_item_details` → `get_content` → `get_annotations`
5. **汇报**：标题/作者/年份/期刊/DOI/zoteroUrl；引用原文时保留原措辞

## When to use me

激活本 skill 当用户想要：

- 按主题/关键词在 Zotero 库中检索文献
- 全文检索某个概念/方法出现在哪些论文中
- 按分类浏览 Zotero 库
- 深读、总结、讲解单篇论文
- 查看某篇论文的笔记与高亮标注
- 回答问题时引用 Zotero 里存的文献

不需要：写入 Zotero（建条目/导入 PDF/改元数据）→ 用 zotero-save。

## Prerequisites — 必须先检查

### 1. Zotero 已打开 + cookjohn/zotero-mcp 插件已装并启用

```bash
curl -s --max-time 5 http://127.0.0.1:23119/connector/ping
curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:23120/mcp
```

- 23120 不通 → Zotero 没开、或插件没启用（Preferences → Zotero MCP Plugin → Enable Server，默认端口 23120）
- **无需**启动 translation-server（那是 zotero-save 写元数据用的；本 skill 只读不依赖）
- **无需**额外 `uv tool install` 或要求 PATH 中存在 `zotero-mcp-session`。建立 MCP session 的 helper 已随本 skill 打包在 `scripts/new-session.sh`。

## Zotero MCP 调用方式（curl 直连，唯一主路径）

Zotero 插件在 `http://127.0.0.1:23120/mcp` 提供 Streamable HTTP MCP。用 curl 按 JSON-RPC 调用。

### 步骤 A：建立会话（拿 Mcp-Session-Id）

先解析**当前已加载的 zotero-read skill 目录**（即包含本 `SKILL.md` 的目录），然后直接运行它携带的 helper：

```bash
# ZOTERO_READ_SKILL_DIR = 当前已加载的 zotero-read skill 的绝对目录
SID=$(bash "$ZOTERO_READ_SKILL_DIR/scripts/new-session.sh")
```

不要把 `zotero-mcp-session` 当作必需的全局命令。`zotero-tools` Python 包仍可提供同名 convenience CLI，但本 skill 的运行不能依赖它是否通过 uv/pip 安装到 PATH。

`new-session.sh` 会 POST `initialize` 到 `127.0.0.1:23120/mcp`，并从响应头提取 `Mcp-Session-Id`。

### 步骤 B：调工具（每条请求都带 Mcp-Session-Id 头）

```bash
curl -s --max-time 60 -X POST http://127.0.0.1:23120/mcp \
  -H "Content-Type: application/json" -H "Accept: application/json, text/event-stream" \
  -H "Mcp-Session-Id: $SID" \
  -d '{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"<工具名>","arguments":<JSON参数>}}'
```

响应的 `result.content[].text` 里是嵌套 JSON 字符串，需要再 parse 一次。

一次会话可连续复用（多条请求共用一个 SID）；会话过期、超时或返回 session error 后，重新执行本 skill 的 `scripts/new-session.sh`。

## 工具参考（只读工具）

| 工具 | 用途 | 参数示例 |
|---|---|---|
| `get_libraries` | 列出库 | `{}` |
| `get_collections` | 全部（子）分类，树形 | `{"recursive":true,"limit":100}` |
| `search_collections` | 按名搜分类 | `{"q":"Professor Example"}` |
| `get_collection_details` | 分类详情 | `{"collectionKey":"..."}` |
| `get_subcollections` | 子分类 | `{"collectionKey":"...","recursive":true}` |
| `get_collection_items` | 分类下的条目 | `{"collectionKey":"...","limit":50}` |
| `search_library` | 元数据检索 | `{"q":"<topic>","limit":20}` |
| `get_item_details` | 单条完整元数据 | `{"itemKey":"ITEMKEY01"}` |
| `get_item_abstract` | 只取摘要 | `{"itemKey":"..."}` |
| `get_content` | 摘要+附件正文+本地文件路径 | `{"itemKey":"...","maxLength":20000}` |
| `search_fulltext` | 全文检索 | `{"q":"<concept>","limit":10}` |
| `fulltext_database` | 全文缓存库快查 | `{"action":"search","q":"..."}` |
| `search_annotations` | 搜标注 | `{"q":"..."}` |
| `get_annotations` | 取指定条目标注 | `{"itemKey":"..."}` |

## 工作流

### 模式 A：主题检索（元数据级）

调用 `search_library`，给用户列候选表（标题/作者/年份/有无 PDF 附件），再按 itemKey 进入模式 D 深读。

### 模式 B：全文检索

```json
{"name":"search_fulltext","arguments":{"q":"<concept>","limit":10}}
```

参数名是 `q`，不是 `query`。优先试 `fulltext_database` 的 search action，命中不足再 `search_fulltext` 实时索引。

### 模式 C：按分类浏览

1. `get_collections {"recursive":true}` 定位 collectionKey
2. `get_collection_items {"collectionKey":"..."}` 获取条目列表
3. 选中条目后 `get_item_details`，按需 `get_content`

### 模式 D：单篇深读（核心）

```json
{"name":"get_item_details","arguments":{"itemKey":"ITEMKEY01"}}
{"name":"get_content","arguments":{"itemKey":"ITEMKEY01","maxLength":30000}}
{"name":"get_annotations","arguments":{"itemKey":"ITEMKEY01"}}
```

`get_content` 的 `attachments[].filePath` 是本地绝对路径，可直接读取 PDF 做页码级核对。

### 模式 E：标注与笔记

- 全库搜标注：`search_annotations {"q":"<关键词>"}`
- 单篇标注：`get_annotations {"itemKey":"..."}`
- 笔记：`get_item_details` 的 `notes[]`

## 汇报格式

回答用户问题时，凡引用 Zotero 文献，附：

```text
标题（年份），作者列表，期刊/会议，DOI
zotero://select/library/items/<key>
```

- 引用标注/原文时保留原措辞
- 全文来自 OCR 时可能存在识别错误，引用长段落时提示核对
- 引用后指出本地 PDF 路径，便于打开核对

## 注意事项

1. **只读**：绝不调用 `write_item` / `write_metadata` / `write_tag` / `write_note` / `create_collection` / `delete_collection` 等写工具
2. `result.content[].text` 是嵌套 JSON 字符串，需要二次 parse
3. `search_fulltext` 参数名是 `q`
4. 会话复用同一个 SID；超时/报错后重新运行本 skill 的 `scripts/new-session.sh`
5. `get_annotations` 必须给 `itemKey` 或 `annotationId` / `annotationIds`
6. `get_content` 长文可能被截断，用 `maxLength` 控制
7. 深读长论文时可把全文存到临时文件再分段读，避免上下文爆炸
8. 完成后汇报命中条目、选读论文、引用段落、本地 PDF 路径

## Troubleshooting

- **23120 不通**：Zotero 没开 / 插件未启用 / 端口被改
- **initialize 无响应或超时**：插件内部出问题，重启插件服务
- **`zotero-mcp-session: command not found`**：不要安装额外包来补这个命令；直接按步骤 A 调用当前 skill 自带的 `scripts/new-session.sh`
- **search_fulltext 报 `q (query) is required`**：参数名用 `q`
- **get_annotations 报 required**：必须给 itemKey 或 annotationId(s)
- **get_content 无附件内容**：条目没有可读 PDF 附件或附件未索引
- **全文检索没结果**：确认 Zotero 已对 PDF 做全文索引；可用 `fulltext_database` 查缓存状态
