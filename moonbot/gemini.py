# This scripts contains use cases for userbots
# This is used on my Moon-Userbot: https://github.com/The-MoonTg-project/Moon-Userbot
# YOu can check it out for uses example

import io
import re
import asyncio
from datetime import datetime, timedelta

from pyrogram import Client, filters, enums
from pyrogram.types import Message
from pyrogram.errors import MessageTooLong


from PIL import Image

from utils.db import db
from utils.misc import modules_help, prefix
from utils.scripts import format_exc, import_library
from utils.config import gemini_key

genai = import_library("google.generativeai", "google-generativeai")
telegraph_lib = import_library("telegraph", "telegraph")

genai.configure(api_key=gemini_key)

# Setup Telegraph
telegraph = telegraph_lib.Telegraph()


def _parse_telegraph_node(node):
    """Recursively parse Telegraph node object to text."""
    if isinstance(node, str):
        return node
    if isinstance(node, dict):
        content = ""
        if "children" in node:
            for child in node["children"]:
                content += _parse_telegraph_node(child)
        if node.get("tag") in [
            "p",
            "h1",
            "h2",
            "h3",
            "h4",
            "h5",
            "h6",
            "br",
            "hr",
            "li",
            "blockquote",
        ]:
            content += "\n"
        return content
    return ""


async def get_telegraph_content(url: str) -> str | None:
    """Fetches and parses content from a Telegraph URL."""
    match = re.match(r"https?://telegra\.ph/(.+)", url)
    if not match:
        return None
    path = match.group(1)
    try:
        page = await asyncio.to_thread(telegraph.get_page, path, return_content=True)
        content = ""
        for node in page.get("content", []):
            content += _parse_telegraph_node(node)
        return content
    except Exception:
        return None


# Thread-safety lock for chat history
_chat_lock = asyncio.Lock()

chat_history = {}
last_interaction_time = {}
context_expiration_minutes = db.get("custom.gemini", "context_expiration_minutes", 5)

safety_settings = {
    "HARM_CATEGORY_DANGEROUS_CONTENT": "BLOCK_NONE",
    "HARM_CATEGORY_HARASSMENT": "BLOCK_NONE",
    "HARM_CATEGORY_HATE_SPEECH": "BLOCK_NONE",
    "HARM_CATEGORY_SEXUALLY_EXPLICIT": "BLOCK_NONE",
}


def get_model(for_image=False):
    if for_image:
        model_name = "gemini-2.0-flash-preview-image-generation"
        return genai.GenerativeModel(
            model_name, safety_settings=safety_settings
        )
    else:
        model_name = db.get("custom.gemini", "model", "gemini-2.0-flash")
        system_prompt = db.get("custom.gemini", "active_prompt")
        if system_prompt:
            prompts = db.get("custom.gemini", "prompts", {})
            system_prompt = prompts.get(system_prompt)
        else:
            system_prompt = "You are a helpful AI assistant."
        
        return genai.GenerativeModel(
            model_name, safety_settings=safety_settings, system_instruction=system_prompt
        )


