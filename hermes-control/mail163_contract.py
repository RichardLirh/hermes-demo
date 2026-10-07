"""Pure, versioned contract for user-confirmed self-mail snapshots.

The task API is the confirmation authority. This module checks its immutable
snapshot at the runtime boundary; a model cannot manufacture confirmation.
"""
import hashlib
import json
import re
import unicodedata
from uuid import UUID

SNAPSHOT_FIELDS = {'send_to', 'max_messages', 'subject', 'body', 'draft_id',
                   'version', 'content_hash', 'message_intent_id'}


def content_hash(subject, body):
    value = {'subject': subject, 'body': body, 'send_to': 'authenticated_self'}
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(',', ':')).encode('utf-8')).hexdigest()


def validate_snapshot(value):
    if not isinstance(value, dict) or set(value) != SNAPSHOT_FIELDS:
        raise ValueError('已确认邮件快照字段不完整')
    if value['send_to'] != 'authenticated_self' or type(value['max_messages']) is not int or value['max_messages'] != 1:
        raise ValueError('只允许给本人发送一封邮件')
    if type(value['version']) is not int or value['version'] < 1:
        raise ValueError('草稿版本无效')
    for key in ('draft_id', 'message_intent_id'):
        if str(UUID(value[key])) != value[key]:
            raise ValueError('草稿或发送意图标识无效')
    for key, limit in (('subject', 120), ('body', 2000)):
        text = value[key]
        if not isinstance(text, str) or not 1 <= len(text) <= limit:
            raise ValueError('邮件主题或正文长度无效')
        if text != unicodedata.normalize('NFC', text.replace('\r\n', '\n').replace('\r', '\n')).strip() or '\x00' in text:
            raise ValueError('邮件快照不是已确认的规范文本')
    if any(unicodedata.category(ch) == 'Cc' for ch in value['subject']):
        raise ValueError('主题不能含换行或控制字符')
    if value['content_hash'] != content_hash(value['subject'], value['body']):
        raise ValueError('邮件内容与确认摘要不匹配')
    return value


def intent_key(config):
    if config.get('mode') == 'send_only':
        return validate_snapshot(config['authorization'])['message_intent_id']
    return config.get('send_ledger_run_id', config['run_id'])


def receipt_matches(receipt, run_id, authorization):
    """A model-written summary or a receipt from another draft cannot finish."""
    try:
        validate_snapshot(authorization)
    except (ValueError, TypeError, KeyError, AttributeError):
        return False
    if not isinstance(receipt, dict) or receipt.get('verified') is not True:
        return False
    identity = receipt.get('recipient', '')
    return (isinstance(identity, str) and bool(re.fullmatch(r'[a-z0-9_.+-]+@163\.com', identity))
            and receipt.get('sender') == identity and receipt.get('recipient_count') == 1
            and receipt.get('run_id') == run_id
            and receipt.get('subject') == authorization['subject']
            and receipt.get('body_sha256') == hashlib.sha256(authorization['body'].encode()).hexdigest()
            and all(receipt.get(key) == authorization[key] for key in
                    ('draft_id', 'version', 'content_hash', 'message_intent_id'))
            and receipt.get('site_message') == '邮件发送成功'
            and bool(receipt.get('sent_at')))
