# MewCode 第二章任务拆解：常驻式 Textual Agent 界面

## 任务 1：初始化 Python 项目骨架
- 目标：建立可安装、可运行、可测试的 Python 项目基础。
- 影响文件：`pyproject.toml`、`README.md`、`src/mewcode/__init__.py`、`src/mewcode/__main__.py`、`tests/`
- 依赖任务：无
- 参考资料定位：`spec.md` 的「阶段目标」「设计骨架」

## 任务 2：定义用户目录配置格式与加载流程
- 目标：支持从用户目录读取 YAML 配置，并校验 `protocol`、`model`、`base_url`、`api_key` 四个核心字段，同时允许可选扩展字段。
- 影响文件：`src/mewcode/config.py`、`tests/test_config.py`
- 依赖任务：任务 1
- 参考资料定位：`checklist.md` 的「配置文件验收」

## 任务 3：设计 Provider 统一接口
- 目标：抽象统一的流式对话接口，让交互界面不直接依赖 Claude 或 OpenAI 的协议细节。
- 影响文件：`src/mewcode/providers/base.py`、`src/mewcode/providers/__init__.py`、`tests/test_provider_factory.py`
- 依赖任务：任务 1、任务 2
- 参考资料定位：`spec.md` 的「Provider 抽象层」「Provider 实现层」

## 任务 4：实现 Provider 工厂与协议选择
- 目标：根据配置中的 `protocol` 选择对应 Provider，并为未知协议提供可观测错误。
- 影响文件：`src/mewcode/providers/factory.py`、`tests/test_provider_factory.py`
- 依赖任务：任务 2、任务 3
- 参考资料定位：`checklist.md` 的「Provider 切换验收」

## 任务 5：实现 Anthropic Claude 流式后端
- 目标：适配 Claude 消息接口，通过 SSE 解析流式响应并输出统一文本增量。
- 影响文件：`src/mewcode/providers/anthropic.py`、`src/mewcode/providers/sse.py`、`tests/test_providers_streaming.py`
- 依赖任务：任务 3、任务 4
- 参考资料定位：Anthropic Messages API 文档、Anthropic streaming 文档、`checklist.md` 的「Claude 验收」

## 任务 6：实现 Claude extended thinking 配置支持
- 目标：当配置开启 thinking 时，Claude 请求携带对应能力；普通聊天输出默认只展示最终回答文本。
- 影响文件：`src/mewcode/providers/anthropic.py`、`src/mewcode/config.py`、`tests/test_providers_streaming.py`
- 依赖任务：任务 5
- 参考资料定位：Anthropic extended thinking 文档、`checklist.md` 的「Claude thinking 验收」

## 任务 7：实现 OpenAI 流式后端
- 目标：适配 OpenAI 对话协议，通过 SSE 解析流式响应并输出统一文本增量。
- 影响文件：`src/mewcode/providers/openai.py`、`src/mewcode/providers/sse.py`、`tests/test_providers_streaming.py`
- 依赖任务：任务 3、任务 4
- 参考资料定位：OpenAI streaming 文档、`checklist.md` 的「OpenAI 验收」

## 任务 8：实现进程内会话历史
- 目标：保存当前运行期间的用户消息与 AI 回复，并在后续请求中带上历史上下文。
- 影响文件：`src/mewcode/session.py`、`tests/test_session.py`
- 依赖任务：任务 3
- 参考资料定位：`spec.md` 的「会话层」、`checklist.md` 的「多轮对话验收」

## 任务 9：引入 Textual 常驻式终端界面
- 目标：使用 Textual 替代普通 REPL，建立常驻式全屏终端界面。
- 影响文件：`pyproject.toml`、`src/mewcode/repl.py`、`tests/test_repl.py`
- 依赖任务：任务 1、任务 8
- 参考资料定位：`spec.md` 的「Textual 交互层」、`checklist.md` 的「Textual 界面验收」

## 任务 10：实现 Agent 风格视觉布局
- 目标：实现黑色背景、红色 block ASCII logo、顶部模型信息、分隔线、对话区、底部固定输入框和底部模式提示。
- 影响文件：`src/mewcode/repl.py`、`tests/test_repl.py`
- 依赖任务：任务 9
- 参考资料定位：`checklist.md` 的「视觉验收」「底部模式提示验收」

## 任务 11：实现对话消息与状态表现
- 目标：用户消息使用蓝色 `>` 标识，AI 回复使用紫色圆点标识，当前处理的用户消息灰色高亮，AI 处理状态显示 Thinking、Coding、Done 和动态 spinner。
- 影响文件：`src/mewcode/repl.py`、`tests/test_repl.py`
- 依赖任务：任务 9、任务 10
- 参考资料定位：`checklist.md` 的「对话区域验收」「状态验收」

## 任务 12：接入真实 LLM 流式回复
- 目标：用户提交输入后调用真实 Provider 流式接口，而不是 mock 回复；将流式增量更新到 Textual 对话区，并在完成后写入会话历史。
- 影响文件：`src/mewcode/repl.py`、`tests/test_repl.py`
- 依赖任务：任务 3 至任务 11
- 参考资料定位：`spec.md` 的「Provider 抽象层」「Textual 交互层」、`checklist.md` 的「真实 LLM 验收」

## 任务 13：补齐错误处理与中断行为
- 目标：覆盖配置缺失、字段缺失、协议不支持、认证失败、网络失败、流中断、Esc 中断等基础错误场景，避免 Python traceback 直接暴露给用户。
- 影响文件：`src/mewcode/config.py`、`src/mewcode/providers/*.py`、`src/mewcode/repl.py`、`tests/`
- 依赖任务：任务 2、任务 4、任务 5、任务 7、任务 12
- 参考资料定位：`checklist.md` 的「错误处理验收」「中断验收」

## 任务 14：接入主流程
- 目标：把命令行入口、配置加载、Provider 工厂、会话历史和 Textual 常驻界面串成 `mewcode` 启动流程。
- 影响文件：`pyproject.toml`、`src/mewcode/__main__.py`、`src/mewcode/cli.py`、`tests/test_cli.py`
- 依赖任务：任务 1 至任务 13
- 参考资料定位：`spec.md` 的「设计骨架」、`checklist.md` 的「启动命令验收」

## 任务 15：端到端验证
- 目标：使用真实或可替代的测试配置，从启动命令到 Textual 界面、多轮对话、流式输出、Provider 切换和退出行为完成验收。
- 影响文件：`checklist.md`、`tests/`、必要时补充 `README.md`
- 依赖任务：任务 14
- 参考资料定位：`checklist.md` 的「端到端验收」
