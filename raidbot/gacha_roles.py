from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import discord

from .gacha import GACHA_ASSETS_DIR, PROJECT_ROOT

log = logging.getLogger(__name__)

ROLE_REWARDS_PATH = PROJECT_ROOT / "config" / "gacha_role_rewards.json"

_DEFAULT_REWARDS: tuple[dict[str, Any], ...] = (
    {
        "id": "ludik",
        "name": "Лудик",
        "milestone": 50,
        "image": "ludik.png",
        "color": 0xFF56D1,
        "description": "Гарантированная роль за 50 круток.",
    },
    {
        "id": "gigacha",
        "name": "Гигача",
        "milestone": 80,
        "image": "gigacha.png",
        "color": 0x227BF4,
        "description": "Гарантированная роль за 80 круток.",
    },
    {
        "id": "ludik-korol",
        "name": "Лудик король",
        "milestone": 150,
        "image": "ludik-korol.png",
        "color": 0xC0BE23,
        "description": "Гарантированная роль за 150 круток.",
    },
)


class RoleRewardError(RuntimeError):
    """Raised when a guaranteed gacha role cannot be granted."""


@dataclass(frozen=True)
class RoleGrant:
    reward: dict[str, Any]
    role: discord.Role
    already_had: bool = False


def _normalize_reward(raw: dict[str, Any]) -> dict[str, Any]:
    reward_id = str(raw.get("id", "")).strip()
    name = str(raw.get("name", "")).strip()
    if not reward_id or not name:
        raise RoleRewardError("У награды должны быть id и название.")
    try:
        milestone = int(raw.get("milestone", 0))
    except (TypeError, ValueError) as exc:
        raise RoleRewardError("Порог круток должен быть числом.") from exc
    if milestone < 1:
        raise RoleRewardError("Порог круток должен быть положительным.")
    image = str(raw.get("image", "")).strip()
    if image and Path(image).name != image:
        raise RoleRewardError("Имя картинки не должно содержать путь.")
    try:
        color = int(raw.get("color", 0))
    except (TypeError, ValueError):
        color = 0
    if not 0 <= color <= 0xFFFFFF:
        color = 0
    return {
        "id": reward_id,
        "name": name,
        "milestone": milestone,
        "image": image,
        "color": color,
        "description": str(raw.get("description", "")).strip(),
    }


@lru_cache(maxsize=1)
def _load_rewards() -> tuple[dict[str, Any], ...]:
    if not ROLE_REWARDS_PATH.is_file():
        return _DEFAULT_REWARDS

    try:
        payload = json.loads(
            ROLE_REWARDS_PATH.read_text(encoding="utf-8-sig")
        )
    except (OSError, json.JSONDecodeError):
        log.exception("Не удалось прочитать config/gacha_role_rewards.json")
        return _DEFAULT_REWARDS

    raw_rewards = payload.get("rewards") if isinstance(payload, dict) else payload
    if not isinstance(raw_rewards, list):
        return _DEFAULT_REWARDS

    rewards: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    seen_milestones: set[int] = set()
    for raw in raw_rewards:
        if not isinstance(raw, dict):
            continue
        try:
            reward = _normalize_reward(raw)
        except RoleRewardError:
            log.exception("Пропущена некорректная награда-роль: %r", raw)
            continue
        if (
            reward["id"] in seen_ids
            or reward["milestone"] in seen_milestones
        ):
            continue
        seen_ids.add(reward["id"])
        seen_milestones.add(reward["milestone"])
        rewards.append(reward)
    rewards.sort(key=lambda reward: reward["milestone"])
    return tuple(rewards) or _DEFAULT_REWARDS


def role_rewards() -> list[dict[str, Any]]:
    return [dict(reward) for reward in _load_rewards()]


def role_reward_image_path(reward: dict[str, Any]) -> Path | None:
    image = str(reward.get("image") or "").strip()
    if not image:
        return None
    path = (GACHA_ASSETS_DIR / image).resolve()
    try:
        path.relative_to(GACHA_ASSETS_DIR.resolve())
    except ValueError:
        return None
    return path if path.is_file() else None


def pending_role_rewards(profile: dict[str, Any]) -> list[dict[str, Any]]:
    claimed = {
        str(reward_id)
        for reward_id in profile.get("role_rewards", [])
        if reward_id
    }
    total = max(0, int(profile.get("total_pulls", 0)))
    return [
        reward
        for reward in role_rewards()
        if total >= reward["milestone"] and reward["id"] not in claimed
    ]


def role_reward_status(
    profile: dict[str, Any], reward: dict[str, Any]
) -> str:
    claimed = {
        str(reward_id)
        for reward_id in profile.get("role_rewards", [])
        if reward_id
    }
    total = max(0, int(profile.get("total_pulls", 0)))
    if reward["id"] in claimed:
        return "✅ получено"
    if total >= reward["milestone"]:
        return "⏳ ожидает выдачи"
    return f"осталось {reward['milestone'] - total}"


