# Hermes 模型驱动与人工接管

Windows 主机运行 NousResearch/hermes-agent 的真实 `AIAgent`，百炼 `qwen-plus` 生成工具调用；唯一浏览器适配器通过本机 kubectl 隧道连接 ACS 内现有 Chromium 页面。人工界面也通过同一适配器操作，登录、客户选择和草稿保留在同一会话中。

## 当前验收状态（2026-10-07）

- 已完成：Python 3.14.8 环境、Hermes 官方源码与依赖、百炼模型真实调用、自定义工具调用协议。
- 已完成：ACS 实例 `demo-hermes-browser-gl8f9` 的本机接管界面、远程画面、搜索、人工侧登录、修改草稿；测试后已释放。
- 已通过：控制权、旧 epoch 拒绝、等待在途操作、审批过期/草稿变化、重复提交、未知结果不重放等 6 项测试。
- 已通过真实 Hermes 两轮操作与 ACS 浏览器贯通验收：`demo-hermes-browser-7zbb4`，模型起草 → 人工侧登录与改稿 → 交回模型保留原文并追加 → 人工确认提交，回执 `followup-1`；重复提交返回同一回执。人工侧由验收脚本模拟，用户亲自接管体验尚未进行。
- 首轮发现 Hermes 默认工具搜索与 Qwen 工具调用不兼容。关闭 `tools.tool_search` 后，真实 Hermes + qwen-plus 的 `acs_browser(action=read)` 本机协议测试成功（回执 `PROTOCOL_OK`）。该协议测试使用本机测试适配器，不能当作云端浏览器验收。
- 中途实例 `demo-hermes-browser-7zzn7` 因 `InsufficientBalance` 无法调度，已释放。用户补充余额超过 100 元后，后续实例成功完成上述验收。
- 接管页面已实际打开，显示登录状态、人工原稿及模型追加内容、提交回执。已通过页面“结束演示并释放沙箱”触发清理。

## 本机启动

在 PowerShell 执行：

```powershell
& 'D:\workspace\personal\xiaozhi-sandbox-lab\hermes-control\Start-HermesDemo.ps1'
```

启动器更新临时 kubeconfig，创建一个沙箱并打开本机控制页。Hermes 在 Windows 运行，浏览器在 ACS 运行。本实现使用已验证的 Kubernetes 隧道；它不是公网 E2B 浏览器链路的验收。公网 IP 临时方案保留用于先前 SDK 测试，域名与 HTTPS 仍属后续补充。

模型密钥只从本机 `~/.config/xiaozhi-sandbox-demo/secrets/bailian-api-key` 读取，不进入镜像或 GitHub。控制页面只监听 `127.0.0.1:18765`，启动链接使用一次会话令牌换取 HttpOnly Cookie；CDP 隧道仅监听本机 `19222`。不要分享启动链接。

## 操作顺序

1. 点击“交给 Hermes 执行”：让模型搜索演示客户并起草，不能登录或提交。
2. 点击“人工接管”：待确认后，Agent 旧操作被拒绝。右侧输入 `demo / demo-password` 登录演示系统，修改草稿并点击“把修改写入浏览器”。右侧操作会作用于左侧截图里的同一页面。
3. 修改任务，例如“保留人工草稿，末尾追加一句下次联系安排”，再点击“交给 Hermes 执行”。
4. 再接管，审核草稿后点击“审核并提交这份草稿”。提交前确认内容，页面返回记录编号。此处只连接虚构客户演示系统。
5. 点击“结束演示并释放沙箱”。正常退出时缩容为 0 并验证实例删除；启动 30 分钟后自动执行同样清理。强制结束 Windows 进程会绕过 finally，应另行检查云端副本数。

这是用于固定演示网页的接管界面，不是任意网站的通用远程桌面。保留自动唤醒模板配置，但本轮不声称完成暂停/唤醒验收。

## 安装与固定版本

- Hermes 上游提交：`a3ab152cd53454a76d2e29d30b1b56b2cf793c43`
- 官方源码：https://github.com/NousResearch/hermes-agent/tree/a3ab152cd53454a76d2e29d30b1b56b2cf793c43
- 解压目录：实验目录的 `vendor/hermes-pinned`，保持上游文件不修改。
- 官方归档：`https://codeload.github.com/NousResearch/hermes-agent/legacy.tar.gz/a3ab152cd53454a76d2e29d30b1b56b2cf793c43`
- 本次归档 SHA-256：`f98b2d6beaa9765e2428cda20975594546f875f6a732f9ac92d4d89b02bfc0c3`
- Python 环境：实验目录 `.hermes-venv`，Python 3.14.8；完整依赖固定在 `requirements.lock.txt`。
- 首次启动会把 `hermes-config.yaml` 复制到隔离的 `.hermes-home/config.yaml`，不修改用户其他 Hermes 配置。
- 模型：`qwen-plus`，工作空间 OpenAI 兼容地址在配置文件内。

## 重复验收命令

先启动演示，再执行：

```powershell
& 'D:\workspace\personal\xiaozhi-sandbox-lab\.hermes-venv\Scripts\python.exe' 'D:\workspace\personal\xiaozhi-sandbox-lab\hermes-control\verify_demo.py'
```

该脚本真实调用 Hermes 和模型，自动模拟人工侧登录与修改，验证同一 browserSessionId、旧控制指令拒绝、交回后的登录与草稿保留、提交回执幂等。自动化结果不能替代用户本人接管验收。通过后生成 `hermes-model-handoff-verification.json`；未通过不会写成功报告。

完整验收后仍须点击页面“结束演示并释放沙箱”，检查两个 SandboxSet 均为 0，且无测试 Pod/Sandbox/PVC。

### 余额门槛说明

用户核对现金余额约 86 元。ACS 官方使用限制要求账户余额与代金券总值不小于 100 元才可创建按量资源；因此事件并不代表现金已耗尽。无额外可用代金券时需补足门槛后再试。来源：https://help.aliyun.com/zh/cs/product-overview/restrictions-on-use
