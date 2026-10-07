"""Durable at-most-one send intent. An uncertain click is never retried."""
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

from browser_bridge import Rejected
from mail163_contract import validate_snapshot


def utc_now():
    return datetime.now(timezone.utc).isoformat()


class SendLedger:
    def __init__(self, run_id, directory=None):
        self.run_id = str(UUID(run_id))
        root = directory or Path(__file__).resolve().parents[2]/'.local'
        self.path = Path(root)/(self.run_id+'.mail-send.json')

    def read(self):
        if not self.path.exists():
            return None
        return json.loads(self.path.read_text(encoding='utf-8'))

    def reserve(self, identity, subject, body, authorization=None, run_id=None):
        confirmation = None
        if authorization is not None:
            validate_snapshot(authorization)
            if authorization['message_intent_id'] != self.run_id or subject != authorization['subject'] or body != authorization['body']:
                raise Rejected('发送账本与已确认内容不匹配')
            confirmation = {key: authorization[key] for key in ('draft_id', 'version', 'content_hash', 'message_intent_id')}
        value = {'run_id': run_id or self.run_id, 'state':'pending', 'recipient':identity,
                 'subject':subject, 'body_sha256':hashlib.sha256(body.encode()).hexdigest(),
                 'intent_at':utc_now(), 'receipt':None, 'confirmation':confirmation}
        self.path.parent.mkdir(parents=True,exist_ok=True)
        try:
            with self.path.open('x',encoding='utf-8') as handle:
                json.dump(value,handle,ensure_ascii=False)
                handle.flush()
                os.fsync(handle.fileno())
        except FileExistsError:
            raise Rejected('本任务已有一次发送记录；结果不确定时禁止自动重发') from None
        return value

    def finish(self, state, receipt=None):
        if state not in {'sent','uncertain','rejected'}:
            raise ValueError('Invalid send state')
        value = self.read()
        if not value or value['state'] != 'pending':
            raise Rejected('发送状态已锁定，不能重写结果或重发')
        if state == 'sent' and not receipt:
            raise Rejected('缺少原站发信回执')
        if state == 'sent' and value.get('confirmation'):
            expected = {**value['confirmation'], 'run_id': value['run_id'],
                        'recipient': value['recipient'], 'sender': value['recipient'],
                        'subject': value['subject'], 'body_sha256': value['body_sha256'],
                        'recipient_count': 1, 'site_message': '邮件发送成功', 'verified': True}
            if any(receipt.get(key) != item for key, item in expected.items()) or not receipt.get('sent_at'):
                raise Rejected('原站回执与本次唯一确认不匹配')
        value.update(state=state,receipt=receipt,checked_at=utc_now())
        temporary=self.path.with_suffix('.tmp')
        with temporary.open('w',encoding='utf-8') as handle:
            json.dump(value,handle,ensure_ascii=False)
            handle.flush()
            os.fsync(handle.fileno())
        temporary.replace(self.path)
        return value
