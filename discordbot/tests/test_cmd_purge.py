import ast
import asyncio

class DummyDiscord:
    class Message: ...
    class TextChannel: ...
    class Thread: ...
    class StageChannel: ...
    class VoiceChannel: ...
    class NotFound(Exception):
        pass

def _load_cmd_purge():
    with open('discordbot/bot.py', 'r', encoding='utf-8') as f:
        source = f.read()
    module = ast.parse(source)
    func_node = None
    for node in module.body:
        if isinstance(node, ast.AsyncFunctionDef) and node.name == 'cmd_purge':
            func_node = node
            break
    if func_node is None:
        raise RuntimeError('cmd_purge not found')
    ns = {
        'discord': DummyDiscord,
        'parse_message_link': lambda link: None,
        '_purge_count': None,
        'MESSAGE_CHANNEL_TYPES': (object,),
    }
    exec(compile(ast.Module(body=[func_node], type_ignores=[]), filename='cmd_purge', mode='exec'), ns)
    return ns['cmd_purge'], ns

class DummyMessage:
    def __init__(self, guild=None):
        self.guild = guild
        self.replies = []
    async def reply(self, text, **kw):
        self.replies.append(text)

class DummyGuild:
    def __init__(self, id=1):
        self.id = id
        self.me = object()


def test_cmd_purge_requires_guild():
    cmd_purge, _ = _load_cmd_purge()
    msg = DummyMessage(guild=None)
    asyncio.run(cmd_purge(msg, '100'))
    assert msg.replies == ['サーバー内でのみ使用できます。']

def test_cmd_purge_requires_arg():
    cmd_purge, _ = _load_cmd_purge()
    msg = DummyMessage(guild=DummyGuild())
    asyncio.run(cmd_purge(msg, ''))
    assert msg.replies == ['`y!purge <数|リンク>` の形式で指定してね！']

def test_cmd_purge_count_path():
    cmd_purge, ns = _load_cmd_purge()
    called = []
    async def fake_purge_count(msg, limit, user_ids):
        called.append((msg, limit, user_ids))
    ns['_purge_count'] = fake_purge_count
    msg = DummyMessage(guild=DummyGuild())
    asyncio.run(cmd_purge(msg, '5'))
    assert called == [(msg, 5, [])]
    assert msg.replies == []
