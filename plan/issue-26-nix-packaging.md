# Issue #26：Zotero 日常工具与分类清理器的 Nix 独立打包执行计划

- 计划版本：`issue26-plan-v3-2026-10-15`
- 需求版本：[Issue #26](https://github.com/ScholarWorkflow/zotero-tools/issues/26)，2026-10-15 初始正文；以及同日用户补充的现有配置保留与冲突显式处理要求。
- 仓库基线：`ScholarWorkflow/zotero-tools@7c39f03f0d6010e3e4ce8e51f7fc8ba761ef58d8`，默认分支 `master`
- 目标仓库：`ScholarWorkflow/zotero-tools`；所有正式实现继续提交到本计划所在拉取请求分支
- 拟议审核状态：`Proposed review status: pending`。实施核心方案前按 Plan Reviewer Rule 完成正式审核；本文件不声明任何审核关口通过，也不声明测试通过。
- 本轮提交内容：仅执行计划；未实现 Nix 打包，未执行正式测试。

## 一、需求判定与文档核对

**结论**：Issue #26 所列需求和“最小构建、安装、资源及命令入口检查”没有与当前 Codex 官方文档直接冲突的条款。Issue 未给出具体测试命令或模型冒烟要求；不修改既定业务目标和测试上限。本计划补充安装产物必须遵守的 Codex 文件位置与角色格式，防止把“包已构建”误认成“宿主已经发现技能”。

### 正式要求（规范性来源）

1. Issue #26：两个可分别选择的包 `zotero-tools` 与 `zotero-collection-cleaner`；cleaner 不为日常包的强制依赖。
2. 日常包交付 `zotero-read`、`zotero-collections`、`zotero-paper-tagger` 三个完整技能目录，`zotero_tools` Python 模块与三个既有命令入口。
3. cleaner 包交付 `zotero-collection-cleaner` 完整技能与同名角色，保留执行前确认及已存在的保护行为。
4. 仅声明真实直接依赖，锁定构建输入，构建后运行不动态拉包；本地 Zotero Desktop、MCP 插件与 HTTP/MCP endpoint 继续由用户提供。
5. 保留现有 APM 与 Codex/OpenCode 兼容内容、用户可写状态、凭据的运行时注入；不修改消费者仓库，不引入公共新仓库或新的安装器。
6. 测试上限是两个包的构建、安装、文件资源与命令入口；没有授权新增业务测试、模型认证、judge 关口或实际清理 Zotero 数据。

### 已核实的现实（描述性来源）

| 决策 | 依据及版本 |
|---|---|
| 产物须拆开，但源代码保持单一归属 | `.apm/skills/{zotero-read,zotero-collections,zotero-paper-tagger,zotero-collection-cleaner}/`、`.apm/agents/zotero-collection-cleaner.agent.md`，仓库基线 `7c39f03`：[资源目录](https://github.com/ScholarWorkflow/zotero-tools/tree/7c39f03f0d6010e3e4ce8e51f7fc8ba761ef58d8/.apm) |
| 三个命令及 Python 最低版本有明确来源 | `pyproject.toml`：`requires-python >=3.11`、`zotero-paper-tagger`、`zotero-mcp-session`、`zotero-item-export`；同一 [基线文件](https://github.com/ScholarWorkflow/zotero-tools/blob/7c39f03f0d6010e3e4ce8e51f7fc8ba761ef58d8/pyproject.toml) |
| 命令包装必须能定位技能外资源 | `zotero_tools/tagger.py`、`zotero_tools/session.py` 根据模块所在目录向上寻找 `.apm/skills/`；Nix 安装进 Python 库目录后，该相对推导不再自然成立：[tagger.py](https://github.com/ScholarWorkflow/zotero-tools/blob/7c39f03f0d6010e3e4ce8e51f7fc8ba761ef58d8/zotero_tools/tagger.py)、[session.py](https://github.com/ScholarWorkflow/zotero-tools/blob/7c39f03f0d6010e3e4ce8e51f7fc8ba761ef58d8/zotero_tools/session.py) |
| 技能内部调用需固定解释器与工具 | `zotero-read/SKILL.md` 的导出示例用 `uv run`；`zotero-collections`/cleaner 使用 `curl`、`grep`、`awk`、`tr`、`mktemp`；`corresp_extractor.py` 调用 `pdftotext`，并有 `fitz` 备用入口，见上述基线各文件 |
| Codex 技能须由宿主可发现 | [Codex 官方 Skills 文档](https://developers.openai.com/codex/skills)：项目的 `.agents/skills/<skill>/SKILL.md` 是受支持位置；单纯存在于 `/nix/store` 不保证被发现 |
| Codex 角色必须使用正式结构 | [Codex 官方 Subagents 文档](https://developers.openai.com/codex/subagents)：项目的 `.codex/agents/<name>.toml`，包含 `name`、`description`、`developer_instructions`；不能直接把 OpenCode 的 Markdown 角色文件当作 Codex 角色 |
| 当前宿主转换基线存在 | `test/test_apm_codex_projection.py`、`test/test_apm_opencode_projection.py` 在 APM `0.29.0` 的既有测量中分别核验 Codex TOML 与 OpenCode Markdown；`apm.yml` 当前目标是 `[opencode, codex]` |
| 包导出可由 Nix 表达 | [Nix Flakes 文档](https://nix.dev/manual/nix/stable/command-ref/new-cli/nix3-flake) 的 `packages.<system>.<name>`、`flake.lock` 与 `nix build`，项目复用既有 Nix 工具 |

**重要边界**：官方 Codex 文档规定宿主加载目录及文件格式；没有承诺 Nix store 中任意包会被自动注册。安装投影由现有 APM 路径或者下游已支持的 Nix 接入方式完成；本议题只提供可组合的标准资源输出及接入说明，不新增安装器、不猜测宿主内部私有参数。

## 二、冻结方案与修改范围

### 2.1 方案与替代选择

采用**单仓库、两个独立 Nix 输出、共享同一套原始资源**：

- `packages.<system>.zotero-tools`：日常三技能、脚本与 schema、完整 `zotero_tools` Python 包、三个命令行入口；不包含 cleaner 技能或 cleaner 角色。
- `packages.<system>.zotero-collection-cleaner`：cleaner 技能与角色，分别给 Codex 和 OpenCode 提供受支持的投影；不强制带入日常三技能。
- 资源源头仍是仓库已有的 `.apm/`，不维护第二套人工业务正文。
- 宿主选择一个或多个资源根时，保持目录结构，将选中的资源根接入既有宿主所识别的位置；cleaner 需显式选择。
- 第三方依赖使用由 `flake.lock` 固定的 Nixpkgs；新增依赖仅在本仓真正调用时声明，不能因为上游输入来自 `professor-research` 就将其作为构建依赖。

曾考虑把所有功能做成一个大包、由安装时开关隐藏 cleaner。该方案仍会把可能改写或删除分类的角色随日常环境一起部署，与 Issue #26 的独立选择目标冲突。还考虑运行时执行 `uv run` 或 APM 重新生成环境；该方案会动态获取依赖，违背固定运行环境要求。最终选择上面的构建期打包与投影。

### 2.2 产物接口（实现时按此冻结）

两包在各自只读输出根内提供 `share/scholarworkflow/` 资源树，约定如下：

- 日常包：`share/scholarworkflow/.agents/skills/zotero-read/`、`zotero-collections/`、`zotero-paper-tagger/`（技能目录连同其 `scripts/`、`CORRESPONDENCE_SCHEMA.md` 等资源），以及独立的 `bin/zotero-paper-tagger`、`bin/zotero-mcp-session`、`bin/zotero-item-export`。
- 日常 Python 模块：从该包固定解释器可 `import zotero_tools`；三个命令即使从仓库外任意工作目录启动，也能找到其被打包的原始帮助脚本。
- cleaner 包：`share/scholarworkflow/.agents/skills/zotero-collection-cleaner/SKILL.md`、`share/scholarworkflow/.codex/agents/zotero-collection-cleaner.toml`、`share/scholarworkflow/.opencode/agents/zotero-collection-cleaner.md`。
- `.codex/agents` 输出从现有 `.apm/agents/zotero-collection-cleaner.agent.md` 生成 `name`、`description`、`developer_instructions`；`.opencode/agents` 保留原有 frontmatter 和业务正文。不得把 OpenCode 的 `hidden`、`permission`、`question` 当成 Codex 权限字段，不创造新的 Codex 调用签名。
- 输出根中的技能和角色**只是可安装资源**。消费者接入后，Codex 项目位置应为 `.agents/skills/`、`.codex/agents/`；OpenCode 角色按现有 `.opencode/agents/` 投影。不能用 store 文件存在来声称宿主已经加载。
- Nix-only 路径适配和脚本固定解释器适配不得修改原始 `.apm/` 的业务正文；确需修改共用 Python 入口时，保留原先的开发/原 APM 路径作为未设置 Nix 资源路径时的行为。
- 两个包分别导出独立属性与固定 Nix store 路径；不规定消费者必须只接受单一 root，不新增跨仓安装协调器。

上述接口属于本议题选择的包装合同；其余派生器内部变量名与等价构建写法可由实现者决定。

### 2.3 所有者、预期变化、保持行为

| 项目 | 归属与约束 |
|---|---|
| 原始技能和角色内容 | 本仓 `.apm/` 拥有；既有清理计划→询问→执行、Tier-1/Tier-2 边界、串行失败即停、映射文件保护均保持 |
| Python 入口与资源定位 | 本仓 `zotero_tools/` 和打包包装拥有；新增 Nix 资源定位时，不破坏开发环境与 APM 的既有寻找方法 |
| Nix 构建、依赖与资源投影 | 本仓 `flake.nix`、`flake.lock`、`nix/` 拥有；不存在运行时下载/创建 Python 环境 |
| Codex/OpenCode 的实际会话、代理调度与 MCP 设置 | 由使用它的宿主及其配置拥有；Nix 包不替用户注册或模拟 MCP 服务 |
| Zotero 数据、缓存、日志、凭据 | 运行时与用户选定的程序根拥有；不能构建时预填凭据，不能写入 Nix store |
| 消费者 professor-research/contact | 消费者自行选择包、验证自身依赖；本次不修改其源码与测试 |

预期变化只有两项：新增两个独立 Nix 可消费输出，以及为这些输出增加必要的包装/路径适配。**保留行为**包括现有 APM 安装、四个源技能与一个源角色、三个 CLI 的业务功能、运行时端点覆盖、cleaner 的人工确认。**禁止副作用**包括：默认引入 cleaner；自动连接、修改或删除真实 Zotero 收藏；重写业务 schema；绕过 Codex 现有原生 MCP 路由；修改 OpenCode 交互规则；将凭据或用户状态存入 store；新增公共服务或宿主迁移。

### 2.4 可选宿主接入的配置保留约定

本仓仍只提供所选包必需的资源、入口及最小接入片段/说明，不生成替换整份用户配置的模板，不新增安装器或配置合并器。实际接入由消费者现有受支持的项目入口完成，默认限于选定项目；纯 CLI 使用或读取资源无需创建或改写宿主配置，已有 Zotero MCP 继续由宿主拥有。

- 资源映射或必要配置接入须保留其他技能、角色、MCP 以及用户模型、provider、权限、hooks 等无关配置和未知字段；不得整份覆盖 Codex/OpenCode 配置或整目录替换已有技能/角色。
- 只检查本次实际映射的技能/角色目标，以及确需接入的配置键及其父级/全局继承值，不扫描无关资源。已有 APM、其他 roots 或用户提供的目标定义相同且可复用时，保留并复用，无需额外确认且不认领所有权；定义不同或实际目标冲突时，报告具体来源并保持现状，由用户明确保留原来源或切换后再继续该项，不依赖加载优先级静默遮蔽或覆盖。
- 升级/卸载只更新或移除现有接入方式能够确认由本包管理、且仍与上次生成内容一致的项或链接。用户编辑过、来源不明、其他包所有的内容保留并报告；无法安全区分时停止该项交给使用方，不删除整份配置或共享目录。日常包与 cleaner 的独立选择及原有 APM 安装语义保持。

先前 v2 修订仅影响 2.4 和第 4 步的接入所有权、冲突与生命周期。本次 v3 依照用户对测试审核意见的处理决定，仅补齐第五节 T3 的角色正文比对、T4 的受控会话入口与原源码路径兼容检查；既有 T1–T5 业务目标及数量不变，T5 不新增依赖获取取证。包划分、角色保护、运行时秘密处理不变；相关 P1–P4 决定保持 `Proposed review status: pending`，不继承旧批准。检查或复验按 Test Engineer Rule 处理，不新增测试关口。

## 三、实施顺序（本地代理逐项完成）

### 第 0 步：锁定输入和检查已有关联

1. 在目标仓库确认 `master` 与本 PR 分支的提交；记录实施时的精确 SHA、`nix --version`、当前 Nixpkgs/平台信息。若仓库已变化，先对比是否影响本计划的资源路径或工具调用事实；只改受影响的决定。
2. 再读当前 `apm.yml`、`pyproject.toml`、四个 `SKILL.md`、cleaner agent、`zotero_tools/` 入口及 `scripts/`，确认本文列出的每一个资源仍存在；仅据已确认的直接调用补依赖。
3. 记录文档查核日期、Codex/已有 APM 转换依据；若实际采用了与 APM `0.29.0` 不同的转换程序，先核对生成文件与官方格式和现有源角色的语义是否相同。
4. 业务实现以前取得正式的 Plan Reviewer 审核批准。审批未通过，只修改本 `plan/issue-26-nix-packaging.md` 后在同一 PR 复审，不另开实现 PR。

### 第 1 步：建立本仓的 Nix 导出入口

1. 新增 `flake.nix`、`flake.lock`；使用同一锁定的 Nixpkgs 输入，在目标平台公开上文两个 `packages.<system>` 属性。包名必须稳定；不要将 cleaner 塞进日常包的 `default` 闭包。
2. 将构建定义置于 `nix/` 下，本仓维护直接依赖与打包步骤，优先使用 Nixpkgs 已有 Python 构建、`makeWrapper`、基础脚本工具，不写新的通用安装器，也不引入公共仓库。
3. 包输出只含构建期取得的源码和依赖；不在生成的启动命令里执行 `pip install`、`uv run` 的在线解析、`nix shell`、`npx` 等动态获取操作。需要生成宿主投影时在构建期完成，不能要求最终用户手工改 store 文件。
4. 尽量保留现有 `apm.yml`、`pyproject.toml`、`README.md` 的 APM 安装入口；如 Python 的 Nix 构建确需补充 `build-system` 元数据，只加入最小标准字段。

### 第 2 步：完成 `zotero-tools` 日常包

1. 安装 `zotero_tools` 的全部模块与三个原有 console scripts，固定 Python ≥3.11；对 `zotero_tools/tagger.py` 和 `zotero_tools/session.py` 增加**包资源根解析**：Nix 启动包装传入明确的安装资源根，未传入时继续使用既有源码树定位，不能依赖调用方 `cwd`。
2. 将三个日常技能完整目录投影到 `share/scholarworkflow/.agents/skills/`。包括 `zotero-read/scripts/new-session.sh`、`zotero_item_export.py`、`item_export_core.py`，以及 tagger 目录的三个 Python 辅助脚本和 `CORRESPONDENCE_SCHEMA.md`；以当前源树为依据，不仅复制 `SKILL.md`。
3. 解决 `zotero-read` 的 `uv run`：仅在 Nix 分发副本或其包装中把导出脚本执行接到固定的 Python 解释器；保留原技能以 `<skill_dir>` 找同目录 helper 的调用含义。不在运行时下载依赖、不改导出结果 schema。
4. 在 Nix 启动环境与技能运行所需的可执行闭包中提供实际使用的 `bash`、`curl`、`grep`、`awk`、`tr`、`mktemp`、`pdftotext` 等工具；`corresp_extractor.py` 的 PDF 解析备用路线如随分发保留，配套提供对应的固定 Python `fitz` 库。将运行所需工具暴露给真正执行技能的宿主，不可只给 CLI 包装设置 `PATH` 却让技能中的 shell 命令找不到工具。
5. 继承 `ZOTERO_HTTP_URL`、`ZOTERO_MCP_URL`、`ZOTERO_STORAGE_ROOT` 等既有运行时参数，不在构建期解析成具体用户地址；保证缓存、报告与导出结果写到用户工作目录、程序根或显式指定的输出目录。
6. 本包不包含 `zotero-collection-cleaner` 角色；不主动接触 Zotero 用户库来证明打包成功。完成后记录此包的可固定引用输出、当前检查结果和未解决依赖，供下游先行接入。

### 第 3 步：完成 `zotero-collection-cleaner` 独立包

1. 从唯一源 `.apm/skills/zotero-collection-cleaner/` 与 `.apm/agents/zotero-collection-cleaner.agent.md` 打包；保留完整正文、原有确认问题及错误/部分完成返回约定。构建期生成符合官方字段要求的 Codex 角色 TOML 与保留原始 OpenCode 形状的 Markdown。
2. Codex 文件 `name=zotero-collection-cleaner`；`description` 与 `developer_instructions` 对应源 agent 的描述及正文，不携带 OpenCode 专有权限前言作为 TOML 权限设定。沿用当前 Codex 角色正文内原生 MCP、`needs_input` 与同一子代理恢复的既有约定，不在此项增加交互协议。
3. 只加入 cleaner 的真实直接依赖和必要的固定 shell 环境。cleaner 当前描述中的 `professor-collection-preparer` 是运行时映射文件来源，不是 Nix 依赖；除非实现确实调用日常包中的共享 endpoint helper，否则不要依赖整个日常包或 `professor-research`。
4. 选择 cleaner 不能自动启动清理：真正运行时仍须生成计划、询问用户、得到明确“执行”后才可以修改数据；`plan` 模式和取消选项保持原样。构建、安装和入口检查中绝不发送删除、合并或改写收藏的指令。
5. 记录 cleaner 的独立输出和未解决运行条件，不阻塞日常包发布。

### 第 4 步：接口映射与宿主兼容

1. Nix 输出给出 `share/scholarworkflow/` 下稳定的**相对资源路径**；下游已有 Nix 接入方式选择任意多个包输出，按 2.4 的配置保留与冲突约定，把选中资源映射到宿主支持的项目目标目录。不将每个项目的自制安装器当作前置。
2. 对 Codex 只输出 `.agents/skills` 与 `.codex/agents/*.toml` 正确载体；对 OpenCode 保留 `.agents/skills` 与 `.opencode/agents/*.md`。如果下游只安装 CLI 而没有完成资源映射，文档必须如实说明技能不会仅因 Nix 包存在而被 Codex 自动发现。
3. 仓库原 `.apm/` 原始内容、`apm.yml`、APM 自动投影的既有测试语义保持不变；不要把构建生成的 `.codex/agents` 或 `.opencode/agents` 提交为新的人工权威源。
4. 外部 Zotero Desktop/已有插件仍由消费者提供；Codex 的原生 Zotero MCP 配置由宿主继承，Nix 包不提供虚假的 `zotero-mcp` 服务，不把 shell `curl` 探测当作 Codex 原生 MCP 的成功证明。

### 第 5 步：文档和对外交付

1. 更新 `README.md`：列出两个准确包名、各自包含的技能/角色/命令、Nix build/profile 的基本用法、`share/scholarworkflow/` 资源路径、Codex/OpenCode 映射方式、选择多个 roots 和 cleaner 自愿安装原则。
2. 明确运行前提：用户自行提供 Zotero Desktop、插件及 HTTP/MCP 服务；`ZOTERO_HTTP_URL` 和 `ZOTERO_MCP_URL` 在运行时覆盖；密钥、库文件、报告、缓存和日志不属于 Nix 输出。
3. 发布信息按包分别记录准确 SHA、Nix 输出引用、所完成的最小安装检查、仍需等待的具体外部服务或依赖。日常包达到条件即可供 `professor-research-core`、`professor-research-explainer`、`professor-contact` 评估接入；这不构成修改这些仓库的授权。

## 四、关键不变量、失败处理和代表性反例

| 输入或反例 | 必须保持的结果 | 处理者 |
|---|---|---|
| 用户只选择日常包 | 不出现 cleaner 技能与角色，三个日常 CLI 和完整资源存在 | Nix 两包导出与选择接口 |
| 用户只选择 cleaner | cleaner 技能与 Codex/OpenCode 角色存在，不要求整仓日常包或 `professor-research` | cleaner Nix 包 |
| 仅 `nix build`，没有进行宿主资源映射 | 只能报告包构建和资源存在；不得声称 Codex 已加载技能/角色 | README/交付记录 |
| 在仓库外启动 `zotero-paper-tagger` 或 `zotero-mcp-session` | 按固定安装位置找到对应 Python/脚本资源，不依赖 `cwd` | CLI 包装、资源根解析 |
| 在只读 store 中使用资源 | 程序运行时缓存、临时文件和导出写到可写的用户指定位置，不尝试改 store | 包装与现有脚本路径 |
| Zotero 离线或未配置 Codex 原生 MCP | 报外部前提不可用；不自动安装服务或虚构成功 | 使用者宿主 |
| 安装了 cleaner 但用户未确认 | 不能执行删除、重新挂载或改写分类 | 原 agent/skill，保持原合同 |
| 将 OpenCode 的 `permission` 字段放进 Codex TOML | 违反官方格式/含义，应在构建投影阶段拒绝，不把它当作 Codex 强制访问控制 | 投影实现 |
| Nix 下载/锁定缺失或脚本关键资源缺失 | 构建或安装检查明确失败；禁止运行时自动下载、在消费者处手工补文件 | Nix 包所有者 |

**已知不确定项与处理**：执行环境的 Nix 版本、目标平台和已存在的 Nix 资源接入工具版本，需要本地代理第 0 步记录；它们决定构建参数，不授权更改上面的产物接口。遇到确实无法按本文映射的宿主兼容问题时，暂停相应发布并将证据反馈本 PR，由方案审核者判断是否须改计划。不要临场改业务正文、追加宿主迁移或测试目标。

## 五、唯一正式测试计划（Issue #26 授权范围）

测试权威：本项目 [Test Engineer Rule](https://app.notion.com/p/rekidunois/Test-Engineer-Rule-3d80101a85f380d8a8f5ce528141e253)；本节是本议题唯一的必测清单与本地执行说明，不另外创建新的正式测试手册。只检查打包与安装本身直接改变的行为。

| 项目 | 业务目标、输入或场景 | 预期结果 | 检查入口 |
|---|---|---|---|
| T1 | 从当前 PR 的待测固定 SHA 构建 `zotero-tools` | Nix 成功生成固定输出，包含日常三技能完整目录、schema/helpers、Python 模块、三个 CLI；不含 cleaner | 对该 SHA 的 `nix build` 与输出文件检查 |
| T2 | 同一 SHA 独立构建 `zotero-collection-cleaner` | Nix 成功生成输出，仅包含对应技能及两宿主角色；无必须先安装日常包或研究仓库的要求 | `nix build` 与输出资源检查 |
| T3 | 用受支持的 Nix profile 安装两个包各自的输出，检查 Codex/OpenCode 资源 | Codex 角色是合法 TOML，仅含 `name`、`description`、`developer_instructions`；字段值分别与同一待测 SHA 的原始角色名称、描述、正文一致；OpenCode 角色与同一源角色文件逐字节一致；资源位于约定路径，可由现有宿主接入方式映射；安装不冒充运行时发现 | 检查实际 Nix 安装产物；用 Python `tomllib` 解析 Codex TOML，按既有 `test/test_apm_codex_projection.py`、`test/test_apm_opencode_projection.py` 的比较规则直接对照同一 SHA 的源文件，不用 APM 的通过结果代替 Nix 产物检查 |
| T4 | 从仓库外临时目录检查日常包三个命令入口，以及本次路径适配影响的原源码运行方式 | `zotero-paper-tagger --help` 和 `zotero-item-export --help` 从实际安装命令成功返回；`zotero-mcp-session` 通过实际安装命令调用随包提供的 `new-session.sh`，仅向获授权的隔离测试端点发初始化请求并取得测试会话标识；未设置 Nix 资源根时 `tagger.py`、`session.py` 仍能按原 `.apm/skills` 路径找到相应资源；不连接真实 Zotero、不发生业务写入或运行时拉包 | 两个已安装帮助入口；在已授权、独占的回环测试端点下检查第三个已安装入口；对本次确实改动的源码路径复用 `test/test_entrypoints.py`、`test/test_endpoint_transport.py` 的相应无副作用检查，不执行无关回归 |
| T5 | 在只读 store/隔离可写目录的安装检查环境中访问已交付资源 | 所需脚本与固定工具可从产物定位；准备或帮助检查不写入 store、不接触真实 Zotero 数据；只装日常包时没有 cleaner 的可见资源 | 只读安装输出与隔离运行目录检查 |

上述各项只使用一个足以判断的入口，不重复为每项叠加测试层；不启动真正的清理、不写标签、不用真实收藏库、不要求 Codex/OpenCode 模型调用，不建立新 judge 或证据采集平台。当前仓库已有测试可以复用未受影响的既有通过记录；只有被实现修改触及的检查才补执行。

### 本地工程师执行步骤

1. 从本 PR 的**实际远端待测 SHA** 使用 Nix 正常获取源并构建两个属性；开发预检允许在工作树定位语法错误，但正式安装证据以远端固定 SHA 为准。记录 SHA、Nix/Nixpkgs 版本、平台和使用的命令。不得从生产 repo 的工作树直接复制、可编辑安装或补丁修消费者。
2. 在仓库及其 worktree 外新建一次性 `/tmp/issue26-nix-<run-id>/`，分别设 `HOME`、`XDG_CACHE_HOME`、`XDG_STATE_HOME`、`TMPDIR` 及两个测试安装 profile 路径，使用 Nix 自带的 profile/install 入口或已经支持的项目接入方式。不要复用用户 Zotero profile、真实数据库或访问凭据。
3. 构建命令形状：`nix build "github:ScholarWorkflow/zotero-tools/<SHA>#zotero-tools" --no-link` 和相同来源的 `#zotero-collection-cleaner`；记录输出 store 路径。安装命令形状：`nix profile install --profile "<tmp>/profile-tools" "github:ScholarWorkflow/zotero-tools/<SHA>#zotero-tools"`，cleaner 使用独立 profile。需要检查宿主映射时仅沿用已支持的接入方式，不手工修改消费者结果。
4. 检查 `share/scholarworkflow` 下的实际文件和角色：以同一待测 SHA 的 `.apm/agents/zotero-collection-cleaner.agent.md` 为原始依据，解析安装的 Codex TOML 并比较三字段与对应源内容；安装的 OpenCode Markdown 与源角色文件逐字节比较。然后从仓库外调用已安装的 `zotero-paper-tagger --help`、`zotero-item-export --help`，确认 Python 包可导入、脚本可定位、固定工具可用。`zotero-mcp-session` 必须从已安装的真实命令进入 `new-session.sh`：仅在本轮确有权限使用的隔离测试端点已可用时，显式将 `ZOTERO_MCP_URL` 设为该端点完整的 `http://127.0.0.1:<独占测试端口>/mcp`，只发送初始化请求并检查测试会话标识；执行前确认地址属于本轮隔离端点，禁止使用默认真实 Zotero 地址、用户凭据或修改收藏，禁止借此新增未经批准的专用测试服务。端点或使用授权缺失时仅将 T4 该部分记为无法判断并暂停，其他检查照常完成，不以 `--help` 或路径存在冒充会话命令通过。对本次改动的源码入口，用未设置 Nix 资源根的方式复用 `test/test_entrypoints.py`、`test/test_endpoint_transport.py` 已有无副作用检查，核对旧 `.apm/skills` 路径可用；无影响部分不重复运行。
5. 权限边界参照 [skills-test-fixtures PR #43](https://github.com/RekiDunois/skills-test-fixtures/pull/43)：本次 T4 是本地命令安装检查，不要求启动 Codex、不读取或修改其全局信任配置，也不因无法证明预先信任而增加预检。若后续实际通过 Codex 宿主检查资源接入，只能在已授权的隔离消费者和既有评估服务中使用该文档对应的运行时启动方式，由运行时遵守原有审批和安全限制；不能把该文档视为访问真实 Zotero、改变信任策略或绕过权限的授权。
6. 记录 T1–T5 对应的通过、业务失败、无法判断或未执行及必要错误输出。对因 Nix 缓存、下载或外部环境导致的失败做最小诊断，现有依赖已不可用则停止受影响项，不把环境故障记为产品失败；在同一条件下不超过一次额外重试，业务断言失败不重试刷通过。
7. 临时配置、环境输出、日志与运行产物保留在上述 `/tmp` 目录，仓库中只保存必要且脱敏的简短正式测试结果。计划执行与任何更改记录更新本文；未受影响历史测试无需因 SHA 变化而一律重跑。

**测试执行状态**：T1–T5 **未执行**；没有构建通过、安装通过或模型运行通过的声明。测试第一关/第二关由获授权人员按项目规则审核，第三关须在实现后的实际版本上取得有效结果。

## 六、交接与完成条件

- 顺序：本计划提交本 PR → Plan Reviewer 审核并给出正式结论 → 同 PR 实施第 1–5 步 → 本地测试工程师按已确认的唯一计划执行 T1–T5 → 按现行合并规则审核 → 合并本 PR 时由描述中的 `Closes #26` 自动关闭 issue。
- 第 1 个包就绪即记录其独立输出，不等待 cleaner；第 2 包另记录结果，不能以某一包通过代替另一包的验证。
- 若实现中发现必须改变原角色正文、原有确认保护、正式输入/输出 schema 或宿主实际调用方式，则停下受影响改动，在本 PR 陈述具体新事实并按 Plan Reviewer Rule 重审受影响关口；未经授权不得将此扩展为业务重构或新测试关口。
- 完成时 `flake.lock` 已固定，两个包可独立构建和引用，README 给出资源位置和运行前提，原 APM 路径继续可用，T1–T5 有当前有效结果，后续实现和测试记录都属于本 PR。