async def _gemini_imgen(client: Client, message: Message):
    """Handles image generation and editing for the gemini command."""
    prompt = " ".join(message.command[2:])
    if not prompt:
        await message.edit_text(
            f"<b>Usage:</b> <code>{prefix}gemini imgen [prompt]</code>\n"
            f"Reply to an image to edit it with the given prompt."
        )
        return

    contents = [prompt]
    caption_action = "Generated"
    media_to_edit = None

    if message.reply_to_message:
        if message.reply_to_message.photo:
            media_to_edit = message.reply_to_message.photo
            caption_action = "Edited"
        elif message.reply_to_message.sticker and not message.reply_to_message.sticker.is_animated and not message.reply_to_message.sticker.is_video:
            media_to_edit = message.reply_to_message.sticker
            caption_action = "Edited"

    status_message = f"<code>{'Editing' if caption_action == 'Edited' else 'Generating'} image...</code>"
    await message.edit_text(status_message)

    try:
        if caption_action == "Edited" and media_to_edit:
            if media_to_edit.file_size > 10 * 1024 * 1024:
                await message.edit_text("<b>Error:</b> <code>Image size is too large (max 10MB)</code>")
                return
            image_stream = await client.download_media(media_to_edit, in_memory=True)
            pil_image = Image.open(image_stream)
            contents.append(pil_image)

        model = get_model(for_image=True)

        generation_config = {
            "response_modalities": ["IMAGE", "TEXT"],
            "response_mime_type": "text/plain",
        }

        response_stream = model.generate_content(
            contents,
            generation_config=generation_config,
            stream=True
        )

        image_found = False
        full_error_message = ""

        for chunk in response_stream:
            if image_found:
                continue

            if (
                chunk.candidates
                and chunk.candidates[0].content
                and chunk.candidates[0].content.parts
            ):
                part = chunk.candidates[0].content.parts[0]
                if part.inline_data and part.inline_data.data:
                    image_data = part.inline_data
                    image_bytes = image_data.data
                    image_file = io.BytesIO(image_bytes)
                    image_file.name = "image.jpeg"
                    
                    processed_prompt = prompt.replace('\n', '\n> ')
                    caption_text = f"**{caption_action} Image**\n**Prompt:**\n> {processed_prompt}\nPowered by Gemini"

                    await client.send_photo(
                        message.chat.id,
                        photo=image_file,
                        caption=caption_text,
                        parse_mode=enums.ParseMode.MARKDOWN,
                        reply_to_message_id=message.id
                    )
                    await message.edit_text(f"✅ **Image {caption_action.lower()}**", parse_mode=enums.ParseMode.MARKDOWN)
                    image_found = True
                else:
                    if chunk.text:
                        full_error_message += chunk.text
            elif chunk.text:
                full_error_message += chunk.text

        if not image_found:
            error_message = full_error_message or "Generation failed. The response was empty or blocked."
            if response_stream.prompt_feedback and response_stream.prompt_feedback.block_reason:
                 error_message = f"Blocked for: {response_stream.prompt_feedback.block_reason.name}"
            await message.edit_text(f"<b>Model Error:</b> <code>{error_message}</code>")

    except Exception as e:
        await message.edit_text(f"An unexpected error occurred: {format_exc(e)}")


