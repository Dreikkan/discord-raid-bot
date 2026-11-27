from __future__ import annotations

import json
import random
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import discord

from raidbot.gacha import (
    GachaError,
    RARITY_WEIGHTS,
    RollResult,
    gacha_item_defaults,
    image_path,
    normalize_item,
    parse_rarity,
    roll_gacha,
)
from raidbot.gacha_panel import (
    GachaInventoryView,
    GachaPanelView,
    GachaResultView,
    build_gacha_result_embed,
    build_legendary_announcement_content,
    build_legendary_announcement_embed,
)
from raidbot.gacha_roles import (
    build_role_reward_embed,
    claim_role_rewards,
    pending_role_rewards,
    role_reward_image_path,
    role_rewards,
)
from raidbot.gacha_settings import (
    GachaCurrencyAmountModal,
    GachaCurrencyView,
    GachaItemImageSourceView,
    GachaItemImageUploadModal,
    GachaItemView,
    GachaPoolView,
)
from raidbot.store import Store


class FakeBot:
    def __init__(self, store: Store) -> None:
        self.store = store

    def get_guild(self, guild_id: int):
        return None


class GachaItemTests(unittest.TestCase):
    def test_default_pool_contains_legendary_core_with_image(self) -> None:
        items = gacha_item_defaults()
        self.assertEqual(len(items), 35)
        core = next(item for item in items if item["id"] == "core-of-harmony")
        self.assertEqual(core["name"], "Ядро гармонии")
        self.assertEqual(core["rarity"], "legendary")
        self.assertTrue(core["announce"])
        self.assertIsNotNone(image_path(core))

    def test_core_base_chance_is_one_tenth_percent(self) -> None:
        items = gacha_item_defaults()
        legendary = [
            item for item in items if item["rarity"] == "legendary"
        ]
        core = next(item for item in legendary if item["id"] == "core-of-harmony")
        rarity_chance = RARITY_WEIGHTS["legendary"] / sum(
            RARITY_WEIGHTS.values()
        )
        item_chance = core["weight"] / sum(
            item["weight"] for item in legendary
        )
        self.assertAlmostEqual(rarity_chance * item_chance, 0.001, places=6)

    def test_rarity_aliases_are_accepted(self) -> None:
        self.assertEqual(parse_rarity("легендарная"), "legendary")
        self.assertEqual(parse_rarity("ЭПИЧЕСКАЯ"), "epic")
        with self.assertRaises(GachaError):
            parse_rarity("мифическая")

    def test_item_validation_rejects_bad_values(self) -> None:
        with self.assertRaises(GachaError):
            normalize_item({"name": "", "rarity": "common"})
        with self.assertRaises(GachaError):
            normalize_item({"name": "Предмет", "rarity": "common", "weight": 0})
        with self.assertRaises(GachaError):
            normalize_item(
                {"name": "Предмет", "rarity": "common", "image": "../x.png"}
            )


