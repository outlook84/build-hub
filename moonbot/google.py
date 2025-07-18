from pyrogram import Client, filters, enums
from pyrogram.types import Message
from pyrogram.errors import MessageTooLong

from utils.db import db
from utils.misc import modules_help, prefix
from utils.scripts import format_exc, import_library


# Import the new library
genai = import_library("google.genai", "google-genai")
from google.genai import types


safety_settings=[
    types.SafetySetting(
        category='HARM_CATEGORY_HATE_SPEECH',
        threshold='BLOCK_NONE',
    ),
    types.SafetySetting(
        category='HARM_CATEGORY_DANGEROUS_CONTENT',
        threshold='BLOCK_NONE',
    ),
    types.SafetySetting(
        category='HARM_CATEGORY_HARASSMENT',
        threshold='BLOCK_NONE',
    ),
    types.SafetySetting(
        category='HARM_CATEGORY_CIVIC_INTEGRITY',
        threshold='BLOCK_NONE',
    ),
    types.SafetySetting(
        category='HARM_CATEGORY_SEXUALLY_EXPLICIT',
        threshold='BLOCK_NONE',
    ),
]


async def _gemini_search(client: Client, message: Message):
    """Handles search with Google grounding for the gemini command."""
    try:
        await message.edit_text("<code>Searching...</code>")

        command_text = message.text or message.caption or ""
        prompt_parts = []

        if message.reply_to_message:
            replied_text = (
                message.reply_to_message.text
                or message.reply_to_message.caption
            )
            if replied_text:
                prompt_parts.append(replied_text)

        parts = command_text.split(maxsplit=1)
        if len(parts) > 1:
            command_prompt = parts[1]
            prompt_parts.append(command_prompt)

        prompt = "\n".join(prompt_parts)

        if not prompt:
            await message.edit_text(
                f"<b>Usage: </b><code>{prefix}google search [query]</code>"
            )
            return

        prompt = "\n".join(prompt_parts)

        if not prompt:
            await message.edit_text(
                f"<b>Usage: </b><code>{prefix}google search [query]</code>"
            )
            return

        model_name = db.get("custom.gemini_search", "search_model", "gemini-2.0-flash")

        # List of models that support grounding
        grounding_supported_models = ["gemini-2.5-flash", "gemini-2.5-flash-lite", "gemini-2.0-flash"]

        if model_name not in grounding_supported_models:
            await message.edit_text(
                f"<b>Error:</b> The current model <code>{model_name}</code> does not support Google Search grounding. "
                f"Please set the model to one of the following: {', '.join(grounding_supported_models)}"
            )
            return

        # Use Google Search for grounding
        max_output_tokens = db.get("custom.gemini_search", "max_output_tokens", 1024)

        system_prompt = db.get("custom.gemini_search", "active_prompt")
        if system_prompt:
            prompts = db.get("custom.gemini_search", "prompts", {})
            system_prompt = prompts.get(system_prompt)
        else:
            system_prompt = "You are a helpful AI assistant."

        contents = []
        if prompt:
            contents.append(prompt)

        client = genai.Client(
            vertexai=False,
        )

        config = types.GenerateContentConfig(
            system_instruction=system_prompt,
            safety_settings=safety_settings,
            max_output_tokens=max_output_tokens if max_output_tokens > 0 else None,
            tools=[
            types.Tool(
                google_search=types.GoogleSearch()
            )
        ]

        )
        response = client.models.generate_content(
            model=model_name,
            contents=contents,
            config=config,
        )

        output_text = response.text
        processed_prompt = prompt.replace('\n', '\n> ')
        question_text = f"👤**Search Query:**\n> {processed_prompt}"

        processed_response = output_text.replace('\n', '\n> ')
        formatted_response = f"🤖**Response:**\n> {processed_response}"

        await message.edit_text(
            f"{question_text}\n{formatted_response}\nPowered by Gemini with Google Search",
            parse_mode=enums.ParseMode.MARKDOWN,
        )
    except MessageTooLong:
        await message.edit_text(
            "<b>Error:</b> <code>Output is too long and cannot be displayed.</code>"
        )
    except Exception as e:
        await message.edit_text(f"An error occurred: {format_exc(e)}")