async def _ask_gemini(client: Client, message: Message):
    try:
        await message.edit_text("<code>Thinking...</code>")

        command_text = message.text or message.caption or ""
        prompt_parts = []
        replied_text = None

        if message.reply_to_message:
            replied_text = (
                message.reply_to_message.text or message.reply_to_message.caption
            )
            if replied_text:
                prompt_parts.append(replied_text)

        command_prompt = None
        parts = command_text.split(maxsplit=1)
        if len(parts) > 1:
            command_prompt = parts[1]
            prompt_parts.append(command_prompt)

        prompt = "\n".join(prompt_parts)

        telegraph_urls = re.findall(r"https?://telegra\.ph/\S+", prompt)
        if telegraph_urls:
            await message.edit_text(
                "<code>Found Telegraph link, fetching content...</code>"
            )
            telegraph_content = ""
            for url in telegraph_urls:
                content = await get_telegraph_content(url)
                if content:
                    telegraph_content += content + "\n\n"
            if telegraph_content:
                prompt = (
                    f"Context from Telegraph:\n{telegraph_content}\n\nMy prompt:\n{prompt}"
                )
            await message.edit_text("<code>Thinking...</code>")

        image_part = None
        media_to_process = None
        if message.photo:
            media_to_process = message.photo
        elif message.reply_to_message:
            if message.reply_to_message.photo:
                media_to_process = message.reply_to_message.photo
            elif (
                message.reply_to_message.sticker
                and not message.reply_to_message.sticker.is_animated
                and not message.reply_to_message.sticker.is_video
            ):
                media_to_process = message.reply_to_message.sticker

        if media_to_process:
            if media_to_process.file_size > 10 * 1024 * 1024:
                await message.edit_text(
                    "<b>Error:</b> <code>Image size is too large (max 10MB)</code>"
                )
                return
            image_stream = await client.download_media(
                media_to_process, in_memory=True
            )
            if image_stream:
                try:
                    pil_image = Image.open(image_stream)
                    image_part = pil_image
                except Exception as e:
                    await message.edit_text(
                        f"<b>Error:</b> <code>Failed to process image: {e}</code>"
                    )
                    return

        if not prompt and not image_part:
            await message.edit_text(
                f"<b>Usage: </b><code>{prefix}gemini [prompt/reply to message with text or image]</code>"
            )
            return

        contents = []
        if prompt:
            contents.append(prompt)
        if image_part:
            contents.append(image_part)

        model = get_model()
        is_context_on = db.get("custom.gemini", "context_on", False)
        user_id = message.from_user.id

        max_tokens = db.get("custom.gemini", "max_tokens")
        generation_config = None
        if max_tokens:
            try:
                generation_config = {"max_output_tokens": int(max_tokens)}
            except (ValueError, TypeError):
                pass

        if is_context_on:
            async with _chat_lock:
                if user_id not in chat_history or (
                    user_id in last_interaction_time
                    and datetime.now() - last_interaction_time[user_id]
                    > timedelta(minutes=context_expiration_minutes)
                ):
                    chat_history[user_id] = []

                last_interaction_time[user_id] = datetime.now()

                chat = model.start_chat(history=chat_history[user_id])
                response = await chat.send_message_async(
                    contents, generation_config=generation_config
                )
                chat_history[user_id] = chat.history
        else:
            response = await model.generate_content_async(
                contents, generation_config=generation_config
            )

        output_text = ""
        if response.parts:
            output_text = "".join(part.text for part in response.parts)

        if response.candidates[0].finish_reason.name == "MAX_TOKENS":
            output_text += "\n\n[...Output truncated due to max_tokens limit...]"

        question_text = ""
        if prompt:
            display_prompt = None
            if command_prompt:
                display_prompt = command_prompt
            elif replied_text and (
                not message.reply_to_message.from_user
                or not message.reply_to_message.from_user.is_self
            ):
                display_prompt = replied_text

            if display_prompt:
                if len(display_prompt) > 200:
                    display_prompt = display_prompt[:200] + "..."
                processed_prompt = display_prompt.replace("\n", "\n> ")
                question_text = f"👤**Prompt:**\n> {processed_prompt}"

        processed_response = output_text.replace("\n", "\n> ")
        full_response_text = f"{question_text}\n🤖**Response:**\n> {processed_response}\nPowered by Gemini"

        telegraph_char_limit = db.get("custom.gemini", "telegraph_char_limit")
        if (
            telegraph_char_limit
            and len(full_response_text) > telegraph_char_limit
            and db.get("custom.gemini", "telegraph_on", True)
        ):
            await message.edit_text(
                "<code>Output is long... Pasting to Telegraph...</code>"
            )
            return await post_to_telegraph(
                message, output_text, question_text, command_prompt, replied_text
            )

        await message.edit_text(
            full_response_text,
            parse_mode=enums.ParseMode.MARKDOWN,
        )
    except MessageTooLong:
        if not db.get("custom.gemini", "telegraph_on", True):
            await message.edit_text(
                "<b>Error:</b> <code>Output is too long.</code>\n"
                f"<b>Tip:</b> <code>You can enable Telegraph posting with {prefix}gemini telegraph on</code>"
            )
            return

        await message.edit_text(
            "<code>Output is too long... Pasting to Telegraph...</code>"
        )
        await post_to_telegraph(
            message, output_text, question_text, command_prompt, replied_text
        )
    except Exception as e:
        await message.edit_text(f"An error occurred: {format_exc(e)}")


