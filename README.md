# Hermes browser sandbox demo

Personal ACS browser runtime. The image contains headed Chromium, Playwright 1.63.0,
a fictional CRM, and optional password-protected noVNC. Hermes/model configuration
stays on the client; this image does not install Hermes Agent.

## ACR personal edition
- GitHub source: RichardLirh/hermes-demo
- Branch: main
- Build context: /
- Dockerfile: Dockerfile
- Image tag: demo-v1
- Repository: richard-agent/hermes-browser (Shenzhen, private)
- Enable overseas build if the domestic builder cannot fetch Microsoft/PyPI/Ubuntu dependencies.
- Keep build cache enabled. No registry or model credentials are build arguments.

GitHub Actions builds and tests the container. It does not push to ACR.
ACR's linked build rule builds and stores the image in your existing private repository.
A successful GitHub test does not prove the ACR tag exists.

## Runtime
Default ports bind to loopback inside the container:
- 9222: Chromium CDP
- 8765: fictional CRM (demo / demo-password)
- 5900 and 6080: optional VNC/noVNC, only when VNC_PASSWORD is supplied at runtime

VNC passwords should be random; legacy VNC uses only the first 8 characters.
Do not publish these ports directly on a public IP. Use an authenticated tunnel/gateway.
NoVNC and raw CDP do not enforce the SessionControl handoff fence. The supplied
control.py is a tested primitive; integration with a sole authenticated browser
adapter remains a separate step. Auto-wake is a Sandbox template setting, not
an image setting.

The Playwright runtime uses its default Chromium sandbox configuration and is
intended for the trusted fictional demo only, not arbitrary untrusted browsing.
No privileged container mode is required.

## Verify
```sh
python -m unittest discover -s browser-runtime -p 'test_*.py' -v
docker build -t hermes-browser:demo-v1 .
docker run -d --name browser-smoke --shm-size=512m hermes-browser:demo-v1
docker exec browser-smoke python smoke_browser.py
docker logs browser-smoke
docker rm -f browser-smoke
```

The smoke test performs login and an idempotent submission against fictional,
in-memory data. It saves a screenshot inside the container. These records are lost
on release; export needed artifacts before deleting a sandbox.

ACS agent-runtime injection and SandboxSet deployment are configured separately.
This repository alone does not complete Hermes model integration, public gateway
routing, or same-session agent/human takeover acceptance.

Never commit API keys, registry passwords, kubeconfigs, or private Obsidian notes.
