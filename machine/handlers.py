from __future__ import annotations

import asyncio
import logging
import re
from typing import Any, Callable, Awaitable, Mapping

from structlog.stdlib import get_logger

from slack_sdk.socket_mode.async_client import AsyncBaseSocketModeClient
from slack_sdk.socket_mode.request import SocketModeRequest
from slack_sdk.socket_mode.response import SocketModeResponse

from machine.clients.slack import SlackClient
from machine.models.core import RegisteredActions, MessageHandler, BlockActionHandler
from machine.plugins.base import Message

logger = logging.getLogger(__name__)


def create_block_actions_handler(
    plugin_actions: RegisteredActions,
    settings: Mapping,
    bot_id: str,
    bot_name: str,
    slack_client: SlackClient,
) -> Callable[[AsyncBaseSocketModeClient, SocketModeRequest], Awaitable[None]]:
    async def block_actions_handler(client: AsyncBaseSocketModeClient, request: SocketModeRequest) -> None:
        if request.type == "interactive":
            # Acknowledge the request anyway
            response = SocketModeResponse(envelope_id=request.envelope_id)
            # Don't forget having await for method calls
            await client.send_socket_mode_response(response)

            type = request.payload["type"]
            if type == "block_actions":
                await handle_block_actions(
                    payload=request.payload,
                    plugin_actions=plugin_actions,
                    slack_client=slack_client,
                    log_handled_message=settings["LOG_HANDLED_MESSAGES"],
                )

    return block_actions_handler


def create_message_handler(
    plugin_actions: RegisteredActions,
    settings: Mapping,
    bot_id: str,
    bot_name: str,
    slack_client: SlackClient,
) -> Callable[[AsyncBaseSocketModeClient, SocketModeRequest], Awaitable[None]]:
    message_matcher = generate_message_matcher(settings)

    async def message_handler(client: AsyncBaseSocketModeClient, request: SocketModeRequest) -> None:
        if request.type == "events_api":
            # Acknowledge the request anyway
            response = SocketModeResponse(envelope_id=request.envelope_id)
            # Don't forget having await for method calls
            await client.send_socket_mode_response(response)

            # only process message events
            if request.payload["event"]["type"] == "message":
                await handle_message(
                    event=request.payload["event"],
                    bot_name=bot_name,
                    bot_id=bot_id,
                    plugin_actions=plugin_actions,
                    message_matcher=message_matcher,
                    slack_client=slack_client,
                    log_handled_message=settings["LOG_HANDLED_MESSAGES"],
                )

    return message_handler


def create_generic_event_handler(
    plugin_actions: RegisteredActions,
) -> Callable[[AsyncBaseSocketModeClient, SocketModeRequest], Awaitable[None]]:
    async def generic_event_handler(client: AsyncBaseSocketModeClient, request: SocketModeRequest) -> None:
        if request.type == "events_api":
            # Acknowledge the request anyway
            response = SocketModeResponse(envelope_id=request.envelope_id)
            # Don't forget having await for method calls
            await client.send_socket_mode_response(response)

            # only process message events
            if request.payload["event"]["type"] in plugin_actions.process:
                await dispatch_event_handlers(
                    request.payload["event"], list(plugin_actions.process[request.payload["event"]["type"]].values())
                )

    return generic_event_handler


def generate_message_matcher(settings: Mapping) -> re.Pattern[str]:
    alias_regex = ""
    if "ALIASES" in settings:
        logger.debug("Setting aliases to %s", settings["ALIASES"])
        alias_alternatives = "|".join([re.escape(alias) for alias in settings["ALIASES"].split(",")])
        alias_regex = f"|(?P<alias>{alias_alternatives})"
    return re.compile(
        rf"^(?:<@(?P<atuser>\w+)>:?|(?P<username>\w+):{alias_regex}) ?(?P<text>.*)$",
        re.DOTALL,
    )