async def post_to_telegraph(
    message: Message, output_text: str, question_text: str, command_prompt, replied_text
):
    """Posts the response to Telegraph."""
    try:
        short_name = db.get("custom.gemini", "telegraph_short_name", "Moonbot")
        telegraph.create_account(short_name=short_name, replace_token=True)
        response_text = output_text.replace("\n", "<br>")
        page = await asyncio.to_thread(
            telegraph.create_page,
            title="Gemini Response",
            html_content=f"<p>{response_text}</p><br><em>Powered by Gemini</em>",
        )
        telegraph_url = page["url"]

        # Re-create question_text for telegraph response
        question_text = ""
        if command_prompt or replied_text:
            display_prompt = None
            if command_prompt:
                display_prompt = command_prompt
            elif replied_text and (
                not message.reply_to_message.from_user
                or not message.reply_to_message.from_user.is_self
            ):
                display_prompt = replied_text

            if display_prompt:
                if len(display_prompt) > 200:
                    display_prompt = display_prompt[:200] + "..."
                processed_prompt = display_prompt.replace("\n", "\n> ")
                question_text = f"👤**Prompt:**\n> {processed_prompt}"

        formatted_response = f"🤖**Response:**\n> {telegraph_url}"

        await message.edit_text(
            f"{question_text}\n{formatted_response}\nPowered by Gemini",
            disable_web_page_preview=False,
            parse_mode=enums.ParseMode.MARKDOWN,
        )
    except Exception as e:
        await message.edit_text(
            f"<b>Error:</b> <code>Failed to paste to Telegraph: {format_exc(e)}</code>"
        )
        try:
            short_name = db.get("custom.gemini", "telegraph_short_name", "Moonbot")
            telegraph.create_account(short_name=short_name, replace_token=True)
            response_text = output_text.replace("\n", "<br>")
            page = await asyncio.to_thread(
                telegraph.create_page,
                title="Gemini Response",
                html_content=f"<p>{response_text}</p><br><em>Powered by Gemini</em>",
            )
            telegraph_url = page["url"]

            # Re-create question_text for telegraph response
            question_text = ""
            if prompt:
                display_prompt = None
                if command_prompt:
                    display_prompt = command_prompt
                elif replied_text and (
                    not message.reply_to_message.from_user
                    or not message.reply_to_message.from_user.is_self
                ):
                    display_prompt = replied_text

                if display_prompt:
                    if len(display_prompt) > 200:
                        display_prompt = display_prompt[:200] + "..."
                    processed_prompt = display_prompt.replace("\n", "\n> ")
                    question_text = f"👤**Prompt:**\n> {processed_prompt}"

            formatted_response = f"🤖**Response:**\n> {telegraph_url}"

            await message.edit_text(
                f"{question_text}\n{formatted_response}\nPowered by Gemini",
                disable_web_page_preview=False,
                parse_mode=enums.ParseMode.MARKDOWN,
            )
        except Exception as e:
            await message.edit_text(
                f"<b>Error:</b> <code>Failed to paste to Telegraph: {format_exc(e)}</code>"
            )
    except Exception as e:
        await message.edit_text(f"An error occurred: {format_exc(e)}")


