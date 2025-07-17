# This scripts contains use cases for userbots
# This is used on my Moon-Userbot: https://github.com/The-MoonTg-project/Moon-Userbot
# YOu can check it out for uses example

import io
from datetime import datetime, timedelta

from pyrogram import Client, filters, enums
from pyrogram.types import Message
from pyrogram.errors import MessageTooLong



from PIL import Image

from utils.db import db
from utils.misc import modules_help, prefix
from utils.scripts import format_exc, import_library
from utils.config import gemini_key
from utils.rentry import paste as rentry_paste

genai = import_library("google.generativeai", "google-generativeai")

genai.configure(api_key=gemini_key)

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
                    caption_text = f"**{caption_action} Image**\n\n👤**Prompt:**\n> {processed_prompt}\nPowered by Gemini"

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
        prompt = ""
        parts = command_text.split(maxsplit=1)
        if len(parts) > 1:
            prompt = parts[1]
        elif message.reply_to_message:
            prompt = (
                message.reply_to_message.text
                or message.reply_to_message.caption
                or ""
            )

        image_part = None
        media_to_process = None
        if message.photo:
            media_to_process = message.photo
        elif message.reply_to_message:
            if message.reply_to_message.photo:
                media_to_process = message.reply_to_message.photo
            elif message.reply_to_message.sticker and not message.reply_to_message.sticker.is_animated and not message.reply_to_message.sticker.is_video:
                media_to_process = message.reply_to_message.sticker

        if media_to_process:
            if media_to_process.file_size > 10 * 1024 * 1024:
                await message.edit_text(
                    "<b>Error:</b> <code>Image size is too large (max 10MB)</code>"
                )
                return
            image_stream = await client.download_media(media_to_process, in_memory=True)
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

        global chat_history, last_interaction_time, context_expiration_minutes

        if is_context_on:
            if user_id not in chat_history or \
               (user_id in last_interaction_time and \
                datetime.now() - last_interaction_time[user_id] > timedelta(minutes=context_expiration_minutes)):
                chat_history[user_id] = []
                last_interaction_time[user_id] = datetime.now()

            chat = model.start_chat(history=chat_history[user_id])
            response = await chat.send_message_async(contents)
            chat_history[user_id] = chat.history
            last_interaction_time[user_id] = datetime.now()
        else:
            response = model.generate_content(contents)

        output_text = response.text
        if prompt:
            processed_prompt = prompt.replace('\n', '\n> ')
            question_text = f"👤**Prompt:**\n> {processed_prompt}"
        else:
            question_text = ""

        processed_response = output_text.replace('\n', '\n> ')
        formatted_response = f"🤖**Response:**\n> {processed_response}"

        await message.edit_text(
            f"{question_text}\n{formatted_response}\nPowered by Gemini",
            parse_mode=enums.ParseMode.MARKDOWN,
        )
    except MessageTooLong:
        await message.edit_text(
            "<code>Output is too long... Pasting to rentry...</code>"
        )
        try:
            rentry_url, edit_code = await rentry_paste(
                text=f"{response.text}\n\nPowered by Gemini", return_edit=True
            )
        except RuntimeError:
            await message.edit_text(
                "<b>Error:</b> <code>Failed to paste to rentry</code>"
            )
            return
        await client.send_message(
            "me",
            f"Here's your edit code for Url: {rentry_url}\nEdit code:  <code>{edit_code}</code>",
            disable_web_page_preview=True,
        )
        await message.edit_text(
            f"<b>Output:</b> {rentry_url}\n<b>Note:</b> <code>Edit Code has been sent to your saved messages</code>",
            disable_web_page_preview=True,
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
                if action == "show":
                    model_name = db.get("custom.gemini", "model", "gemini-1.5-flash")
                    await message.edit_text(
                        f"<b>Current Gemini model:</b> <code>{model_name}</code>"
                    )
                    return
            await message.edit_text(
                f"<b>Usage:</b> <code>{prefix}gemini model [set|list|show]</code>"
            )
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
                        response_text = "<b>Available system prompts:</b>\n\n"
                        for name, content in prompts.items():
                            safe_name = name.replace('<', '&lt;').replace('>', '&gt;').replace('&', '&amp;')
                            safe_content = content.replace('<', '&lt;').replace('>', '&gt;').replace('&', '&amp;')
                            response_text += f"• <code>{safe_name}</code>:\n<pre>{safe_content}</pre>\n"
                        await message.edit_text(response_text, parse_mode=enums.ParseMode.HTML)
                    else:
                        await message.edit_text("<b>No system prompts saved.</b>")
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
                    if user_id in chat_history:
                        del chat_history[user_id]
                    if user_id in last_interaction_time:
                        del last_interaction_time[user_id]
                    await message.edit_text("<b>Gemini chat history cleared.</b>")
                elif action == "show":
                    user_id = message.from_user.id
                    user_chat_history = chat_history.get(user_id, [])
                    if user_chat_history:
                        response_text = "<b>Current chat history:</b>\n\n"
                        for item in user_chat_history:
                            role = item.role.capitalize()
                            content_parts = []
                            for part in item.parts:
                                if hasattr(part, 'text') and part.text:
                                    content_parts.append(part.text)
                                if hasattr(part, 'inline_data'):
                                    content_parts.append("[Image]")
                            full_content = " ".join(content_parts)
                            safe_text = full_content.replace('<', '&lt;').replace('>', '&gt;').replace('&', '&amp;')
                            response_text += f"<b>{role}:</b>\n<pre>{safe_text}</pre>\n"
                        await message.edit_text(response_text, parse_mode=enums.ParseMode.HTML)
                    else:
                        await message.edit_text("<b>Chat history is empty.</b>")
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
    "gemini [prompt]*": "Ask questions with Gemini Ai (can reply to text or image).",
    "gemini imgen [prompt]": "Generate an image or reply to an image to edit it.",
    "gemini model set [model_name]": "Set the Gemini model to use.",
    "gemini model list": "List all available Gemini models.",
    "gemini model show": "Show the current Gemini model.",
    "gemini prompt add [name] [prompt]": "Add a new system prompt.",
    "gemini prompt del [name]": "Delete a system prompt.",
    "gemini prompt list": "List all saved system prompts.",
    "gemini prompt set [name]": "Set the active system prompt.",
    "gemini context [on|off|clear|show|expire]": "Manage chat history context.",
    "gemini context expire [minutes]": "Set context expiration time in minutes. Default is 5.",
}
