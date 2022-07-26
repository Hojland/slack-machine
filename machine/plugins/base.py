from datetime import datetime
from typing import Dict, Any, Optional, Union, List

from blinker import signal
from slack_sdk.models.attachments import Attachment
from slack_sdk.models.blocks import Block

from machine.clients.slack import SlackClient
from machine.models import Channel
from machine.models import User
from machine.storage import PluginStorage
from machine.utils.collections import CaseInsensitiveDict


class MachineBasePlugin:
    """Base class for all Slack Machine plugins

    The purpose of this class is two-fold:

    1. It acts as a marker-class so Slack Machine can recognize plugins as such
    2. It provides a lot of common functionality and convenience methods for plugins to
       interact with channels and users

    :var settings: Slack Machine settings object that contains all settings that
        were defined through ``local_settings.py`` Plugin developers can use any
        settings that are defined by the user, and ask users to add new settings
        specifically for their plugin.
    """

    def __init__(self, client: SlackClient, settings: CaseInsensitiveDict, storage: PluginStorage):
        self._client = client
        self.storage = storage
        self.settings = settings
        self._fq_name = f"{self.__module__}.{self.__class__.__name__}"

    def init(self):
        """Initialize plugin

        This method can be implemented by concrete plugin classes. It will be called **once**
        for each plugin, when that plugin is first loaded. You can refer to settings via
        ``self.settings``, and access storage through ``self.storage``, but the Slack client has
        not been initialized yet, so you cannot send or process messages during initialization.

        :return: None
        """
        pass

    @property
    def users(self) -> Dict[str, User]:
        """Dictionary of all users in the Slack workspace

        :return: a dictionary of all users in the Slack workspace, where the key is the user id and
            the value is a :py:class:`~machine.models.user.User` object
        """
        return self._client.users

    @property
    def channels(self) -> Dict[str, Channel]:
        """List of all channels in the Slack workspace

        This is a list of all channels in the Slack workspace that the bot is aware of. This
        includes all public channels, all private channels the bot is a member of and all DM
        channels the bot is a member of.

        :return: a list of all channels in the Slack workspace, where each channel is a
            :py:class:`~machine.models.channel.Channel` object
        """
        return self._client.channels

    def find_channel_by_name(self, channel_name: str) -> Optional[Channel]:
        """Find a channel by its name, irrespective of a preceding pound symbol. This does not
        include DMs.

        :param channel_name: The name of the channel to retrieve.
        :return: The channel if found, None otherwise.
        """
        if channel_name.startswith("#"):
            channel_name = channel_name[1:]
        for c in self.channels.values():
            if c.name_normalized and channel_name.lower() == c.name_normalized.lower():
                return c

    @property
    def bot_info(self) -> Dict[str, str]:
        """Information about the bot user in Slack

        This will return a dictionary with information about the bot user in Slack that represents
        Slack Machine

        :return: Bot user
        """
        return self._client.bot_info

    def at(self, user: User) -> str:
        """Create a mention of the provided user

        Create a mention of the provided user in the form of ``<@[user_id]>``. This method is
        convenient when you want to include mentions in your message. This method does not send
        a message, but should be used together with methods like
        :py:meth:`~machine.plugins.base.MachineBasePlugin.say`

        :param user: user your want to mention
        :return: user mention
        """
        return user.fmt_mention()

    def say(
        self,
        channel: Union[Channel, str],
        text: str,
        attachments: Union[List[Attachment], List[Dict[str, Any]], None] = None,
        blocks: Union[List[Block], List[Dict[str, Any]], None] = None,
        thread_ts: Optional[str] = None,
        ephemeral_user: Union[User, str, None] = None,
        **kwargs,
    ):
        """Send a message to a channel

        Send a message to a channel using the WebAPI. Allows for rich formatting using
        `blocks`_ and/or `attachments`_. You can provide blocks and attachments as Python dicts or
        you can use the `convenient classes`_ that the underlying slack client provides.
        Can also reply in-thread and send ephemeral messages, visible to only one user.
        Ephemeral messages and threaded messages are mutually exclusive, and ``ephemeral_user``
        takes precedence over ``thread_ts``
        Any extra kwargs you provide, will be passed on directly to the `chat.postMessage`_ or
        `chat.postEphemeral`_ request.

        .. _attachments: https://api.slack.com/docs/message-attachments
        .. _blocks: https://api.slack.com/reference/block-kit/blocks
        .. _convenient classes:
            https://github.com/slackapi/python-slackclient/tree/master/slack/web/classes

        :param channel: :py:class:`~machine.models.channel.Channel` object or id of channel to send
            message to. Can be public or private (group) channel, or DM channel.
        :param text: message text
        :param attachments: optional attachments (see `attachments`_)
        :param blocks: optional blocks (see `blocks`_)
        :param thread_ts: optional timestamp of thread, to send a message in that thread
        :param ephemeral_user: optional user name or id if the message needs to visible
            to a specific user only
        :return: Dictionary deserialized from `chat.postMessage`_ request, or `chat.postEphemeral`_
            if `ephemeral_user` is True.

        .. _chat.postMessage: https://api.slack.com/methods/chat.postMessage
        .. _chat.postEphemeral: https://api.slack.com/methods/chat.postEphemeral
        """
        return self._client.send(
            channel,
            text=text,
            attachments=attachments,
            blocks=blocks,
            thread_ts=thread_ts,
            ephemeral_user=ephemeral_user,
            **kwargs,
        )

    def say_scheduled(
        self,
        when: datetime,
        channel: Union[Channel, str],
        text: str,
        attachments: Union[List[Attachment], List[Dict[str, Any]], None] = None,
        blocks: Union[List[Block], List[Dict[str, Any]], None] = None,
        thread_ts: Optional[str] = None,
        ephemeral_user: Union[User, str, None] = None,
        **kwargs,
    ):
        """Schedule a message to a channel

        This is the scheduled version of :py:meth:`~machine.plugins.base.MachineBasePlugin.say`.
        It behaves the same, but will send the message at the scheduled time.

        :param when: when you want the message to be sent, as :py:class:`datetime.datetime` instance
        :param channel: :py:class:`~machine.models.channel.Channel` object or id of channel to send
            message to. Can be public or private (group) channel, or DM channel.
        :param text: message text
        :param attachments: optional attachments (see `attachments`_)
        :param blocks: optional blocks (see `blocks`_)
        :param thread_ts: optional timestamp of thread, to send a message in that thread
        :param ephemeral_user: optional :py:class:`~machine.models.user.User` object or id of user
            if the message needs to visible to that specific user only
        :return: None

        .. _attachments: https://api.slack.com/docs/message-attachments
        .. _blocks: https://api.slack.com/reference/block-kit/blocks
        """
        self._client.send_scheduled(
            when,
            channel,
            text=text,
            attachments=attachments,
            blocks=blocks,
            thread_ts=thread_ts,
            ephemeral_user=ephemeral_user,
            **kwargs,
        )

    def react(self, channel: Union[Channel, str], ts: str, emoji: str):
        """React to a message in a channel

        Add a reaction to a message in a channel. What message to react to, is determined by the
        combination of the channel and the timestamp of the message.

        :param channel: :py:class:`~machine.models.channel.Channel` object or id of channel to send
            message to. Can be public or private (group) channel, or DM channel.
        :param ts: timestamp of the message to react to
        :param emoji: what emoji to react with (should be a string, like 'angel', 'thumbsup', etc.)
        :return: Dictionary deserialized from `reactions.add`_ request.

        .. _reactions.add: https://api.slack.com/methods/reactions.add
        """
        return self._client.react(channel, ts, emoji)

    def send_dm(
        self,
        user: Union[User, str],
        text: str,
        attachments: Union[List[Attachment], List[Dict[str, Any]], None] = None,
        blocks: Union[List[Block], List[Dict[str, Any]], None] = None,
        **kwargs,
    ):
        """Send a Direct Message

        Send a Direct Message to a user by opening a DM channel and sending a message to it. Allows
        for rich formatting using `blocks`_ and/or `attachments`_. You can provide blocks and
        attachments as Python dicts or you can use the `convenient classes`_ that the underlying
        slack client provides.
        Any extra kwargs you provide, will be passed on directly to the `chat.postMessage`_ request.

        .. _attachments: https://api.slack.com/docs/message-attachments
        .. _blocks: https://api.slack.com/reference/block-kit/blocks
        .. _convenient classes:
            https://github.com/slackapi/python-slackclient/tree/master/slack/web/classes

        :param user: :py:class:`~machine.models.user.User` object or id of user to send DM to.
        :param text: message text
        :param attachments: optional attachments (see `attachments`_)
        :param blocks: optional blocks (see `blocks`_)
        :return: Dictionary deserialized from `chat.postMessage`_ request.

        .. _chat.postMessage: https://api.slack.com/methods/chat.postMessage
        """
        return self._client.send_dm(user, text, attachments=attachments, blocks=blocks, **kwargs)

    def send_dm_scheduled(
        self,
        when: datetime,
        user: Union[User, str],
        text: str,
        attachments: Union[List[Attachment], List[Dict[str, Any]], None] = None,
        blocks: Union[List[Block], List[Dict[str, Any]], None] = None,
        **kwargs,
    ):
        """Schedule a Direct Message

        This is the scheduled version of
        :py:meth:`~machine.plugins.base.MachineBasePlugin.send_dm`. It behaves the same, but
        will send the DM at the scheduled time.

        :param when: when you want the message to be sent, as :py:class:`datetime.datetime` instance
        :param user: :py:class:`~machine.models.user.User` object or id of user to send DM to.
        :param text: message text
        :param attachments: optional attachments (see `attachments`_)
        :param blocks: optional blocks (see `blocks`_)
        :return: None

        .. _attachments: https://api.slack.com/docs/message-attachments
        .. _blocks: https://api.slack.com/reference/block-kit/blocks
        """
        self._client.send_dm_scheduled(when, user, text=text, attachments=attachments, blocks=blocks, **kwargs)

    def emit(self, event: str, **kwargs):
        """Emit an event

        Emit an event that plugins can listen for. You can include arbitrary data as keyword
        arguments.

        :param event: name of the event
        :param kwargs: any data you want to emit with the event
        :return: None
        """
        e = signal(event)
        e.send(self, **kwargs)


