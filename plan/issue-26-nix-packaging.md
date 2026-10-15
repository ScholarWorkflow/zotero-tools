# Issue #26：复用 agent-env-nix 的 Zotero 独立分包计划

- Requirement revision：2026-10-15 共享层替换版 [Issue #26](https://github.com/ScholarWorkflow/zotero-tools/issues/26)。
- Plan revision：issue26-plan-v4-2026-10-15。本文件直接替换旧完整方案，是唯一执行与最小测试计划，没有并行旧版本或附加测试清单。
- Target revision：业务基线 `7c39f03f0d6010e3e4ce8e51f7fc8ba761ef58d8`；替换前计划 head `eac90a39fc2eea33075fafb8deb721d4fe6d1256`。
- Shared revision：[agent-env-nix PR #1](https://github.com/RekiDunois/agent-env-nix/pull/1)，`760c1bf60e8ec19d1985660ec5e3276a8ef80b5a`，open、未合并，属于接口候选而非已发布稳定版本。
- Proposed review status: pending。仅改需求/计划，未实现、未测试；正式审核后在本 PR 同一分支实施。
- 规则：[Project Consensus](https://app.notion.com/p/rekidunois/Project-Consensus-3d60101a85f3815a8c43f271f2b4d91d)、[Plan Reviewer Rule](https://app.notion.com/p/rekidunois/Plan-Reviewer-Rule-3e80101a85f3817a94cbc6eca1a76a5c)、[Test Engineer Rule](https://app.notion.com/p/rekidunois/Test-Engineer-Rule-3d80101a85f380d8a8f5ce528141e253)。引用不新增本计划之外的测试。

## 1. 方案、依据与边界

需求是日常工具与破坏性 cleaner 分开、完整资源、固定依赖、原有角色确认和 APM 行为保留。当前 Python tagger/session 按模块目录向上查找 `.apm/skills`，进入 Nix Python 库后不能自然成立，技能也仍使用 uv/shell/PDF 命令。因此 producer 负责固定运行包、资源根和必要 Nix 调用适配，共享层负责声明式包、组合、复制和 Codex 角色/配置保护。仅复制 SKILL.md、给所有功能一个默认大包、每仓再建安装器均不满足这一职责分离。

关键事实来源：
- [pyproject.toml](https://github.com/ScholarWorkflow/zotero-tools/blob/7c39f03f0d6010e3e4ce8e51f7fc8ba761ef58d8/pyproject.toml)：Python >=3.11、三个 console scripts；[源技能/角色](https://github.com/ScholarWorkflow/zotero-tools/tree/7c39f03f0d6010e3e4ce8e51f7fc8ba761ef58d8/.apm)；[tagger.py](https://github.com/ScholarWorkflow/zotero-tools/blob/7c39f03f0d6010e3e4ce8e51f7fc8ba761ef58d8/zotero_tools/tagger.py)、[session.py](https://github.com/ScholarWorkflow/zotero-tools/blob/7c39f03f0d6010e3e4ce8e51f7fc8ba761ef58d8/zotero_tools/session.py) 的资源定位。
- 共享 [package.nix](https://github.com/RekiDunois/agent-env-nix/blob/760c1bf60e8ec19d1985660ec5e3276a8ef80b5a/lib/package.nix) 接受完整 files、exports.skills/agents、两类依赖；[project.nix](https://github.com/RekiDunois/agent-env-nix/blob/760c1bf60e8ec19d1985660ec5e3276a8ef80b5a/lib/project.nix) 递归组合并生成 apply/remove；[README](https://github.com/RekiDunois/agent-env-nix/blob/760c1bf60e8ec19d1985660ec5e3276a8ef80b5a/README.md) 明确生成物所有权、闭包与实际复制。
- [Codex skills](https://developers.openai.com/codex/skills)、[subagents](https://developers.openai.com/codex/subagents)：技能需进入发现位置；角色为 name、description、developer_instructions 的原生 TOML。共享库不会读取 APM frontmatter 并自动理解其宿主 variants，本仓仍须准确选取描述/正文。

预期变化：新增两独立 agent 包和共享 Codex 接入；保留：原四技能、源角色、三个 CLI 业务、APM/OpenCode/uv 非 Nix 路径、运行时端点参数、cleaner 确认。禁止：默认带 cleaner、真实数据写入测试、业务/schema 重构、虚构 Zotero MCP 服务、改消费者仓库或用户信任、秘密入 store。

## 2. 唯一接口及 producer 修改点

### 2.1 包声明与选择

新增 flake.nix/flake.lock、nix/，共享 input 固定上述 SHA 与实际 nixpkgs/平台。共享仓访问使用现有 Nix/Git 认证，不将 token 写进声明。仅对实际验证平台声明可消费。

- `packages.<system>.zotero-tools`：共享 mkAgentPackage 结果，exports.skills 为 zotero-read、zotero-collections、zotero-paper-tagger；files 包含完整目录、scripts/schema 及所需附属资源；runtimePackages 引用固定 Python 应用与所需 shell/PDF 工具。无 cleaner export 或强制依赖。
- `packages.<system>.zotero-collection-cleaner`：独立 mkAgentPackage，完整 cleaner 技能，exports.agents.zotero-collection-cleaner 的 description/developer_instructions 来自同一源角色的既有 Codex variant；共享层生成 name/TOML。不另写 Codex 序列化器，不把 OpenCode permission/hidden/question 当权限字段。
- 两包 producer 参数暴露 `enableHarnesses ? [ "codex" ]`，透传共享库，可 `.override { enableHarnesses = []; }`。Nix 新路径只实现 Codex；APM 的既有 OpenCode 原角色/转换保留，不再在 Nix 输出或 Nix 测试新增 OpenCode 产物。
- `agentDependencies` 仅放真实依赖的 mkAgentPackage 结果；cleaner 只有实际复用日常 endpoint helper 时才依赖日常包，不能因输入来自 professor-collection-preparer 就依赖研究包。runtimePackages 只保留普通 derivation 闭包，不遍历其技能、不自动给 PATH/bin。

共享产物使用 `$out/payload`、`$out/codex/agents`、agent-env.json 和 passthru.agentEnv，不再定义旧 share/scholarworkflow 中间协议。files 用安全不重叠相对路径映射完整资源，exports.skills 指向其目录。

### 2.2 必须保留的本仓 runtime 工作

1. 固定 Python >=3.11 应用，安装全部 zotero_tools 模块及三个真实 console scripts。为 tagger/session 增加显式 Nix 资源根，未设置时保留原源码树/APM 定位，不依赖 cwd。
2. 共享 mkAgentPackage 本身不产出 `$out/bin`。本仓保持原三 CLI 作为 zotero-tools 包的可安装 bin：用 producer 专属 derivation 包装追加指向固定 runtime 的 bin 链接，并保留 mkAgentPackage 的完整输出与 passthru.agentEnv（例如对结果作局部 overrideAttrs）。不能只放 runtimePackages 就声称 profile 安装后已有 CLI；不在共享层添加通用 CLI 安装器。
3. 固定资源树与 runtime 构建关系须无循环：先从源构建 Nix 资源副本，再以该副本构建 Python/wrappers，最后 agent 包引用相同资源及 runtime。wrapper 的资源根指向实际脚本根而非未定义 share 路径。
4. 完整交付 zotero-read 的 new-session.sh、zotero_item_export.py、item_export_core.py，以及 tagger helpers 和 CORRESPONDENCE_SCHEMA.md。仅 Nix 副本/包装将 uv 动态执行改成固定解释器；保留源技能 `<skill_dir>` 找相对 helper 的含义及原 uv 用法。
5. 对真正执行技能的入口提供 bash、curl、grep、awk、tr、mktemp、pdftotext 等实际使用工具；保留 fitz 备用路径则提供固定 PyMuPDF。使用 producer wrapper/固定命令或 Nix 变体指令，不仅给 CLI 设置 PATH 却遗漏技能 shell 命令。
6. 保留 ZOTERO_HTTP_URL、ZOTERO_MCP_URL、ZOTERO_STORAGE_ROOT 运行时覆盖；导出、缓存、日志使用可写工作/程序根/显式目录。Zotero Desktop/插件/HTTP 与 Codex 原生 MCP 为外部前提，两包 mcp 默认空，不注册假的 Zotero server。
7. cleaner 描述及完整业务正文保持既有 plan→询问→执行、Tier-1/Tier-2、串行失败即停、映射文件保护和取消/部分完成语义；安装本身不运行 cleaner。

## 3. 共享接入及生命周期

消费者调用共享 `lib.mkProject { inherit pkgs; roots = [ ... ]; }`，构建环境后显式运行 `bin/agent-env apply --project <project>`。本仓只给可复用例子，不写本仓 installer/consumer-view。构建和 profile CLI 安装均不等于技能已发现；apply 生成实际 `.agents/skills/<name>` 文件和 `.codex/agents/<name>.toml`，Codex 是否信任由宿主既有配置决定。

共同职责全部复用共享层：递归依赖、同一包身份去重、导出碰撞拒绝、完整复制、原生 TOML、相关配置层检测、保活 GC roots、apply/remove。不同包同名 export 即使内容相同仍拒绝；项目已有等价未管理资源则复用不认领。不能用“所有等价来源都合并”替代这一真实合同。

已管理技能目录为生成物，用户应改源仓库；升级/移除允许整树替换/删除。其他来源技能不动。已管理 agent/config 若与上次生成值不同则保留并报告；其他配置/未知字段保留。共享 apply 不写全局配置、不改信任，无法读取的 managed/cloud/MDM 或后续会话覆盖不在保证内；不承诺整个项目原子性。冲突停止相应接入，不静默覆盖，不在本仓建设第二套保护实现。

## 4. 实施顺序和完成边界

1. 正式审核本完整计划；确认 producer/shared 精确 SHA、Nix/平台和直接调用。共享接口更新需分析影响再改锁，不能直接追浮动主分支。
2. 实现共享 flake 引用及两包声明；先完成日常固定资源/runtime/CLI，保留 default 不含 cleaner。
3. 完成 cleaner 独立声明及源角色到 description/body 的最小适配；不重造共享 TOML 投影或碰撞检测。
4. README 记录 build/profile CLI 与共享 mkProject/apply 的区别、两个包的资源/CLI、Codex-only override、APM 兼容、可写目录、外部 Zotero 前提与可引用 SHA。
5. 同 PR 按以下唯一最小清单记录结果。日常包先就绪可供 professor-research-core/explainer/contact 接入，cleaner 不阻塞；不修改消费者。两包完整后按现行合并审核，合并 Closes #26 关闭 issue。

## 5. 唯一最小测试计划

当前全部未执行，正式步骤/结果依 Test Engineer Rule 审核。只改现有 T1–T5 的接口和 Nix 宿主范围，不新增通用库测试或业务认证。

| 项 | 输入/场景 | 预期及唯一检查入口 |
|---|---|---|
| T1 日常构建 | 固定远端 producer SHA 的 zotero-tools | nix build 成功；三完整技能/schema/helpers、Python 模块、三个可安装 CLI 存在；不含 cleaner |
| T2 独立 cleaner | 同 SHA 的 cleaner 输出 | 独立构建，技能与 Codex 角色完整；没有无依据的日常/研究强制依赖 |
| T3 共享正式接入与角色 | 仓库外隔离消费者，分别以两包为 roots，通过共享 mkProject/apply | 两包各自资源可发现位置正确；Codex TOML 三字段与同一 SHA 的源角色既有 Codex 描述/正文一致；用现有 test_apm_codex_projection.py 对应比较规则及 tomllib 检查实际 Nix 产物。不另测 OpenCode Nix 产物或共享通用复制/配置算法 |
| T4 三命令与源码兼容 | profile 安装真实包，从仓库外运行；本次触及的源码路径 | tagger --help、item-export --help 成功；mcp-session 从实际 CLI 经随包 new-session.sh，仅向获授权隔离回环 endpoint 初始化并取得会话标识。无 Nix 资源根时旧源码定位保留；只复用 test_entrypoints.py/test_endpoint_transport.py 受影响检查 |
| T5 固定工具与状态 | 已安装资源、只读 store、隔离可写目录 | 固定脚本与实际工具可用，准备/帮助不写 store、不触真实 Zotero；日常单独选择没有 cleaner。与 T1/T3/T4 的已有观察合并记录，不增加第二套检查 |

准备：使用实际远端 producer SHA 与锁定共享 SHA，经正式 nix build/profile install；在仓库和 worktree 外 `/tmp/issue26-nix-<run-id>` 设置独占 HOME/XDG_CACHE_HOME/XDG_STATE_HOME/TMPDIR 和安装 profiles，通过 README 的共享组合/apply 示例准备消费者。不能手工复制源文件、editable install、临时软链或消费者补丁冒充安装。

执行工程师在本文件补齐实现后的准确命令与 runtime/resource 路径；T4 的 ZOTERO_MCP_URL 必须是本轮获授权独占 `http://127.0.0.1:<port>/mcp`，不用默认真实服务/凭据，不发写入/删除。隔离端点或授权缺失时该部分无法判断，其他项继续，不能用 help 或文件存在替代 session 入口成功，也不新增未经批准测试服务。

[skills-test-fixtures PR #43](https://github.com/RekiDunois/skills-test-fixtures/pull/43) 仅约束实际需要的隔离配置/权限；不成为新预检/宿主认证，T4 不要求启动 Codex 或读取/修改其全局信任。若确实使用 Codex，只用已授权消费者与既有运行方式，不绕过原审批。

最小诊断环境故障，同条件最多一次额外重试；断言失败不重试刷通过。临时结果留隔离目录，只在本文件记简短脱敏结果；未受影响旧有效结果可复用。不跑真实 cleaner、标签写入、真实库、模型认证或 judge，不新建证据采集平台。源 APM/OpenCode/uv 未受影响不重复验证。

## 6. 当前状态

v4 已用共享 mkAgentPackage/mkProject 替换旧 share 布局和每仓接入说明，保留包特有 Python/CLI/资源与角色适配。计划审核、测试审核仍 pending；没有实现或测试通过结论。完成条件是两独立可固定包、共享接入、三个 CLI 和源兼容有效、角色正文保持、外部前提如实记录及 T1–T5 最小结果齐备。