class GachaRollTests(unittest.TestCase):
    def setUp(self) -> None:
        self.items = gacha_item_defaults()

    def test_roll_returns_requested_count(self) -> None:
        results, pity, core_pity = roll_gacha(
            self.items, 10, 0, rng=random.Random(42)
        )
        self.assertEqual(len(results), 10)
        self.assertGreaterEqual(pity, 0)
        self.assertLessEqual(pity, 10)
        self.assertGreaterEqual(core_pity, 0)
        self.assertLessEqual(core_pity, 10)

    def test_pity_guarantees_legendary_at_threshold(self) -> None:
        results, pity, _ = roll_gacha(
            self.items, 1, 79, rng=random.Random(7)
        )
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].item["rarity"], "legendary")
        self.assertTrue(results[0].pity)
        self.assertEqual(pity, 0)

    def test_natural_legendary_resets_pity(self) -> None:
        legendary = next(
            item for item in self.items if item["rarity"] == "legendary"
        )
        results, pity, core_pity = roll_gacha(
            [legendary], 1, 12, rng=random.Random(1)
        )
        self.assertEqual(results[0].item["id"], legendary["id"])
        self.assertFalse(results[0].pity)
        self.assertEqual(pity, 0)
        self.assertEqual(core_pity, 0)

    def test_core_pity_guarantees_core_at_120(self) -> None:
        results, pity, core_pity = roll_gacha(
            self.items, 1, 0, core_pity=119, rng=random.Random(0)
        )
        self.assertEqual(results[0].item["id"], "core-of-harmony")
        self.assertTrue(results[0].core_pity)
        self.assertEqual(pity, 0)
        self.assertEqual(core_pity, 0)

    def test_core_pity_increments_without_core(self) -> None:
        pool = [
            item
            for item in self.items
            if item["id"] != "core-of-harmony"
        ]
        _, _, core_pity = roll_gacha(
            pool, 10, 0, core_pity=5, rng=random.Random(2)
        )
        self.assertEqual(core_pity, 15)

    def test_core_pity_resets_on_natural_core(self) -> None:
        core = next(
            item for item in self.items if item["id"] == "core-of-harmony"
        )
        results, _, core_pity = roll_gacha(
            [core], 1, 0, core_pity=5, rng=random.Random(0)
        )
        self.assertEqual(results[0].item["id"], "core-of-harmony")
        self.assertFalse(results[0].core_pity)
        self.assertEqual(core_pity, 0)

    def test_core_pity_in_ten_pull(self) -> None:
        core = next(
            item for item in self.items if item["id"] == "core-of-harmony"
        )
        common = next(
            item for item in self.items if item["id"] == "griby"
        )
        results, _, core_pity = roll_gacha(
            [core, common],
            10,
            0,
            core_pity=119,
            rng=random.Random(0),
        )
        self.assertEqual(results[0].item["id"], "core-of-harmony")
        self.assertTrue(results[0].core_pity)
        self.assertLessEqual(core_pity, 9)

    def test_empty_pool_is_rejected(self) -> None:
        with self.assertRaises(GachaError):
            roll_gacha([], 1, 0)


class GachaStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.path = Path(self.temporary_directory.name) / "store.json"
        self.store = Store(self.path)

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def test_old_placeholder_pool_is_replaced_and_custom_items_survive(
        self,
    ) -> None:
        old_data = {
            "version": 2,
            "guilds": {
                "1": {
                    "settings_version": 3,
                    "gacha_items": [
                        {
                            "id": "smoldering-coal",
                            "name": "Тлеющий уголь",
                            "rarity": "common",
                            "weight": 100,
                        },
                        {
                            "id": "custom-item",
                            "name": "Мой предмет",
                            "rarity": "rare",
                            "weight": 100,
                        },
                    ],
                }
            },
            "raids": {},
            "profiles": {},
            "activity_events": {},
        }
        self.path.write_text(
            json.dumps(old_data, ensure_ascii=False),
            encoding="utf-8",
        )

        store = Store(self.path)
        settings = store.settings_for(1)
        ids = {item["id"] for item in settings["gacha_items"]}
        self.assertNotIn("smoldering-coal", ids)
        self.assertIn("custom-item", ids)
        self.assertIn("core-of-harmony", ids)
        self.assertEqual(len(settings["gacha_items"]), 36)
        self.assertEqual(settings["gacha_pool_version"], 4)
        core = next(
            item
            for item in settings["gacha_items"]
            if item["id"] == "core-of-harmony"
        )
        self.assertEqual(core["weight"], 8)

    def test_role_reward_marks_are_idempotent(self) -> None:
        self.store.mark_role_reward(1, 10, "ludik")
        self.store.mark_role_reward(1, 10, "ludik")
        profile = self.store.profile_for(1, 10)
        self.assertEqual(profile["role_rewards"], ["ludik"])

        reloaded = Store(self.path)
        self.assertEqual(
            reloaded.profile_for(1, 10)["role_rewards"], ["ludik"]
        )

    def test_gacha_items_can_be_added_edited_and_deleted(self) -> None:
        saved = self.store.save_gacha_item(
            1,
            {
                "name": "Тестовый предмет",
                "description": "Описание",
                "rarity": "rare",
                "weight": 25,
            },
        )
        self.assertEqual(saved["rarity"], "rare")
        self.assertIsNotNone(self.store.find_gacha_item(1, saved["id"]))

        saved["name"] = "Изменённый предмет"
        self.store.save_gacha_item(1, saved)
        self.assertEqual(
            self.store.find_gacha_item(1, saved["id"])["name"],
            "Изменённый предмет",
        )

        self.assertTrue(self.store.delete_gacha_item(1, saved["id"]))
        self.assertIsNone(self.store.find_gacha_item(1, saved["id"]))

    def test_profile_pull_persists_balance_inventory_and_pity(self) -> None:
        self.store.add_currency(1, 10, 500)
        profile = self.store.complete_gacha_pull(
            1,
            10,
            cost=100,
            item_ids=["core-of-harmony", "griby"],
            pity=2,
            core_pity=3,
        )
        self.assertEqual(profile["balance"], 400)
        self.assertEqual(profile["inventory"]["core-of-harmony"], 1)
        self.assertEqual(profile["inventory"]["griby"], 1)
        self.assertEqual(profile["pity"], 2)
        self.assertEqual(profile["core_pity"], 3)
        self.assertEqual(profile["total_pulls"], 2)

        reloaded = Store(self.path)
        restored = reloaded.profile_for(1, 10)
        self.assertEqual(restored["balance"], 400)
        self.assertEqual(restored["inventory"]["core-of-harmony"], 1)
        self.assertEqual(restored["core_pity"], 3)

    def test_activity_reward_is_idempotent_and_expires(self) -> None:
        self.store.register_activity_event(
            555,
            guild_id=1,
            activity_id="party",
            start_at=1000,
            end_at=2000,
        )
        status, amount, balance = self.store.claim_activity_reward(
            555, 42, amount=25, now=1500
        )
        self.assertEqual((status, amount, balance), ("ok", 25, 25))

        status, amount, balance = self.store.claim_activity_reward(
            555, 42, amount=25, now=1600
        )
        self.assertEqual((status, amount, balance), ("already", 0, 25))

        status, amount, balance = self.store.claim_activity_reward(
            555, 43, amount=25, now=2001
        )
        self.assertEqual(status, "ended")

        self.assertEqual(self.store.prune_activity_events(3000), 1)
        self.assertIsNone(self.store.activity_event(555))

    def test_raid_rewards_are_idempotent(self) -> None:
        raid = self.store.create_raid(
            guild_id=1,
            channel_id=2,
            created_by=3,
            title="Рейд",
            description="",
            start_at=1000,
            limits={"tank": 1, "heal": 2, "dd": 7},
            role_emojis={"tank": "1", "heal": "2", "dd": "3"},
        )
        self.store.set_registration(
            raid["id"],
            10,
            role="tank",
            specializations=[],
            display_name="Танк",
            status="main",
        )
        self.store.set_registration(
            raid["id"],
            11,
            role="dd",
            specializations=[],
            display_name="Запас",
            status="bench",
        )
        self.store.set_registration(
            raid["id"],
            12,
            role="dd",
            specializations=[],
            display_name="Отсутствует",
            status="absent",
        )

        awards = self.store.award_raid_rewards(
            raid["id"], main_amount=50, bench_amount=15, now=1000
        )
        self.assertEqual(len(awards), 2)
        self.assertEqual(self.store.profile_for(1, 10)["balance"], 50)
        self.assertEqual(self.store.profile_for(1, 11)["balance"], 15)
        self.assertEqual(self.store.profile_for(1, 12)["balance"], 0)

        again = self.store.award_raid_rewards(
            raid["id"], main_amount=50, bench_amount=15, now=2000
        )
        self.assertEqual(again, [])
        self.assertEqual(self.store.profile_for(1, 10)["balance"], 50)

    def test_old_raid_without_reward_field_is_not_paid_retroactively(self) -> None:
        raid = self.store.create_raid(
            guild_id=1,
            channel_id=2,
            created_by=3,
            title="Старый рейд",
            description="",
            start_at=1000,
            limits={"tank": 1, "heal": 2, "dd": 7},
            role_emojis={"tank": "1", "heal": "2", "dd": "3"},
        )
        self.store.set_registration(
            raid["id"],
            10,
            role="tank",
            specializations=[],
            display_name="Танк",
            status="main",
        )
        del self.store.data["raids"][raid["id"]]["rewards_awarded_at"]
        self.store.save()

        awards = self.store.award_raid_rewards(
            raid["id"], main_amount=50, bench_amount=15, now=2000
        )
        self.assertEqual(awards, [])
        self.assertEqual(self.store.profile_for(1, 10)["balance"], 0)


