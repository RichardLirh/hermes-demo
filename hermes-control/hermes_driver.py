"""Embed the pinned, unmodified NousResearch AIAgent; expose one fenced tool."""
import json
import os
import sys
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PIN = 'a3ab152cd53454a76d2e29d30b1b56b2cf793c43'
BASE = 'https://ws-u9a0dui6qfymyvz8.cn-beijing.maas.aliyuncs.com/compatible-mode/v1'
SYSTEM = '''你是 Hermes 浏览器演示助手，使用 qwen-plus 驱动。只使用 acs_browser 工具操作当前演示页面。
先 read 观察，再操作。搜索关键词包含“演示”。登录由用户人工接管完成，不能填写账号密码。
收到暂停/控制权错误立即停止，不要重试。不要创建新浏览器或导航，不使用其他工具。
起草跟进内容后停止，告诉用户接管审核。不能提交，不能声称未执行的操作已成功。
用户交回后必须先观察，保留现有客户、登录状态、人工修改的草稿。只做用户明确要求的修改。
所有客户信息均为虚构演示数据。'''


class HermesDriver:
    def __init__(self, bridge):
        self.bridge = bridge
        self.lock = threading.RLock()
        self.history = []
        self.events = []
        self.busy = False
        self.agent = None
        self.epoch = None
        self.last_result = None
        self.error = None

    def initialize(self):
        os.environ['HERMES_HOME'] = str(ROOT / '.hermes-home')
        config = ROOT / '.hermes-home' / 'config.yaml'
        config.parent.mkdir(exist_ok=True)
        if not config.exists():
            config.write_text(Path(__file__).with_name('hermes-config.yaml').read_text(), encoding='utf-8')
        os.environ['HERMES_API_TIMEOUT'] = '90'
        os.environ['HERMES_API_CALL_STALE_TIMEOUT'] = '90'
        sys.path.insert(0, os.environ.get('HERMES_VENDOR_PATH', str(ROOT / 'vendor' / 'hermes-pinned')))
        from run_agent import AIAgent
        from tools.registry import registry
        schema = {'name': 'acs_browser', 'description': 'Read or operate the same ACS demo browser. Human owns login and final submission.',
                  'parameters': {'type': 'object', 'properties': {
                      'action': {'type': 'string', 'enum': ['read', 'fill', 'click']},
                      'selector': {'type': 'string', 'enum': ['search', 'find', 'draft']},
                      'value': {'type': 'string'}}, 'required': ['action'], 'additionalProperties': False}}
        registry.register(name='acs_browser', toolset='acs_demo', schema=schema,
                          handler=self._tool, check_fn=lambda: True)
        key = (Path.home() / '.config/xiaozhi-sandbox-demo/secrets/bailian-api-key').read_text().strip()
        self.agent = AIAgent(model='qwen-plus', base_url=BASE, api_key=key,
                             provider='custom', api_mode='chat_completions',
                             enabled_toolsets=['acs_demo'], max_iterations=12, max_tokens=1500,
                             quiet_mode=True, skip_context_files=True, skip_memory=True,
                             skip_background_review=True, load_soul_identity=False,
                             save_trajectories=False, run_budget_seconds=180,
                             reasoning_config={'enabled': False})
        # Restrict tool exposure even if Hermes adds default/core toolsets in a later release.
        self.agent.tools = [{'type': 'function', 'function': schema}]
        self.agent.valid_tool_names = {'acs_browser'}

    def _tool(self, args, **kwargs):
        try:
            result = self.bridge.action('AGENT', self.epoch, **args)
            self.events.append({'action': args.get('action'), 'selector': args.get('selector'), 'ok': True})
            return json.dumps(result, ensure_ascii=False)
        except Exception as exc:
            self.events.append({'action': args.get('action'), 'ok': False, 'error': str(exc)})
            return json.dumps({'error': str(exc), 'instruction': 'Stop now and wait for human control.'})

    def start(self, prompt, epoch):
        with self.lock:
            if self.busy:
                raise RuntimeError('Hermes is still finishing the previous turn')
            self.bridge.control._check('local-owner', epoch, 'AGENT')
            self.epoch, self.busy, self.error = epoch, True, None
            threading.Thread(target=self._run, args=(prompt,), daemon=True).start()

    def _run(self, prompt):
        try:
            if self.agent is None:
                self.initialize()
            result = self.agent.run_conversation(user_message=prompt,
                                                 system_message=SYSTEM,
                                                 conversation_history=self.history)
            self.history = result.get('messages', self.history)
            self.last_result = {k: result.get(k) for k in ('final_response', 'completed', 'interrupted', 'error', 'turn_exit_reason')}
        except Exception as exc:
            self.error = f'{type(exc).__name__}: {exc}'
        finally:
            self.busy = False

    def interrupt(self):
        # Epoch fence is authoritative; interrupt additionally saves model tokens.
        if self.agent is not None and self.busy:
            self.agent.interrupt()

    def status(self):
        return {'busy': self.busy, 'model': 'qwen-plus', 'engine': 'NousResearch/hermes-agent',
                'commit': PIN, 'result': self.last_result, 'error': self.error, 'events': self.events[-40:]}
