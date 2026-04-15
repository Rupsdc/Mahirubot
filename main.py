import discord
from discord.ext import commands
from discord import app_commands
import os
import json
import asyncio
from deep_translator import GoogleTranslator
from langdetect import detect
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ── Config ────────────────────────────────────────────────────────────────────
TOKEN = os.environ["DISCORD_TOKEN"]
DATA_FILE = "user_languages.json"

# Languages users can pick as their "native language"
SUPPORTED_LANGUAGES = {
    "Japanese 🇯🇵": "ja",
    "Spanish 🇪🇸": "es",
    "French 🇫🇷": "fr",
    "German 🇩🇪": "de",
    "Portuguese 🇧🇷": "pt",
    "Italian 🇮🇹": "it",
    "Dutch 🇳🇱": "nl",
    "Russian 🇷🇺": "ru",
    "Korean 🇰🇷": "ko",
    "Chinese (Simplified) 🇨🇳": "zh-CN",
    "Arabic 🇸🇦": "ar",
    "Hindi 🇮🇳": "hi",
    "Polish 🇵🇱": "pl",
    "Turkish 🇹🇷": "tr",
    "Swedish 🇸🇪": "sv",
    "English 🇬🇧": "en",
}

# ── Persistence ───────────────────────────────────────────────────────────────

def load_user_languages() -> dict:
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r") as f:
            return json.load(f)
    return {}


def save_user_languages(data: dict):
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=2)


user_languages: dict = load_user_languages()  # { "user_id": "ja" }

# ── Bot setup ─────────────────────────────────────────────────────────────────

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)


# ── Translation helpers ───────────────────────────────────────────────────────

def translate(text: str, src: str, dest: str) -> str:
    """Translate text. Returns original on failure."""
    try:
        return GoogleTranslator(source=src, target=dest).translate(text)
    except Exception as e:
        logger.warning(f"Translation failed ({src}→{dest}): {e}")
        return text


def detect_lang(text: str) -> str:
    try:
        return detect(text)
    except Exception:
        return "en"


def is_mostly_english(text: str) -> bool:
    try:
        return detect(text) == "en"
    except Exception:
        return True


def build_translation_embed(
    original: str,
    translated: str,
    src_label: str,
    dest_label: str,
    author: discord.Member,
) -> discord.Embed:
    embed = discord.Embed(color=0x5865F2)
    embed.set_author(name=author.display_name, icon_url=author.display_avatar.url)
    embed.add_field(name=f"Original ({src_label})", value=original[:1024], inline=False)
    embed.add_field(name=f"Translated ({dest_label})", value=translated[:1024], inline=False)
    embed.set_footer(text="🌐 Auto-translated by TranslatorBot")
    return embed


# ── Events ────────────────────────────────────────────────────────────────────

@bot.event
async def on_ready():
    logger.info(f"Logged in as {bot.user} (ID: {bot.user.id})")
    try:
        synced = await bot.tree.sync()
        logger.info(f"Synced {len(synced)} slash command(s)")
    except Exception as e:
        logger.error(f"Failed to sync commands: {e}")


@bot.event
async def on_message(message: discord.Message):
    # Ignore bots and DMs
    if message.author.bot or not message.guild:
        return

    await bot.process_commands(message)

    content = message.content.strip()
    if not content or content.startswith("/"):
        return

    uid = str(message.author.id)
    native_lang = user_languages.get(uid)  # None means English (default)

    # ── Case 1: User has a non-English native language set ────────────────────
    if native_lang and native_lang != "en":
        detected = detect_lang(content)

        if detected == "en":
            # English message → translate to their native language (for them)
            translated = translate(content, "en", native_lang)
            if translated.strip() == content.strip():
                return  # Nothing useful to show
            embed = build_translation_embed(
                content, translated, "English", native_lang.upper(), message.author
            )
            try:
                await message.author.send(
                    content="📨 **Someone just said (translated for you):**",
                    embed=embed,
                )
            except discord.Forbidden:
                pass  # DMs closed — silently ignore

        elif detected == native_lang or detected.startswith(native_lang.split("-")[0]):
            # They wrote in their native language → show English translation in channel
            translated = translate(content, native_lang, "en")
            if translated.strip() == content.strip():
                return
            embed = build_translation_embed(
                content, translated, native_lang.upper(), "English", message.author
            )
            await message.channel.send(embed=embed)

        else:
            # Unknown/third language — translate to English for everyone
            translated = translate(content, "auto", "en")
            if translated.strip() == content.strip():
                return
            embed = build_translation_embed(
                content, translated, detected.upper(), "English", message.author
            )
            await message.channel.send(embed=embed)

    # ── Case 2: Default — just auto-translate any non-English to English ──────
    else:
        detected = detect_lang(content)
        if detected == "en":
            return
        translated = translate(content, "auto", "en")
        if translated.strip() == content.strip():
            return
        embed = build_translation_embed(
            content, translated, detected.upper(), "English", message.author
        )
        await message.channel.send(embed=embed)


