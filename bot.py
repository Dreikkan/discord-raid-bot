from __future__ import annotations

import logging
import os
from pathlib import Path

import discord
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv

from raidbot.commands import RaidCog
from raidbot.reminders import ActivityCheckinView, ReminderService
from raidbot.store import Store
from raidbot.views import RaidPanelView

PROJECT_ROOT = Path(__file__).resolve().parent
load_dotenv(PROJECT_ROOT / ".env")

log = logging.getLogger("raidbot")


def _configure_logging() -> None:
    level_name = os.getenv("LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


class RaidBot(commands.Bot):
    def __init__(self, data_path: str | Path) -> None:
        intents = discord.Intents.default()
        intents.members = True
        super().__init__(
            command_prefix="!",
            intents=intents,
            allowed_mentions=discord.AllowedMentions.none(),
        )
        self.store = Store(data_path)
        self.reminders = ReminderService(self)

    async def setup_hook(self) -> None:
        await self.add_cog(RaidCog(self))
        self.add_view(ActivityCheckinView(self))

        for raid in self.store.all_raids():
            view = RaidPanelView(self, raid["id"])
            message_id = raid.get("message_id")
            if message_id is not None:
                self.add_view(view, message_id=int(message_id))
            else:
                self.add_view(view)

        self.reminders.start()
        self.tree.on_error = self.on_app_command_error  # type: ignore[method-assign]
        await self._sync_commands()

    async def _sync_commands(self) -> None:
        guild_id_raw = os.getenv("GUILD_ID", "").strip()
        if guild_id_raw:
            try:
                guild_id = int(guild_id_raw)
            except ValueError:
                log.error("GUILD_ID должен быть числом. Команды не синхронизированы.")
                return

            guild = discord.Object(id=guild_id)
            try:
                synced = await self.tree.sync(guild=guild)
            except discord.HTTPException:
                log.exception("Не удалось синхронизировать команды на сервере")
                return
            log.info("Синхронизировано %s команд на сервере %s", len(synced), guild_id)
            return

        try:
            synced = await self.tree.sync()
        except discord.HTTPException:
            log.exception("Не удалось синхронизировать глобальные команды")
            return
        log.info(
            "Синхронизировано %s глобальных команд. "
            "Чтобы команды появились быстрее, задайте GUILD_ID в .env.",
            len(synced),
        )

    async def on_app_command_error(
        self,
        interaction: discord.Interaction,
        error: Exception,
    ) -> None:
        if isinstance(error, app_commands.MissingPermissions):
            message = "Нужны права «Управлять сервером»."
        elif isinstance(error, app_commands.CheckFailure):
            message = "У вас нет доступа к этой команде."
        elif isinstance(error, app_commands.CommandOnCooldown):
            message = f"Попробуйте позже, осталось {error.retry_after:.1f} сек."
        else:
            original = getattr(error, "original", error)
            log.exception(
                "Ошибка команды %s",
                getattr(interaction.command, "qualified_name", "unknown"),
                exc_info=original,
            )
            message = "Произошла внутренняя ошибка. Попробуйте ещё раз."

        try:
            if interaction.response.is_done():
                await interaction.followup.send(message, ephemeral=True)
            else:
                await interaction.response.send_message(message, ephemeral=True)
        except (discord.HTTPException, discord.NotFound):
            log.exception("Не удалось отправить сообщение об ошибке")

    async def on_ready(self) -> None:
        if self.user:
            log.info("Бот запущен как %s (ID: %s)", self.user, self.user.id)
        log.info("Серверов: %s", len(self.guilds))

    async def close(self) -> None:
        await self.reminders.stop()
        await super().close()


def main() -> None:
    _configure_logging()

    token = os.getenv("DISCORD_TOKEN", "").strip()
    if not token:
        raise SystemExit(
            "DISCORD_TOKEN не задан. Скопируйте .env.example в .env и вставьте токен."
        )

    data_path = Path(os.getenv("DATA_FILE", PROJECT_ROOT / "data" / "store.json"))
    if not data_path.is_absolute():
        data_path = PROJECT_ROOT / data_path
    bot = RaidBot(data_path)
    try:
        bot.run(token, log_handler=None)
    except discord.PrivilegedIntentsRequired as exc:
        raise SystemExit(
            "Включите Server Members Intent: Discord Developer Portal → "
            "ваше приложение → Bot → Privileged Gateway Intents → "
            "Server Members Intent. Без него бот не запустится."
        ) from exc


if __name__ == "__main__":
    main()