class RoleRewardTests(unittest.TestCase):
    def test_role_reward_definitions(self) -> None:
        rewards = role_rewards()
        self.assertEqual(
            [reward["milestone"] for reward in rewards],
            [50, 80, 150],
        )
        self.assertEqual(
            [reward["name"] for reward in rewards],
            ["Лудик", "Гигача", "Лудик король"],
        )
        for reward in rewards:
            self.assertIsNotNone(role_reward_image_path(reward))

    def test_pending_role_rewards_follow_total_pulls(self) -> None:
        def pending(total: int, claimed: list[str] | None = None):
            return [
                reward["id"]
                for reward in pending_role_rewards(
                    {
                        "total_pulls": total,
                        "role_rewards": claimed or [],
                    }
                )
            ]

        self.assertEqual(pending(49), [])
        self.assertEqual(pending(50), ["ludik"])
        self.assertEqual(pending(80), ["ludik", "gigacha"])
        self.assertEqual(
            pending(150), ["ludik", "gigacha", "ludik-korol"]
        )
        self.assertEqual(pending(80, ["ludik"]), ["gigacha"])

    def test_role_reward_embed_has_role_and_icon(self) -> None:
        reward = role_rewards()[0]
        role = SimpleNamespace(mention="<@&100>")
        member = SimpleNamespace(mention="<@10>")
        embed = build_role_reward_embed(reward, role, member)
        self.assertIn("Лудик", embed.title)
        self.assertIn("<@&100>", embed.description)
        self.assertEqual(embed.image.url, "attachment://ludik.png")


class FakeRole:
    def __init__(
        self,
        role_id: int,
        name: str,
        position: int = 5,
    ) -> None:
        self.id = role_id
        self.name = name
        self.mention = f"<@&{role_id}>"
        self.position = position
        self.managed = False

    def is_default(self) -> bool:
        return False