def build_role_reward_embed(
    reward: dict[str, Any],
    role: discord.Role,
    member: Any,
    *,
    already_had: bool = False,
) -> discord.Embed:
    if already_had:
        lines = [
            f"Роль {role.mention} уже была у вас — награда засчитана."
        ]
    else:
        lines = [
            f"{member.mention} получает роль {role.mention} "
            f"за **{reward['milestone']}** круток!"
        ]
    description = str(reward.get("description") or "").strip()
    if description:
        lines.extend(("", f"*{description}*"))

    embed = discord.Embed(
        title=f"🎉 Роль «{reward['name']}»",
        description="\n".join(lines),
        color=int(reward.get("color") or 0xF1C40F),
    )
    path = role_reward_image_path(reward)
    if path is not None:
        embed.set_image(url=f"attachment://{path.name}")
    embed.set_footer(text="Гача гармонии · Гарантированная награда")
    embed.timestamp = discord.utils.utcnow()
    return embed


def build_role_reward_error_embed(errors: list[str]) -> discord.Embed:
    return discord.Embed(
        title="Не удалось выдать роль",
        description="\n".join(f"• {error}" for error in errors),
        color=discord.Color.red(),
    )


def _role_by_name(guild: Any, name: str) -> Any | None:
    return discord.utils.get(guild.roles, name=name)


def _bot_member(guild: Any) -> Any | None:
    return getattr(guild, "me", None)


def _can_manage_roles(guild: Any) -> bool:
    me = _bot_member(guild)
    if me is None:
        return False
    permissions = getattr(me, "guild_permissions", None)
    return bool(permissions and permissions.manage_roles)


async def _create_role(guild: Any, reward: dict[str, Any]) -> Any:
    if not _can_manage_roles(guild):
        raise RoleRewardError(
            "у бота нет права «Manage Roles». Выдайте его и повторите."
        )
    try:
        return await guild.create_role(
            name=reward["name"],
            colour=discord.Colour(int(reward.get("color") or 0)),
            mentionable=False,
            hoist=False,
            reason="Гача: гарантированная награда",
        )
    except (discord.Forbidden, discord.HTTPException) as exc:
        raise RoleRewardError(
            "не удалось создать роль. Проверьте право «Manage Roles»."
        ) from exc


async def _grant_role(
    guild: Any, member: Any, reward: dict[str, Any]
) -> RoleGrant:
    role = _role_by_name(guild, str(reward["name"]))
    member_role_ids = {
        int(member_role.id)
        for member_role in getattr(member, "roles", [])
        if member_role.id
    }

    if role is not None:
        if int(role.id) in member_role_ids:
            return RoleGrant(reward=reward, role=role, already_had=True)
    else:
        role = await _create_role(guild, reward)

    if role.is_default():
        raise RoleRewardError("нельзя выдать роль @everyone.")
    if role.managed:
        raise RoleRewardError(
            "эта роль управляется интеграцией и не может быть выдана ботом."
        )
    if not _can_manage_roles(guild):
        raise RoleRewardError(
            "у бота нет права «Manage Roles». Выдайте его и повторите."
        )

    me = _bot_member(guild)
    if me is None or me.top_role.position <= role.position:
        raise RoleRewardError(
            "роль находится выше роли бота. Поднимите роль бота выше."
        )

    try:
        await member.add_roles(
            role, reason=f"Гача: награда за {reward['milestone']} круток"
        )
    except (discord.Forbidden, discord.HTTPException) as exc:
        raise RoleRewardError(
            "Discord не разрешил выдать роль. Проверьте иерархию ролей."
        ) from exc
    return RoleGrant(reward=reward, role=role)


async def claim_role_rewards(
    bot: Any, guild: Any, user_id: int, profile: dict[str, Any]
) -> tuple[list[RoleGrant], list[str]]:
    pending = pending_role_rewards(profile)
    if not pending:
        return [], []
    if guild is None:
        return [], ["Сервер не найден."]

    member = guild.get_member(int(user_id))
    if member is None:
        return [], ["Пользователь не найден на сервере."]

    grants: list[RoleGrant] = []
    errors: list[str] = []
    for reward in pending:
        try:
            grant = await _grant_role(guild, member, reward)
        except RoleRewardError as exc:
            errors.append(f"«{reward['name']}»: {exc}")
            continue
        except (discord.DiscordException, ValueError, TypeError):
            log.exception(
                "Не удалось выдать роль %s пользователю %s",
                reward.get("id"),
                user_id,
            )
            errors.append(
                f"«{reward['name']}»: не удалось выдать роль."
            )
            continue

        bot.store.mark_role_reward(
            guild.id, user_id, str(reward["id"])
        )
        grants.append(grant)

    return grants, errors


async def send_role_reward_notices(
    interaction: discord.Interaction,
    grants: list[RoleGrant],
    errors: list[str],
) -> None:
    for grant in grants:
        embed = build_role_reward_embed(
            grant.reward,
            grant.role,
            interaction.user,
            already_had=grant.already_had,
        )
        path = role_reward_image_path(grant.reward)
        try:
            if path is not None:
                await interaction.followup.send(
                    embed=embed,
                    file=discord.File(path, filename=path.name),
                    ephemeral=True,
                )
            else:
                await interaction.followup.send(
                    embed=embed, ephemeral=True
                )
        except (discord.DiscordException, ValueError, TypeError):
            log.exception(
                "Не удалось отправить уведомление о роли %s",
                grant.reward.get("id"),
            )

    if errors:
        try:
            await interaction.followup.send(
                embed=build_role_reward_error_embed(errors),
                ephemeral=True,
            )
        except (discord.DiscordException, ValueError, TypeError):
            log.exception("Не удалось отправить ошибку выдачи роли")