# ── Slash Commands ────────────────────────────────────────────────────────────

class LanguageSelect(discord.ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(label=name, value=code)
            for name, code in SUPPORTED_LANGUAGES.items()
        ]
        super().__init__(
            placeholder="Choose your native language…",
            min_values=1,
            max_values=1,
            options=options,
        )

    async def callback(self, interaction: discord.Interaction):
        chosen_code = self.values[0]
        uid = str(interaction.user.id)

        if chosen_code == "en":
            user_languages.pop(uid, None)
            save_user_languages(user_languages)
            await interaction.response.send_message(
                "✅ Your native language has been set to **English** (default). "
                "No personal translations will be sent.",
                ephemeral=True,
            )
        else:
            user_languages[uid] = chosen_code
            save_user_languages(user_languages)
            lang_name = next(n for n, c in SUPPORTED_LANGUAGES.items() if c == chosen_code)
            await interaction.response.send_message(
                f"✅ Native language set to **{lang_name}**!\n\n"
                "• When you write in your language → an English translation appears in the channel.\n"
                "• When others write in English → I'll DM you the translation.\n\n"
                "Make sure your DMs from server members are **open** so I can message you!",
                ephemeral=True,
            )


class LanguageView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=60)
        self.add_item(LanguageSelect())


@bot.tree.command(name="setlanguage", description="Set your native language for automatic translation.")
async def set_language(interaction: discord.Interaction):
    view = LanguageView()
    await interaction.response.send_message(
        "🌐 **Select your native language below.**\n"
        "- Your messages will be auto-translated to English for the channel.\n"
        "- English messages in the channel will be translated to your language via DM.",
        view=view,
        ephemeral=True,
    )


@bot.tree.command(name="mylanguage", description="Check what native language you have set.")
async def my_language(interaction: discord.Interaction):
    uid = str(interaction.user.id)
    code = user_languages.get(uid, "en")
    name = next((n for n, c in SUPPORTED_LANGUAGES.items() if c == code), "English 🇬🇧")
    await interaction.response.send_message(
        f"Your current native language is **{name}** (`{code}`).",
        ephemeral=True,
    )


@bot.tree.command(name="clearlanguage", description="Remove your native language setting (back to English default).")
async def clear_language(interaction: discord.Interaction):
    uid = str(interaction.user.id)
    user_languages.pop(uid, None)
    save_user_languages(user_languages)
    await interaction.response.send_message(
        "✅ Your language preference has been cleared. You're back to the English default.",
        ephemeral=True,
    )


@bot.tree.command(name="translate", description="Manually translate a piece of text.")
@app_commands.describe(text="The text to translate", target="Target language code (e.g. ja, es, fr)")
async def manual_translate(interaction: discord.Interaction, text: str, target: str = "en"):
    await interaction.response.defer(ephemeral=True)
    result = translate(text, "auto", target)
    await interaction.followup.send(
        f"**Translation → `{target}`:**\n{result}",
        ephemeral=True,
    )


@bot.tree.command(name="languages", description="Show all supported language codes.")
async def list_languages(interaction: discord.Interaction):
    lines = "\n".join(f"`{code}` — {name}" for name, code in SUPPORTED_LANGUAGES.items())
    await interaction.response.send_message(
        f"**Supported languages:**\n{lines}",
        ephemeral=True,
    )


# ── Run ───────────────────────────────────────────────────────────────────────
bot.run(TOKEN)