class RoleRewardGrantTests(unittest.IsolatedAsyncioTestCase):
    async def test_claim_assigns_role_and_marks_profile(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            store = Store(Path(temporary) / "store.json")
            bot = FakeBot(store)
            role = FakeRole(100, "Лудик")
            member = SimpleNamespace(
                id=10,
                mention="<@10>",
                roles=[],
                add_roles=AsyncMock(),
            )
            guild = SimpleNamespace(
                id=1,
                roles=[role],
                get_member=lambda user_id: member,
                me=SimpleNamespace(
                    guild_permissions=SimpleNamespace(manage_roles=True),
                    top_role=SimpleNamespace(position=10),
                ),
                create_role=AsyncMock(),
            )
            profile = store.profile_for(1, 10)
            profile["total_pulls"] = 50
            store.save()

            grants, errors = await claim_role_rewards(
                bot, guild, 10, profile
            )

            self.assertEqual(errors, [])
            self.assertEqual(len(grants), 1)
            self.assertEqual(grants[0].reward["id"], "ludik")
            member.add_roles.assert_awaited_once()
            self.assertEqual(
                store.profile_for(1, 10)["role_rewards"], ["ludik"]
            )

    async def test_higher_role_removes_previous_role(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            store = Store(Path(temporary) / "store.json")
            bot = FakeBot(store)
            ludik = FakeRole(100, "Лудик")
            gigacha = FakeRole(101, "Гигача")
            member = SimpleNamespace(
                id=10,
                mention="<@10>",
                roles=[ludik],
                add_roles=AsyncMock(),
                remove_roles=AsyncMock(),
            )
            guild = SimpleNamespace(
                id=1,
                roles=[ludik, gigacha],
                get_member=lambda user_id: member,
                me=SimpleNamespace(
                    guild_permissions=SimpleNamespace(manage_roles=True),
                    top_role=SimpleNamespace(position=10),
                ),
                create_role=AsyncMock(),
            )
            profile = store.profile_for(1, 10)
            profile["total_pulls"] = 80
            profile["role_rewards"] = ["ludik"]
            store.save()

            grants, errors = await claim_role_rewards(
                bot, guild, 10, profile
            )

            self.assertEqual(errors, [])
            self.assertEqual(grants[0].reward["id"], "gigacha")
            member.add_roles.assert_awaited_once_with(
                gigacha,
                reason="Гача: награда за 80 круток",
            )
            member.remove_roles.assert_awaited_once_with(
                ludik,
                reason="Гача: заменена более высокой ролью",
            )
            self.assertEqual(
                store.profile_for(1, 10)["role_rewards"],
                ["ludik", "gigacha"],
            )

    async def test_open_cleans_old_role_without_new_pending(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            store = Store(Path(temporary) / "store.json")
            bot = FakeBot(store)
            ludik = FakeRole(100, "Лудик")
            gigacha = FakeRole(101, "Гигача")
            member = SimpleNamespace(
                id=10,
                mention="<@10>",
                roles=[ludik, gigacha],
                add_roles=AsyncMock(),
                remove_roles=AsyncMock(),
            )
            guild = SimpleNamespace(
                id=1,
                roles=[ludik, gigacha],
                get_member=lambda user_id: member,
                me=SimpleNamespace(
                    guild_permissions=SimpleNamespace(manage_roles=True),
                    top_role=SimpleNamespace(position=10),
                ),
                create_role=AsyncMock(),
            )
            profile = store.profile_for(1, 10)
            profile["total_pulls"] = 80
            profile["role_rewards"] = ["ludik", "gigacha"]
            store.save()

            grants, errors = await claim_role_rewards(
                bot, guild, 10, profile
            )

            self.assertEqual(grants, [])
            self.assertEqual(errors, [])
            member.remove_roles.assert_awaited_once_with(
                ludik,
                reason="Гача: заменена более высокой ролью",
            )


class GachaEmbedTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.temporary_directory.name) / "store.json")
        self.bot = FakeBot(self.store)
        self.items = self.store.settings_for(1)["gacha_items"]
        self.core = next(
            item for item in self.items if item["id"] == "core-of-harmony"
        )

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def test_panel_and_pool_views(self) -> None:
        panel = GachaPanelView(self.bot, 1, 10)
        embed = panel.build_embed()
        self.assertIn("Гача гармонии", embed.title)
        self.assertIn("Осколки гармонии", embed.description)
        self.assertIn("До гарантии легендарки", embed.description)
        self.assertIn("До гарантии «Ядра»", embed.description)
        role_field = next(
            field
            for field in embed.fields
            if "Гарантированные роли" in field.name
        )
        self.assertIn("Лудик", role_field.value)
        self.assertIn("Гигача", role_field.value)
        self.assertIn("Лудик король", role_field.value)
        labels = [
            item.label for item in panel.children if hasattr(item, "label")
        ]
        self.assertIn("Крутить ×1", labels)
        self.assertIn("Крутить ×10", labels)

        pool = GachaPoolView(self.bot, 1)
        self.assertEqual(pool.build_embed().title, "🎁 Настройки гачи")
        select = next(
            item for item in pool.children if isinstance(item, discord.ui.Select)
        )
        self.assertEqual(len(select.options), 24)
        pool_labels = [
            item.label for item in pool.children if hasattr(item, "label")
        ]
        self.assertIn("Начислить валюту", pool_labels)

        item_view = GachaItemView(self.bot, 1, "core-of-harmony")
        item_embed = item_view.build_embed()
        self.assertIn("Ядро гармонии", item_embed.title)
        self.assertEqual(
            item_embed.image.url, "attachment://core-of-harmony.png"
        )
        files = item_view.build_files()
        self.assertEqual(files[0].filename, "core-of-harmony.png")
        for file in files:
            file.close()

    def test_result_and_announcement_show_item_image(self) -> None:
        self.store.add_currency(1, 10, 500)
        profile = self.store.complete_gacha_pull(
            1,
            10,
            cost=100,
            item_ids=["core-of-harmony"],
            pity=0,
        )
        result = RollResult(self.core, pity=True)
        embed = build_gacha_result_embed(
            result, profile=profile, page=0, total=1
        )
        self.assertEqual(embed.image.url, "attachment://core-of-harmony.png")
        self.assertIn("Сработала гарантия", embed.description)

        core_guarantee = RollResult(self.core, core_pity=True)
        core_embed = build_gacha_result_embed(
            core_guarantee, profile=profile, page=0, total=1
        )
        self.assertIn("гарантия «Ядра гармонии»", core_embed.description)

        view = GachaResultView(self.bot, 1, 10, [result])
        self.assertEqual(
            view.build_embed().image.url,
            "attachment://core-of-harmony.png",
        )
        files = view.build_files()
        self.assertEqual(files[0].filename, "core-of-harmony.png")
        for file in files:
            file.close()

        common = next(item for item in self.items if item["id"] == "griby")
        multi_view = GachaResultView(
            self.bot,
            1,
            10,
            [RollResult(common), RollResult(self.core)],
        )
        self.assertEqual(multi_view.page, 1)
        self.assertEqual(multi_view.current().item["id"], "core-of-harmony")

        user = SimpleNamespace(mention="<@10>")
        content = build_legendary_announcement_content(user, self.core)
        self.assertIn("<@10>", content)
        self.assertIn("Ядро гармонии", content)

        announcement = build_legendary_announcement_embed(user, self.core)
        self.assertIn("Невероятная удача", announcement.description)
        self.assertIn("Ядро гармонии", announcement.description)
        self.assertEqual(
            announcement.image.url, "attachment://core-of-harmony.png"
        )


class GachaCurrencyTests(unittest.IsolatedAsyncioTestCase):
    async def test_currency_view_and_award_modal(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            store = Store(Path(temporary) / "store.json")
            bot = FakeBot(store)
            view = GachaCurrencyView(bot, 1)
            self.assertIn("Начисление", view.build_embed().title)
            labels = [
                item.label
                for item in view.children
                if hasattr(item, "label")
            ]
            self.assertIn("Выдать всем", labels)

            view.message = SimpleNamespace(id=1)
            modal = GachaCurrencyAmountModal(
                bot, 1, 10, "Игрок", view
            )
            modal.amount_input._value = "500"
            response = SimpleNamespace(
                edit_message=AsyncMock(),
                send_message=AsyncMock(),
            )
            interaction = SimpleNamespace(
                message=SimpleNamespace(id=1),
                user=SimpleNamespace(id=999),
                response=response,
            )

            await modal.on_submit(interaction)

            self.assertEqual(store.profile_for(1, 10)["balance"], 500)
            response.edit_message.assert_awaited_once()
            embed = response.edit_message.await_args.kwargs["embed"]
            self.assertIn("Начислено", embed.description)
            self.assertIn("500", embed.description)

    async def test_award_to_all_server_members(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            store = Store(Path(temporary) / "store.json")

            class FakeMember:
                def __init__(self, member_id: int, bot: bool = False) -> None:
                    self.id = member_id
                    self.bot = bot

            class FakeGuild:
                me = None

                async def fetch_members(self, limit=None):
                    for member in (
                        FakeMember(10),
                        FakeMember(11),
                        FakeMember(12),
                        FakeMember(999, bot=True),
                    ):
                        yield member

            class GuildBot(FakeBot):
                def get_guild(self, guild_id: int):
                    return FakeGuild()

            bot = GuildBot(store)
            view = GachaCurrencyView(bot, 1)
            view.message = SimpleNamespace(id=1)
            modal = GachaCurrencyAmountModal(
                bot,
                1,
                0,
                "всем участникам",
                view,
                all_members=True,
            )
            modal.amount_input._value = "250"
            response = SimpleNamespace(
                defer=AsyncMock(),
                edit_message=AsyncMock(),
                send_message=AsyncMock(),
            )
            followup = SimpleNamespace(send=AsyncMock())
            interaction = SimpleNamespace(
                message=SimpleNamespace(id=1),
                user=SimpleNamespace(id=999),
                response=response,
                followup=followup,
                delete_original_response=AsyncMock(),
            )

            await modal.on_submit(interaction)

            for user_id in (10, 11, 12):
                self.assertEqual(
                    store.profile_for(1, user_id)["balance"], 250
                )
            response.defer.assert_awaited_once()
            followup.send.assert_awaited_once()
            interaction.delete_original_response.assert_awaited_once()
            embed = followup.send.await_args.kwargs["embed"]
            self.assertIn("3", embed.description)
            self.assertIn("750", embed.description)


class GachaCloseTests(unittest.IsolatedAsyncioTestCase):
    async def test_result_and_inventory_close_use_interaction_token(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            store = Store(Path(temporary) / "store.json")
            bot = FakeBot(store)
            core = next(
                item
                for item in store.settings_for(1)["gacha_items"]
                if item["id"] == "core-of-harmony"
            )
            result_view = GachaResultView(
                bot, 1, 10, [RollResult(core)]
            )
            inventory_view = GachaInventoryView(bot, 1, 10)

            for view in (result_view, inventory_view):
                response = SimpleNamespace(
                    is_done=lambda: False,
                    defer=AsyncMock(),
                )
                interaction = SimpleNamespace(
                    response=response,
                    delete_original_response=AsyncMock(),
                )
                await view._close(interaction)
                response.defer.assert_awaited_once()
                interaction.delete_original_response.assert_awaited_once()


class FakeAttachment:
    filename = "new.png"
    size = 3

    async def read(self) -> bytes:
        return b"new"


class GachaImageUploadTests(unittest.IsolatedAsyncioTestCase):
    async def test_upload_modal_saves_image_for_item(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            store = Store(Path(temporary) / "store.json")
            bot = FakeBot(store)
            assets = Path(temporary) / "assets"
            assets.mkdir()

            item_id = "core-of-harmony"
            parent = GachaItemImageSourceView(bot, 1, item_id)
            parent.message = SimpleNamespace(id=1)
            modal = GachaItemImageUploadModal(bot, 1, item_id, parent)
            data = modal.to_dict()
            self.assertEqual(data["components"][0]["type"], 18)
            self.assertEqual(
                data["components"][0]["component"]["type"], 19
            )
            modal.upload._values = [FakeAttachment()]

            response = SimpleNamespace(
                edit_message=AsyncMock(),
                send_message=AsyncMock(),
            )
            interaction = SimpleNamespace(
                message=SimpleNamespace(id=1),
                response=response,
            )

            with (
                patch("raidbot.gacha.GACHA_ASSETS_DIR", assets),
                patch("raidbot.gacha_settings.GACHA_ASSETS_DIR", assets),
            ):
                await modal.on_submit(interaction)

            self.assertTrue((assets / "core-of-harmony.png").is_file())
            saved = store.find_gacha_item(1, item_id)
            assert saved is not None
            self.assertEqual(saved["image"], "core-of-harmony.png")
            response.edit_message.assert_awaited_once()
            attachments = (
                response.edit_message.await_args.kwargs.get("attachments")
                or []
            )
            for file in attachments:
                file.close()


if __name__ == "__main__":
    unittest.main()
