# Browser image build status

- GitHub repository: https://github.com/RichardLirh/hermes-demo
- Source commit: 3b163eeec512586cd8208c0542f8ab1d7a4aecca
- Successful build and browser smoke run: https://github.com/RichardLirh/hermes-demo/actions/runs/37579359024
- Control unit tests: 6 passed locally and in CI.
- ACR destination: richard-agent/hermes-browser, Shenzhen personal edition.
- ACR build page: https://cr.console.aliyun.com/repository/cn-shenzhen/richard-agent/hermes-browser/build
- ACR tag demo-v1: verified in ACR, 1.115 GB, successful build 2026-10-07 14:22:03.
- ACS private pull with acr-hermes-pull Secret verified; headed Chromium login/followup smoke passed.
- ACR rule to configure: Branch main; context /; Dockerfile Dockerfile; tag demo-v1.
- Browser image remains runtime only. Windows Hermes and authenticated same-page takeover are implemented in ../hermes-control.
- Real Hermes + qwen-plus + ACS browser handoff passed on demo-hermes-browser-7zbb4, including human-side login/edit, same-session continuation, writer fencing and duplicate submission receipt followup-1. Human-side actions were automated test inputs.
- An intermediate attempt hit InsufficientBalance at 86 RMB; user replenished above ACS's 100 RMB creation threshold and the retry passed.
- Both demo SandboxSets were verified at zero replicas with no test pods, sandboxes or PVCs after cleanup.