class Message:
    """A message that was received by the bot

    This class represents a message that was received by the bot and passed to one or more
    plugins. It contains the message (text) itself, and metadata about the message, such as the
    sender of the message, the channel the message was sent to.

    The ``Message`` class also contains convenience methods for replying to the message in the
    right channel, replying to the sender, etc.
    """

    def __init__(self, client: SlackClient, msg_event: Dict[str, Any], plugin_class_name: str):
        self._client = client
        self._msg_event = msg_event
        self._fq_plugin_name = plugin_class_name

    @property
    def subtype(self) -> str:
        """The subtype of the message, if applicable

        :return: the subtype of the message, if applicable
        """
        if "subtype" in self._msg_event:
            return self._msg_event["subtype"]
        else:
            return None

    @property
    def sender(self) -> User:
        """The sender of the message

        :return: the User the message was sent by
        """
        return self._client.users[self._msg_event["user"]]

    @property
    def channel(self) -> Channel:
        """The channel the message was sent to

        :return: the Channel the message was sent to
        """
        return self._client.channels[self._msg_event["channel"]]

    @property
    def is_dm(self) -> bool:
        channel_id = self._msg_event["channel"]
        return not (channel_id.startswith("C") or channel_id.startswith("G"))

    @property
    def text(self) -> str:
        """The body of the actual message

        :return: the body (text) of the actual message
        """
        return self._msg_event["text"]

    @property
    def at_sender(self) -> str:
        """The sender of the message formatted as mention

        :return: a string representation of the sender of the message, formatted as `mention`_,
            to be used in messages

        .. _mention: https://api.slack.com/docs/message-formatting#linking_to_channels_and_users
        """
        return self.sender.fmt_mention()

    def say(
        self,
        text: str,
        attachments: Union[List[Attachment], List[Dict[str, Any]], None] = None,
        blocks: Union[List[Block], List[Dict[str, Any]], None] = None,
        thread_ts: Optional[str] = None,
        ephemeral: bool = False,
        **kwargs,
    ):
        """Send a new message to the channel the original message was received in

        Send a new message to the channel the original message was received in, using the WebAPI.
        Allows for rich formatting using `blocks`_ and/or `attachments`_. You can provide blocks
        and attachments as Python dicts or you can use the `convenient classes`_ that the
        underlying slack client provides.
        Can also reply to a thread and send an ephemeral message only visible to the sender of the
        original message. Ephemeral messages and threaded messages are mutually exclusive, and
        ``ephemeral`` takes precedence over ``thread_ts``
        Any extra kwargs you provide, will be passed on directly to the `chat.postMessage`_ or
        `chat.postEphemeral`_ request.

        .. _attachments: https://api.slack.com/docs/message-attachments
        .. _blocks: https://api.slack.com/reference/block-kit/blocks
        .. _convenient classes:
            https://github.com/slackapi/python-slackclient/tree/master/slack/web/classes

        :param text: message text
        :param attachments: optional attachments (see `attachments`_)
        :param blocks: optional blocks (see `blocks`_)
        :param thread_ts: optional timestamp of thread, to send a message in that thread
        :param ephemeral: ``True/False`` wether to send the message as an ephemeral message, only
            visible to the sender of the original message
        :return: Dictionary deserialized from `chat.postMessage`_ request, or `chat.postEphemeral`_
            if `ephemeral` is True.

        .. _chat.postMessage: https://api.slack.com/methods/chat.postMessage
        .. _chat.postEphemeral: https://api.slack.com/methods/chat.postEphemeral
        """
        if ephemeral:
            ephemeral_user = self.sender.id
        else:
            ephemeral_user = None

        return self._client.send(
            self.channel.id,
            text=text,
            attachments=attachments,
            blocks=blocks,
            thread_ts=thread_ts,
            ephemeral_user=ephemeral_user,
            **kwargs,
        )

    def say_scheduled(
        self,
        when: datetime,
        text: str,
        attachments: Union[List[Attachment], List[Dict[str, Any]], None] = None,
        blocks: Union[List[Block], List[Dict[str, Any]], None] = None,
        thread_ts: Optional[str] = None,
        ephemeral: bool = False,
        **kwargs,
    ):
        """Schedule a message

        This is the scheduled version of :py:meth:`~machine.plugins.base.Message.say`.
        It behaves the same, but will send the message at the scheduled time.

        :param when: when you want the message to be sent, as :py:class:`datetime.datetime` instance
        :param text: message text
        :param attachments: optional attachments (see `attachments`_)
        :param blocks: optional blocks (see `blocks`_)
        :param thread_ts: optional timestamp of thread, to send a message in that thread
        :param ephemeral: ``True/False`` wether to send the message as an ephemeral message, only
            visible to the sender of the original message
        :return: None

        .. _attachments: https://api.slack.com/docs/message-attachments
        .. _blocks: https://api.slack.com/reference/block-kit/blocks
        """
        if ephemeral:
            ephemeral_user = self.sender.id
        else:
            ephemeral_user = None

        self._client.send_scheduled(
            when,
            self.channel.id,
            text=text,
            attachments=attachments,
            blocks=blocks,
            thread_ts=thread_ts,
            ephemeral_user=ephemeral_user,
            **kwargs,
        )

    def reply(
        self,
        text,
        attachments: Union[List[Attachment], List[Dict[str, Any]], None] = None,
        blocks: Union[List[Block], List[Dict[str, Any]], None] = None,
        in_thread: bool = False,
        ephemeral: bool = False,
        **kwargs,
    ):
        """Reply to the sender of the original message

        Reply to the sender of the original message with a new message, mentioning that user. Rich
        formatting using `blocks`_ and/or `attachments`_ is possible. You can provide blocks
        and attachments as Python dicts or you can use the `convenient classes`_ that the
        underlying slack client provides.
        Can also reply to a thread and send an ephemeral message only visible to the sender of the
        original message. In the case of in-thread response, the sender of the original message
        will not be mentioned. Ephemeral messages and threaded messages are mutually exclusive,
        and ``ephemeral`` takes precedence over ``in_thread``
        Any extra kwargs you provide, will be passed on directly to the `chat.postMessage`_ or
        `chat.postEphemeral`_ request.

        .. _attachments: https://api.slack.com/docs/message-attachments
        .. _blocks: https://api.slack.com/reference/block-kit/blocks
        .. _convenient classes:
            https://github.com/slackapi/python-slackclient/tree/master/slack/web/classes

        :param text: message text
        :param attachments: optional attachments (see `attachments`_)
        :param blocks: optional blocks (see `blocks`_)
        :param in_thread: ``True/False`` wether to reply to the original message in-thread
        :param ephemeral: ``True/False`` wether to send the message as an ephemeral message, only
            visible to the sender of the original message
        :return: Dictionary deserialized from `chat.postMessage`_ request, or `chat.postEphemeral`_
            if `ephemeral` is True.

        .. _chat.postMessage: https://api.slack.com/methods/chat.postMessage
        .. _chat.postEphemeral: https://api.slack.com/methods/chat.postEphemeral
        """
        if in_thread and not ephemeral:
            return self.say(text, attachments=attachments, blocks=blocks, thread_ts=self.ts, **kwargs)
        else:
            text = self._create_reply(text)
            return self.say(text, attachments=attachments, blocks=blocks, ephemeral=ephemeral, **kwargs)

    def reply_scheduled(
        self,
        when: datetime,
        text: str,
        attachments: Union[List[Attachment], List[Dict[str, Any]], None] = None,
        blocks: Union[List[Block], List[Dict[str, Any]], None] = None,
        in_thread: bool = False,
        ephemeral: bool = False,
        **kwargs,
    ):
        """Schedule a reply and send it

        This is the scheduled version of :py:meth:`~machine.plugins.base.Message.reply`.
        It behaves the same, but will send the reply at the scheduled time.

        :param when: when you want the message to be sent, as :py:class:`datetime.datetime` instance
        :param text: message text
        :param attachments: optional attachments (see `attachments`_)
        :param blocks: optional blocks (see `blocks`_)
        :param in_thread: ``True/False`` wether to reply to the original message in-thread
        :param ephemeral: ``True/False`` wether to send the message as an ephemeral message, only
            visible to the sender of the original message
        :return: None

        .. _attachments: https://api.slack.com/docs/message-attachments
        .. _blocks: https://api.slack.com/reference/block-kit/blocks
        """
        if in_thread and not ephemeral:
            return self.say_scheduled(when, text, attachments=attachments, blocks=blocks, thread_ts=self.ts, **kwargs)
        else:
            text = self._create_reply(text)
            return self.say_scheduled(when, text, attachments=attachments, blocks=blocks, ephemeral=ephemeral, **kwargs)

    def reply_dm(
        self,
        text: str,
        attachments: Union[List[Attachment], List[Dict[str, Any]], None] = None,
        blocks: Union[List[Block], List[Dict[str, Any]], None] = None,
        **kwargs,
    ):
        """Reply to the sender of the original message with a DM

        Reply in a Direct Message to the sender of the original message by opening a DM channel and
        sending a message to it. Allows for rich formatting using `blocks`_ and/or `attachments`_.
        You can provide blocks and attachments as Python dicts or you can use the
        `convenient classes`_ that the underlying slack client provides.
        Any extra kwargs you provide, will be passed on directly to the `chat.postMessage`_ request.

        .. _attachments: https://api.slack.com/docs/message-attachments
        .. _blocks: https://api.slack.com/reference/block-kit/blocks
        .. _convenient classes:
            https://github.com/slackapi/python-slackclient/tree/master/slack/web/classes

        :param text: message text
        :param attachments: optional attachments (see `attachments`_)
        :param blocks: optional blocks (see `blocks`_)
        :return: Dictionary deserialized from `chat.postMessage`_ request.

        .. _chat.postMessage: https://api.slack.com/methods/chat.postMessage
        """
        return self._client.send_dm(self.sender.id, text, attachments=attachments, blocks=blocks, **kwargs)

    def reply_dm_scheduled(
        self,
        when: datetime,
        text: str,
        attachments: Union[List[Attachment], List[Dict[str, Any]], None] = None,
        blocks: Union[List[Block], List[Dict[str, Any]], None] = None,
        **kwargs,
    ):
        """Schedule a DM reply and send it

        This is the scheduled version of :py:meth:`~machine.plugins.base.Message.reply_dm`.
        It behaves the same, but will send the DM at the scheduled time.

        :param when: when you want the message to be sent, as :py:class:`datetime.datetime` instance
        :param text: message text
        :param attachments: optional attachments (see `attachments`_)
        :param blocks: optional blocks (see `blocks`_)
        :return: None

        .. _attachments: https://api.slack.com/docs/message-attachments
        .. _blocks: https://api.slack.com/reference/block-kit/blocks
        """
        self._client.send_dm_scheduled(
            when, self.sender.id, text=text, attachments=attachments, blocks=blocks, **kwargs
        )

    def react(self, emoji: str):
        """React to the original message

        Add a reaction to the original message

        :param emoji: what emoji to react with (should be a string, like 'angel', 'thumbsup', etc.)
        :return: Dictionary deserialized from `reactions.add`_ request.

        .. _reactions.add: https://api.slack.com/methods/reactions.add
        """
        return self._client.react(self.channel.id, self._msg_event["ts"], emoji)

    def _create_reply(self, text):
        if not self.is_dm:
            return f"{self.at_sender}: {text}"
        else:
            return text

    @property
    def ts(self) -> str:
        """The timestamp of the message

        :return: the timestamp of the message
        """
        return self._msg_event["ts"]

    @property
    def in_thread(self):
        """Is message in a thread

        :return: bool
        """
        return "thread_ts" in self._msg_event

    def __str__(self):
        if self.channel.is_im:
            message = f"Message '{self.text}', sent by user @{self.sender.profile.real_name} in DM"
        else:
            message = "Message '{}', sent by user @{} in channel #{}".format(
                self.text, self.sender.profile.real_name, self.channel.name
            )
        return message

    def __repr__(self):
        return "Message(text={}, sender={}, channel={})".format(
            repr(self.text), repr(self.sender.profile.real_name), repr(self.channel.name)
        )
