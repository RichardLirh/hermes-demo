"""Actual Hermes + Qwen tool-call test; intentionally NO cloud/browser mutation."""
import json
from pathlib import Path
from hermes_driver import HermesDriver, PIN


class Probe:
    def action(self, actor, epoch, **args):
        return {'probe': True, 'received': args, 'note': 'Local protocol test only; no browser or cloud operation'}


if __name__ == '__main__':
    driver = HermesDriver(Probe())
    driver.initialize()
    driver.epoch = 1
    result = driver.agent.run_conversation(
        user_message='Call acs_browser with action read exactly once, then say PROTOCOL_OK. This is a local protocol test.',
        system_message='Use the provided acs_browser tool once. Do not use other tools.')
    assert len(driver.events) == 1 and driver.events[0]['ok'] and driver.events[0]['action'] == 'read'
    assert result.get('completed')
    report = {'engine': 'NousResearch/hermes-agent', 'commit': PIN, 'model': 'qwen-plus',
              'scope': 'Real model and Hermes, local probe adapter; NOT cloud browser verification',
              'events': driver.events, 'completed': result.get('completed'), 'response': result.get('final_response')}
    Path(__file__).resolve().parents[1].joinpath('hermes-protocol-verification.json').write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False))