@Client.on_message(filters.command("gemini", prefix) & filters.me)
async def gemini(client: Client, message: Message):
    command = message.command
    if len(command) > 1:
        sub_command = command[1]
        
        if sub_command == "imgen":
            await _gemini_imgen(client, message)
            return
            
        if sub_command == "model":
            if len(command) > 2:
                action = command[2]
                if action == "set":
                    if len(command) > 3:
                        model_name = command[3]
                        db.set("custom.gemini", "model", model_name)
                        await message.edit_text(
                            f"<b>Gemini model set to:</b> <code>{model_name}</code>"
                        )
                    else:
                        await message.edit_text(
                            f"<b>Usage:</b> <code>{prefix}gemini model set [model_name]</code>"
                        )
                    return
                if action == "list":
                    try:
                        models = [m.name.replace("models/", "") for m in genai.list_models() if 'generateContent' in m.supported_generation_methods]
                        model_list = "\n".join([f"• <code>{model}</code>" for model in models])
                        await message.edit_text(f"<b>Available Gemini models:</b>\n{model_list}")
                    except Exception as e:
                        await message.edit_text(f"<b>Error listing models:</b> <code>{format_exc(e)}</code>")
                    return
            await message.edit_text(
                f"<b>Usage:</b> <code>{prefix}gemini model [set|list]</code>"
            )
            return

        if sub_command == "telegraph":
            if len(command) > 2:
                action = command[2]
                if action == "on":
                    db.set("custom.gemini", "telegraph_on", True)
                    await message.edit_text("<b>Telegraph posting is now ON.</b>")
                elif action == "off":
                    db.set("custom.gemini", "telegraph_on", False)
                    await message.edit_text("<b>Telegraph posting is now OFF.</b>")
                else:
                    await message.edit_text(
                        f"<b>Usage:</b> <code>{prefix}gemini telegraph [on|off]</code>"
                    )
            else:
                is_on = db.get("custom.gemini", "telegraph_on", True)
                status = "ON" if is_on else "OFF"
                await message.edit_text(f"<b>Telegraph posting is currently {status}.</b>")
            return

        if sub_command == "telegraph_name":
            if len(command) > 2:
                name = " ".join(command[2:])
                db.set("custom.gemini", "telegraph_short_name", name)
                await message.edit_text(f"<b>Telegraph short name set to:</b> <code>{name}</code>")
            else:
                await message.edit_text(
                    f"<b>Usage:</b> <code>{prefix}gemini telegraph_name [name]</code>"
                )
            return

        if sub_command == "telegraph_limit":
            if len(command) > 2:
                value = command[2]
                if value.lower() == "clear":
                    db.set("custom.gemini", "telegraph_char_limit", None)
                    await message.edit_text(
                        "<b>Telegraph character limit cleared.</b>"
                    )
                else:
                    try:
                        limit = int(value)
                        if limit <= 0:
                            await message.edit_text(
                                "<b>Character limit must be a positive integer.</b>"
                            )
                        else:
                            db.set("custom.gemini", "telegraph_char_limit", limit)
                            await message.edit_text(
                                f"<b>Telegraph character limit set to:</b> <code>{limit}</code>"
                            )
                    except ValueError:
                        await message.edit_text(
                            "<b>Invalid number for character limit.</b>"
                        )
            else:
                limit = db.get("custom.gemini", "telegraph_char_limit")
                if limit:
                    await message.edit_text(
                        f"<b>Current character limit:</b> <code>{limit}</code>\n"
                        f"<b>Usage:</b> <code>{prefix}gemini telegraph_limit [number|clear]</code>"
                    )
                else:
                    await message.edit_text(
                        f"<b>Character limit is not set.</b>\n"
                        f"<b>Usage:</b> <code>{prefix}gemini telegraph_limit [number|clear]</code>"
                    )
            return

        if sub_command == "settings":
            model_name = db.get("custom.gemini", "model", "gemini-1.5-flash")
            max_tokens = db.get("custom.gemini", "max_tokens", "Not set")
            active_prompt = db.get("custom.gemini", "active_prompt", "Not set")
            context_status = "ON" if db.get("custom.gemini", "context_on", False) else "OFF"
            context_expiry = db.get("custom.gemini", "context_expiration_minutes", 5)
            telegraph_status = "ON" if db.get("custom.gemini", "telegraph_on", True) else "OFF"
            telegraph_name = db.get("custom.gemini", "telegraph_short_name", "Moonbot")
            telegraph_limit = db.get("custom.gemini", "telegraph_char_limit", "Not set")

            settings_text = (
                f"<b>Gemini Settings:</b>\n"
                f"• <b>Model:</b> <code>{model_name}</code>\n"
                f"• <b>Max Tokens:</b> <code>{max_tokens}</code>\n"
                f"• <b>Active Prompt:</b> <code>{active_prompt}</code>\n"
                f"• <b>Context:</b> <code>{context_status}</code>\n"
                f"• <b>Context Expiration:</b> <code>{context_expiry} minutes</code>\n"
                f"• <b>Telegraph Posting:</b> <code>{telegraph_status}</code>\n"
                f"• <b>Telegraph Name:</b> <code>{telegraph_name}</code>\n"
                f"• <b>Telegraph Char Limit:</b> <code>{telegraph_limit}</code>"
            )
            await message.edit_text(settings_text)
            return

        if sub_command == "max_tokens":
            if len(command) > 2:
                value = command[2]
                if value.lower() == 'clear':
                    db.set("custom.gemini", "max_tokens", None)
                    await message.edit_text("<b>Gemini max_tokens setting cleared.</b>")
                else:
                    try:
                        max_tokens = int(value)
                        if max_tokens <= 0:
                            await message.edit_text("<b>max_tokens must be a positive integer.</b>")
                        else:
                            db.set("custom.gemini", "max_tokens", max_tokens)
                            await message.edit_text(f"<b>Gemini max_tokens set to:</b> <code>{max_tokens}</code>")
                    except ValueError:
                        await message.edit_text("<b>Invalid number for max_tokens.</b>")
            else:
                max_tokens = db.get("custom.gemini", "max_tokens")
                if max_tokens:
                    await message.edit_text(f"<b>Current max_tokens:</b> <code>{max_tokens}</code>\n"
                                          f"<b>Usage:</b> <code>{prefix}gemini max_tokens [number|clear]</code>")
                else:
                    await message.edit_text(f"<b>max_tokens is not set.</b>\n"
                                          f"<b>Usage:</b> <code>{prefix}gemini max_tokens [number|clear]</code>")
            return

        if sub_command == "prompt":
            if len(command) > 2:
                action = command[2]
                if action == "add":
                    if len(command) > 3:
                        prompt_name = command[3]
                        prompt_text = " ".join(command[4:])
                        if not prompt_text:
                            await message.edit_text(
                                f"<b>Usage:</b> <code>{prefix}gemini prompt add [name] [prompt]</code>"
                            )
                            return
                        prompts = db.get("custom.gemini", "prompts", {})
                        prompts[prompt_name] = prompt_text
                        db.set("custom.gemini", "prompts", prompts)
                        await message.edit_text(
                            f"<b>System prompt '{prompt_name}' added.</b>"
                        )
                    else:
                        await message.edit_text(
                            f"<b>Usage:</b> <code>{prefix}gemini prompt add [name] [prompt]</code>"
                        )
                    return
                if action == "del":
                    if len(command) > 3:
                        prompt_name = command[3]
                        prompts = db.get("custom.gemini", "prompts", {})
                        if prompt_name in prompts:
                            del prompts[prompt_name]
                            db.set("custom.gemini", "prompts", prompts)
                            await message.edit_text(
                                f"<b>System prompt '{prompt_name}' deleted.</b>"
                            )
                        else:
                            await message.edit_text(
                                f"<b>System prompt '{prompt_name}' not found.</b>"
                            )
                    else:
                        await message.edit_text(
                            f"<b>Usage:</b> <code>{prefix}gemini prompt del [name]</code>"
                        )
                    return
                if action == "list":
                    prompts = db.get("custom.gemini", "prompts", {})
                    if prompts:
                        response_text = "**Available system prompts:**\n\n"
                        for name, content in prompts.items():
                            response_text += f"• `{name}`:\n> {content.replace(chr(10), chr(10) + '> ')}\n"
                        await message.edit_text(response_text, parse_mode=enums.ParseMode.MARKDOWN)
                    else:
                        await message.edit_text("**No system prompts saved.**")
                    return
                if action == "set":
                    if len(command) > 3:
                        prompt_name = command[3]
                        prompts = db.get("custom.gemini", "prompts", {})
                        if prompt_name in prompts:
                            db.set("custom.gemini", "active_prompt", prompt_name)
                            await message.edit_text(
                                f"<b>Active system prompt set to:</b> <code>{prompt_name}</code>"
                            )
                        else:
                            await message.edit_text(
                                f"<b>System prompt '{prompt_name}' not found.</b>"
                            )
                    else:
                        await message.edit_text(
                            f"<b>Usage:</b> <code>{prefix}gemini prompt set [name]</code>"
                        )
                    return
            await message.edit_text(
                f"<b>Usage:</b> <code>{prefix}gemini prompt [add|del|list|set]</code>"
            )
            return

        if sub_command == "context":
            if len(command) > 2:
                action = command[2]
                if action == "on":
                    db.set("custom.gemini", "context_on", True)
                    await message.edit_text("<b>Gemini context is now ON.</b>")
                elif action == "off":
                    db.set("custom.gemini", "context_on", False)
                    await message.edit_text("<b>Gemini context is now OFF.</b>")
                elif action == "clear":
                    user_id = message.from_user.id
                    async with _chat_lock:
                        if user_id in chat_history:
                            del chat_history[user_id]
                        if user_id in last_interaction_time:
                            del last_interaction_time[user_id]
                    await message.edit_text("<b>Gemini chat history cleared.</b>")
                elif action == "show":
                    user_id = message.from_user.id
                    user_chat_history = chat_history.get(user_id, [])
                    if user_chat_history:
                        response_text = "**Current chat history:**\n\n"
                        for item in user_chat_history:
                            role = item.role.capitalize()
                            
                            text_parts = [p.text for p in item.parts if hasattr(p, 'text') and p.text]
                            
                            # Correctly check for actual image data
                            has_image = any(
                                hasattr(p, 'inline_data') and p.inline_data and p.inline_data.data 
                                for p in item.parts
                            )

                            if text_parts:
                                full_content = " ".join(text_parts)
                            elif has_image:
                                full_content = "[Image]"
                            else:
                                full_content = "[Empty Message]"

                            response_text += f"**{role}:**\n> {full_content.replace(chr(10), chr(10) + '> ')}\n"
                        await message.edit_text(response_text, parse_mode=enums.ParseMode.MARKDOWN)
                    else:
                        await message.edit_text("**Chat history is empty.**")
                elif action == "expire":
                    if len(command) > 3:
                        try:
                            minutes = int(command[3])
                            if minutes <= 0:
                                await message.edit_text("<b>Expiration time must be a positive integer.</b>")
                            else:
                                db.set("custom.gemini", "context_expiration_minutes", minutes)
                                global context_expiration_minutes
                                context_expiration_minutes = minutes
                                await message.edit_text(f"<b>Gemini context expiration set to {minutes} minutes.</b>")
                        except ValueError:
                            await message.edit_text("<b>Invalid number for minutes.</b>")
                    else:
                        current_expiry = db.get("custom.gemini", "context_expiration_minutes", 5)
                        await message.edit_text(f"<b>Current expiration time is {current_expiry} minutes.</b>\n"
                                              f"<b>Usage:</b> <code>{prefix}gemini context expire [minutes]</code>")
                    return
                else:
                    await message.edit_text(
                        f"<b>Usage:</b> <code>{prefix}gemini context [on|off|clear|show|expire]</code>"
                    )
            else:
                is_on = db.get("custom.gemini", "context_on", False)
                status = "ON" if is_on else "OFF"
                current_expiry = db.get("custom.gemini", "context_expiration_minutes", 5)
                await message.edit_text(f"<b>Gemini context is currently {status}.</b>\n"
                                      f"<b>Expiration time is {current_expiry} minutes.</b>")
            return

    # Fallback to default behavior if no subcommand matches
    await _ask_gemini(client, message)



modules_help["gemini"] = {
    "gemini [prompt]*": "Ask questions with Gemini AI (can reply to text or image).",
    "gemini imgen [prompt]": "Generate an image or reply to an image to edit it.",
    "gemini settings": "Show the current Gemini settings.",
    "gemini telegraph [on|off]": "Toggle Telegraph posting for long messages.",
    "gemini telegraph_name [name]": "Set the short name for Telegraph.",
    "gemini telegraph_limit [number|clear]": "Set a character limit to auto-post to Telegraph.",
    "gemini model set [model_name]": "Set the Gemini model to use.",
    "gemini model list": "List all available Gemini models.",
    "gemini max_tokens [number|clear]": "Set or clear the max output tokens for Gemini.",
    "gemini prompt add [name] [prompt]": "Add a new system prompt.",
    "gemini prompt del [name]": "Delete a system prompt.",
    "gemini prompt list": "List all saved system prompts.",
    "gemini prompt set [name]": "Set the active system prompt.",
    "gemini context [on|off|clear|show|expire]": "Manage chat history context.",
    "gemini context expire [minutes]": "Set context expiration time in minutes. Default is 5.",
}