async def handle_message(
    event: dict[str, Any],
    bot_name: str,
    bot_id: str,
    plugin_actions: RegisteredActions,
    message_matcher: re.Pattern,
    slack_client: SlackClient,
    log_handled_message: bool,
) -> None:
    # Handle message subtype 'message_changed' to allow the bot to respond to edits
    if "subtype" in event and event["subtype"] == "message_changed":
        channel_type = event["channel_type"]
        channel = event["channel"]
        event = event["message"]
        event["channel_type"] = channel_type
        event["channel"] = channel
        event["subtype"] = "message_changed"
    if "user" in event and not event["user"] == bot_id:
        listeners = list(plugin_actions.listen_to.values())
        respond_to_msg = _check_bot_mention(
            event,
            bot_name,
            bot_id,
            message_matcher,
        )
        if respond_to_msg:
            listeners += list(plugin_actions.respond_to.values())
            await dispatch_listeners(respond_to_msg, listeners, slack_client, log_handled_message)
        else:
            await dispatch_listeners(event, listeners, slack_client, log_handled_message)


async def handle_block_actions(
    payload: dict[str, Any],
    plugin_actions: RegisteredActions,
    slack_client: SlackClient,
    log_handled_message: bool,
) -> None:
    listeners = list(plugin_actions.block_action_react_to.values())
    await dispatch_block_action_listeners(payload, listeners, slack_client, log_handled_message)


def _check_bot_mention(event: dict[str, Any], bot_name: str, bot_id: str, message_matcher: re.Pattern[str]) -> dict[str, Any] | None:
    full_text = event.get("text", "")
    channel_type = event["channel_type"]
    m = message_matcher.match(full_text)

    if channel_type == "channel" or channel_type == "group":
        if not m:
            return None

        matches = m.groupdict()

        atuser = matches.get("atuser")
        username = matches.get("username")
        text = matches.get("text")
        alias = matches.get("alias")

        if alias:
            atuser = bot_id

        if atuser != bot_id and username != bot_name:
            # a channel message at other user
            return None

        event["text"] = text
    else:
        if m:
            event["text"] = m.groupdict().get("text", None)
    return event


def _gen_message(event: dict[str, Any], plugin_class_name: str, slack_client: SlackClient, msg_type: str = "message") -> Message:
    return Message(slack_client, event, plugin_class_name, msg_type)


async def dispatch_listeners(
    event: dict[str, Any], message_handlers: list[MessageHandler], slack_client: SlackClient, log_handled_message: bool
) -> None:
    handler_funcs = []
    for handler in message_handlers:
        matcher = handler.regex
        if "subtype" in event and event["subtype"] == "message_changed" and not handler.handle_message_changed:
            continue
        match = matcher.search(event.get("text", ""))
        if match:
            message = _gen_message(event, handler.class_name, slack_client)
            extra_params = {**match.groupdict()}
            fq_fn_name = f"{handler.class_name}.{handler.function.__name__}"
            handler_logger = get_logger(fq_fn_name)
            handler_logger = handler_logger.bind(user_id=message.sender.id, user_name=message.sender.name)
            if log_handled_message:
                handler_logger.info("Handling message", message=message.text)
            if "logger" in handler.function_signature.parameters:
                extra_params["logger"] = handler_logger
            handler_funcs.append(handler.function(message, **extra_params))
    await asyncio.gather(*handler_funcs)
    return


async def dispatch_block_action_listeners(
    payload: dict[str, Any],
    block_action_handlers: list[BlockActionHandler],
    slack_client: SlackClient,
    log_handled_message: bool,
) -> None:
    handler_funcs = []
    for handler in block_action_handlers:
        action_id = handler.action_id
        for action in payload["actions"]:
            if action_id == action["action_id"]:
                event = {"action": action, "user": payload["user"], "channel": payload["channel"]}
                message = _gen_message(event, handler.class_name, slack_client, msg_type="interactive")
                fq_fn_name = f"{handler.class_name}.{handler.function.__name__}"
                handler_logger = get_logger(fq_fn_name)
                handler_logger = handler_logger.bind(user_id=message.sender.id, user_name=message.sender.name)
                if log_handled_message:
                    handler_logger.info("Handling message", message=message.text)
                extra_params = {}
                if "logger" in handler.function_signature.parameters:
                    extra_params["logger"] = handler_logger
                handler_funcs.append(handler.function(message, **extra_params))
    await asyncio.gather(*handler_funcs)
    return


async def dispatch_event_handlers(event: dict[str, Any], event_handlers: list[Callable[[dict[str, Any]], Awaitable[None]]]) -> None:
    handler_funcs = [f(event) for f in event_handlers]
    await asyncio.gather(*handler_funcs)