@Client.on_message(filters.command("google", prefix) & filters.me)
async def gemini(client: Client, message: Message):
    command = message.command
    if len(command) > 1:
        sub_command = command[1]

        if sub_command == "config":
            if (len(command) > 2 and command[2] == "show") or len(command) == 2:
                model_name = db.get("custom.gemini_search", "model", "gemini-1.5-flash")
                search_model_name = db.get("custom.gemini_search", "search_model", "gemini-1.5-flash")
                active_prompt = db.get("custom.gemini_search", "active_prompt", "Default")
                context_expiry = db.get("custom.gemini_search", "context_expiration_minutes", 5)
                max_tokens = db.get("custom.gemini_search", "max_output_tokens", 1024)

                await message.edit_text(f"<b>Gemini Search Configuration:</b>\n\n"
                                      f"• **Search Model:** <code>{search_model_name}</code>\n"
                                      f"• **Active Prompt:** <code>{active_prompt}</code>\n"
                                      f"• **Max Tokens:** <code>{max_tokens if max_tokens > 0 else 'Default'}</code>")
                return
            await message.edit_text(
                f"<b>Usage:</b> <code>{prefix}google config</code>"
            )
            return

        if sub_command == "max_tokens":
            if len(command) > 2 and command[2] == "set":
                if len(command) > 3:
                    try:
                        tokens = int(command[3])
                        if tokens < 0:
                            await message.edit_text("<b>Max tokens must be a non-negative integer.</b>")
                        else:
                            db.set("custom.gemini_search", "max_output_tokens", tokens)
                            if tokens == 0:
                                await message.edit_text("<b>Max output tokens limit cleared.</b>")
                            else:
                                await message.edit_text(f"<b>Max output tokens set to {tokens}.</b>")
                    except ValueError:
                        await message.edit_text("<b>Invalid number for max tokens.</b>")
                else:
                    await message.edit_text(
                        f"<b>Usage:</b> <code>{prefix}google max_tokens set [number]</code> (0 to clear)"
                    )
            else:
                await message.edit_text(
                    f"<b>Usage:</b> <code>{prefix}google max_tokens set [number]</code>"
                )
            return
            
        if sub_command == "model":
            if len(command) > 2:
                action = command[2]
                if action == "set":
                    if len(command) > 3:
                        model_name = command[3]
                        db.set("custom.gemini_search", "model", model_name)
                        await message.edit_text(
                            f"<b>Gemini model set to:</b> <code>{model_name}</code>"
                        )
                    else:
                        await message.edit_text(
                            f"<b>Usage:</b> <code>{prefix}google model set [model_name]</code>"
                        )
                    return
                if action == "list":
                    grounding_supported_models = ["gemini-2.5-flash", "gemini-2.5-flash-lite", "gemini-2.0-flash"]
                    await message.edit_text(
                        f"Please set the model to one of the following: {', '.join(grounding_supported_models)}"
                    )
                    return
            await message.edit_text(
                f"<b>Usage:</b> <code>{prefix}google model [set|list]</code>"
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
                                f"<b>Usage:</b> <code>{prefix}google prompt add [name] [prompt]</code>"
                            )
                            return
                        prompts = db.get("custom.gemini_search", "prompts", {})
                        prompts[prompt_name] = prompt_text
                        db.set("custom.gemini_search", "prompts", prompts)
                        await message.edit_text(
                            f"<b>System prompt '{prompt_name}' added.</b>"
                        )
                    else:
                        await message.edit_text(
                            f"<b>Usage:</b> <code>{prefix}google prompt add [name] [prompt]</code>"
                        )
                    return
                if action == "del":
                    if len(command) > 3:
                        prompt_name = command[3]
                        prompts = db.get("custom.gemini_search", "prompts", {})
                        if prompt_name in prompts:
                            del prompts[prompt_name]
                            db.set("custom.gemini_search", "prompts", prompts)
                            await message.edit_text(
                                f"<b>System prompt '{prompt_name}' deleted.</b>"
                            )
                        else:
                            await message.edit_text(
                                f"<b>System prompt '{prompt_name}' not found.</b>"
                            )
                    else:
                        await message.edit_text(
                            f"<b>Usage:</b> <code>{prefix}google prompt del [name]</code>"
                        )
                    return
                if action == "list":
                    prompts = db.get("custom.gemini_search", "prompts", {})
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
                        prompts = db.get("custom.gemini_search", "prompts", {})
                        if prompt_name in prompts:
                            db.set("custom.gemini_search", "active_prompt", prompt_name)
                            await message.edit_text(
                                f"<b>Active system prompt set to:</b> <code>{prompt_name}</code>"
                            )
                        else:
                            await message.edit_text(
                                f"<b>System prompt '{prompt_name}' not found.</b>"
                            )
                    else:
                        await message.edit_text(
                            f"<b>Usage:</b> <code>{prefix}google prompt set [name]</code>"
                        )
                    return
            await message.edit_text(
                f"<b>Usage:</b> <code>{prefix}google prompt [add|del|list|set]</code>"
            )
            return

    # Fallback to default behavior if no subcommand matches
    await _gemini_search(client, message)



modules_help["google"] = {
    "google config": "Show current configurations.",
    "google [query]": "Perform a search with Google Search grounding (for supported models).",
    "google model set [model_name]": "Set the Gemini model for search.",
    "google model list": "List available models that support Google Search grounding.",
    "google config max_tokens [number]": "Set the max output tokens (0 to clear). Default is 1024.",
    "google prompt add [name] [prompt]": "Add a new system prompt.",
    "google prompt del [name]": "Delete a system prompt.",
    "google prompt list": "List all saved system prompts.",
    "google prompt set [name]": "Set the active system prompt.",
}