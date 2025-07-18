import asyncio

from pyrogram import Client, filters, enums
from pyrogram.types import Message

from utils.db import db
from utils.misc import modules_help, prefix
from utils.scripts import format_exc, import_library

together = import_library("together", "together")
try:
    InvalidRequestError = together.error.InvalidRequestError
except AttributeError:
    class InvalidRequestError(Exception):
        pass

async def _together_imgen(pyro_client: Client, message: Message):
    prompt = " ".join(message.command[1:])
    if not prompt:
        await message.edit_text(
            f"<b>Usage:</b> <code>{prefix}together [prompt]</code>"
        )
        return

    await message.edit_text("<code>Generating image...</code>")

    try:
        together_client = together.Together(api_key=db.get("custom.together", "api_key"))
        model = db.get("custom.together", "model", "black-forest-labs/FLUX.1-schnell-Free")
        
        params = {
            "prompt": prompt,
            "model": model,
            "n": 1,
            "height": 768,
            "width": 576
        }

        if model == "black-forest-labs/FLUX.1-dev":
            params["steps"] = 10
        else:
            params["steps"] = 4
        
        if model != "black-forest-labs/FLUX.1-schnell-Free":
            params["disable_safety_checker"] = True

        response = await asyncio.to_thread(
            together_client.images.generate, **params
        )
        
        if not response.data or not response.data[0].url:
            await message.edit_text("<b>Image generation failed.</b> The API returned no data, possibly due to content filters or an invalid model.")
            return

        image_url = response.data[0].url

        await pyro_client.send_photo(
            message.chat.id,
            photo=image_url,
            caption=f"**Generated Image**\n**Prompt:**\n> {prompt}\nPowered by Together AI",
            parse_mode=enums.ParseMode.MARKDOWN,
            reply_to_message_id=message.id
        )
        await message.delete()
    except InvalidRequestError as e:
        if "nsfw" in str(e).lower():
            await message.edit_text("<b>Image generation failed:</b> The prompt or result was flagged for containing NSFW content.")
        else:
            await message.edit_text(f"<b>Invalid Request:</b> <code>{format_exc(e)}</code>")
    except Exception as e:
        await message.edit_text(f"An error occurred: {format_exc(e)}")

@Client.on_message(filters.command("together", prefix) & filters.me)
async def together_main(client: Client, message: Message):
    if len(message.command) > 1:
        if message.command[1] == "api_key":
            if len(message.command) > 2:
                api_key = message.command[2]
                db.set("custom.together", "api_key", api_key)
                await message.edit_text(f"<b>Together AI API key set to:</b> <code>{api_key}</code>")
            else:
                await message.edit_text(f"<b>Usage:</b> <code>{prefix}together api_key [key]</code>")
            return
        elif message.command[1] == "model":
            if len(message.command) > 2:
                if message.command[2] == "flux-free":
                    db.set("custom.together", "model", "black-forest-labs/FLUX.1-schnell-Free")
                    await message.edit_text("<b>Model set to:</b> <code>black-forest-labs/FLUX.1-schnell-Free</code>")
                    return
                elif message.command[2] == "flux-schnell":
                    db.set("custom.together", "model", "black-forest-labs/FLUX.1-schnell")
                    await message.edit_text("<b>Model set to:</b> <code>black-forest-labs/FLUX.1-schnell</code>")
                    return
                elif message.command[2] == "flux-dev":
                    db.set("custom.together", "model", "black-forest-labs/FLUX.1-dev")
                    await message.edit_text("<b>Model set to:</b> <code>black-forest-labs/FLUX.1-dev</code>")
                    return
                else:
                    model_name = " ".join(message.command[2:])
                    db.set("custom.together", "model", model_name)
                    await message.edit_text(f"<b>Together AI model set to:</b> <code>{model_name}</code>")
            else:
                current_model = db.get("custom.together", "model", "black-forest-labs/FLUX.1-schnell-Free")
                await message.edit_text(f"<b>Usage:</b> <code>{prefix}together model [model_name]</code>\n\n<b>Current model:</b> <code>{current_model}</code>")
            return
    await _together_imgen(client, message)



modules_help["aimage"] = {
    "together [prompt]": "Generate an image using Together AI.",
    "together api_key [key]": "Set your Together AI API key.",
    "together model [model_name]": "Set the model for image generation.",
    "together flux-free": "Use the FLUX.1-schnell-Free model.",
    "together flux-schnell": "Use the FLUX.1-schnell model.",
    "together flux-dev": "Use the FLUX.1-dev model.",
}
