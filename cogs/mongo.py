from __future__ import annotations

from enum import Enum
import math
import pickle
import random
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any, Optional

import discord
import pymongo
from bson.objectid import ObjectId
from discord.ext import commands
from motor.motor_asyncio import AsyncIOMotorClient
from suntime import Sun
from umongo import Document, EmbeddedDocument, Instance, MixinDocument, fields

from cogs.incenses import DEFAULT_INTERVAL, Incense
from data import models
from helpers import constants
from helpers.genders import generate_gender
from game.pokemon import iv_percent_to_total, make_pokemon_data, random_iv, random_nature
from game.pokedex import get_pokedex_milestones
from game.spawning import pokedex_reward, rolls_gigantamax

# Instance


def iv_total_to_percent(total_iv: int, *, round_to: Optional[int] = 2) -> float:
    return round(total_iv / 186 * 100, round_to)


def calc_stat(pokemon, stat):
    base = getattr(pokemon.species.base_stats, stat)
    iv = getattr(pokemon, f"iv_{stat}")
    return math.floor(
        ((2 * base + iv + 5) * pokemon.level // 100 + 5) * constants.NATURE_MULTIPLIERS[pokemon.nature][stat]
    )


class PokemonBase(MixinDocument):
    class Meta:
        strict = False
        abstract = True

    # General
    id = fields.ObjectIdField(attribute="_id")
    timestamp = fields.DateTimeField(default=datetime.utcnow)
    owner_id = fields.StringField(required=True)
    idx = fields.IntegerField(required=True)

    # Details
    species_id = fields.IntegerField(required=True)
    level = fields.IntegerField(required=True)
    xp = fields.IntegerField(required=True)
    nature = fields.StringField(required=True)
    shiny = fields.BooleanField(required=True)
    _gender = fields.StringField(attribute="gender", default=None)

    # Stats
    iv_hp = fields.IntegerField(required=True)
    iv_atk = fields.IntegerField(required=True)
    iv_defn = fields.IntegerField(required=True)
    iv_satk = fields.IntegerField(required=True)
    iv_sdef = fields.IntegerField(required=True)
    iv_spd = fields.IntegerField(required=True)

    iv_total = fields.IntegerField(required=False)

    # Customization
    nickname = fields.StringField(default=None)
    favorite = fields.BooleanField(default=False)
    held_item = fields.IntegerField(default=None)
    moves = fields.ListField(fields.IntegerField, default=list)
    has_color = fields.BooleanField(default=False)
    color = fields.IntegerField(default=None)

    _hp = None
    ailments = None
    stages = None

    def __format__(self, spec):

        # Default specification
        if "D" in spec or not spec:
            spec += "lPg"

        name = ""

        if "!s" not in spec and self.shiny:
            name += "✨ "

        if "l" in spec:
            name += f"Level {self.level} "

        elif "L" in spec:
            name += f"L{self.level} "

        if "p" in spec:
            name += f"{self.iv_percentage:.2%} "

        if "i" in spec and self.bot.sprites.status:
            sprite = self.bot.sprites.get(self.species, shiny=self.shiny)
            name = sprite + " " + name

        if "!G" not in spec and self.species.is_gmax:
            name += f"{self.bot.sprites['gmax']} "

        name += str(self.species)

        if "g" in spec:
            name += f"{self.gender_icon}"

        if "P" in spec:
            name += f" ({self.iv_percentage:.2%})"

        if "n" in spec and self.nickname is not None:
            name += f' "{self.nickname}"'

        if "f" in spec and self.favorite:
            name += " ❤️"

        if "x" in spec:
            name += f" No. {self.idx}"

        if "X" in spec:
            name += f" (#{self.idx})"

        return name

    def __str__(self):
        return f"{self}"

    @classmethod
    def random(cls, **kwargs):
        ivs = [random_iv() for i in range(6)]
        return cls(
            iv_hp=ivs[0],
            iv_atk=ivs[1],
            iv_defn=ivs[2],
            iv_satk=ivs[3],
            iv_sdef=ivs[4],
            iv_spd=ivs[5],
            iv_total=sum(ivs),
            nature=random_nature(),
            shiny=random.randint(1, 4096) == 1,
            **kwargs,
        )

    @property
    def species(self):
        return self.bot.data.species_by_number(self.species_id)

    @property
    def gender(self) -> str:
        if self._gender is None:
            return generate_gender(self.species, _id=self.id)
        return self._gender

    @property
    def gender_icon(self):
        return constants.GENDER_EMOTES[self.gender.lower()]

    @property
    def image_url(self) -> str:
        return self.species.get_image_url(self.shiny, self.gender)

    @property
    def max_xp(self):
        return 250 + 25 * self.level

    @property
    def max_hp(self):
        if self.species_id == 292:
            return 1
        return (2 * self.species.base_stats.hp + self.iv_hp + 5) * self.level // 100 + self.level + 10

    @property
    def hp(self):
        if self._hp is None:
            return self.max_hp
        return self._hp

    @hp.setter
    def hp(self, value):
        self._hp = value

    @property
    def atk(self):
        return calc_stat(self, "atk")

    @property
    def defn(self):
        return calc_stat(self, "defn")

    @property
    def satk(self):
        return calc_stat(self, "satk")

    @property
    def sdef(self):
        return calc_stat(self, "sdef")

    @property
    def spd(self):
        return calc_stat(self, "spd")

    @property
    def iv_percentage(self):
        return (
            self.iv_hp / 31
            + self.iv_atk / 31
            + self.iv_defn / 31
            + self.iv_satk / 31
            + self.iv_sdef / 31
            + self.iv_spd / 31
        ) / 6

    def get_next_evolution(self, time: Time):
        if self.species.evolution_to is None or self.held_item == 13001:
            return None

        possible = []

        for evo in self.species.evolution_to.items:
            if not isinstance(evo.trigger, models.LevelTrigger):
                continue

            can = True

            if evo.trigger.level and self.level < evo.trigger.level:
                can = False
            if evo.trigger.item and self.held_item != evo.trigger.item_id:
                can = False
            if evo.trigger.move_id and evo.trigger.move_id not in self.moves:
                can = False
            if evo.trigger.move_type_id and not any(
                [self.bot.data.move_by_number(x).type_id == evo.trigger.move_type_id for x in self.moves]
            ):
                can = False
            if evo.trigger.time and evo.trigger.time != time:
                can = False

            if evo.trigger.relative_stats == 1 and self.atk <= self.defn:
                can = False
            if evo.trigger.relative_stats == -1 and self.defn <= self.atk:
                can = False
            if evo.trigger.relative_stats == 0 and self.atk != self.defn:
                can = False
            if evo.trigger.gender and evo.trigger.gender != self.gender:
                can = False
            if evo.trigger.natures and self.nature not in evo.trigger.natures:
                can = False

            if can:
                possible.append(evo.target)

        if len(possible) == 0:
            return None

        return random.choice(possible)

    def can_evolve(self, ctx):
        return self.get_next_evolution() is not None


class Pokemon(PokemonBase, Document):
    class Meta:
        strict = False

    owned_by = fields.StringField(required=True)


class EmbeddedPokemon(PokemonBase, EmbeddedDocument):
    class Meta:
        strict = False


class Member(Document):
    class Meta:
        strict = False

    # General
    id = fields.StringField(attribute="_id")
    username = fields.StringField(attribute="username")
    joined_at = fields.DateTimeField(default=None)
    suspended = fields.BooleanField(default=False)
    suspended_until = fields.DateTimeField(default=datetime.min)
    suspension_reason = fields.StringField(default=None)
    private_room_id = fields.StringField(default=None)
    tos = fields.DateTimeField(default=None)

    # Pokémon
    next_idx = fields.IntegerField(default=1)
    selected_id = fields.ObjectIdField(default=None)
    order_by = fields.StringField(default="number")

    # Pokédex
    pokedex = fields.DictField(fields.StringField(), fields.IntegerField(), default=dict)
    claimed_pokedex_rewards = fields.DictField(fields.StringField(), fields.BooleanField(), default=dict)
    notified_milestones = fields.DictField(fields.StringField(), fields.BooleanField(), default=dict)
    shinies_caught = fields.IntegerField(default=0)
    gmax_caught = fields.IntegerField(default=0)

    # Shop
    balance = fields.IntegerField(default=0)
    premium_balance = fields.IntegerField(default=0)
    redeems = fields.IntegerField(default=0)
    redeems_purchased = fields.DictField(fields.IntegerField(), fields.IntegerField(), default=dict)
    embed_colors = fields.IntegerField(default=0)

    # Shiny Hunt
    shiny_hunt = fields.IntegerField(default=None)
    shiny_streak = fields.IntegerField(default=0)

    # Boosts
    boost_expires = fields.DateTimeField(default=datetime.min)
    shiny_charm_expires = fields.DateTimeField(default=datetime.min)

    # Voting
    last_voted_on = fields.DictField(fields.StringField(), fields.DateTimeField(), default=dict)
    need_vote_reminder_on = fields.DictField(fields.StringField(), fields.BooleanField())
    vote_total = fields.IntegerField(default=0)
    vote_streak = fields.IntegerField(default=0)
    gifts_normal = fields.IntegerField(default=0)
    gifts_great = fields.IntegerField(default=0)
    gifts_ultra = fields.IntegerField(default=0)
    gifts_master = fields.IntegerField(default=0)

    # Settings
    show_balance = fields.BooleanField(default=True)
    silence = fields.BooleanField(default=False)
    catch_mention = fields.BooleanField(default=True)
    confirm_mention = fields.BooleanField(default=True)
    catch_ivs = fields.BooleanField(default=True)
    bold_ids = fields.BooleanField(default=False)

    # Quests
    badges = fields.DictField(fields.StringField(), fields.BooleanField(), default=dict)
    quest_progress = fields.DictField(fields.StringField(), fields.IntegerField(), default=dict)

    # Events
    halloween_tickets = fields.IntegerField(default=0)
    halloween_tickets_2021 = fields.IntegerField(default=0)
    hquests = fields.DictField(fields.StringField(), fields.BooleanField(), default=dict)
    hquest_progress = fields.DictField(fields.StringField(), fields.IntegerField(), default=dict)
    halloween_badge = fields.BooleanField(default=False)
    msf_notified = fields.BooleanField(default=False)
    msf_donated_amount = fields.IntegerField(default=0)
    christmas_boxes_nice = fields.IntegerField(default=0)
    christmas_boxes_naughty = fields.IntegerField(default=0)
    christmas_boxes_nice_opened = fields.IntegerField(default=0)
    christmas_boxes_naughty_opened = fields.IntegerField(default=0)
    valentines_purchased = fields.IntegerField(default=0)
    valentines_purchased_2023 = fields.IntegerField(default=0)
    anniversary_boxes = fields.IntegerField(default=0)
    bingos_awarded = fields.IntegerField(default=0)
    halloween_tickets_2022 = fields.IntegerField(default=0)

    christmas_coins_2022 = fields.IntegerField(default=0)
    christmas_boxes_2022_random = fields.IntegerField(default=0)
    christmas_boxes_2022_pokemon = fields.IntegerField(default=0)
    christmas_boxes_2022_currency = fields.IntegerField(default=0)
    christmas_boxes_2022_event = fields.IntegerField(default=0)
    christmas_boxes_2022_santa = fields.IntegerField(default=0)
    christmas_boxes_2022_random_opened = fields.IntegerField(default=0)
    christmas_boxes_2022_pokemon_opened = fields.IntegerField(default=0)
    christmas_boxes_2022_currency_opened = fields.IntegerField(default=0)
    christmas_boxes_2022_event_opened = fields.IntegerField(default=0)
    christmas_boxes_2022_santa_opened = fields.IntegerField(default=0)

    spring_2023_flower_venusaur = fields.IntegerField(default=0)
    spring_2023_flower_shaymin = fields.IntegerField(default=0)
    spring_2023_flower_lilligant = fields.IntegerField(default=0)
    spring_2023_flower_gossifleur = fields.IntegerField(default=0)
    spring_2023_flower_eldegoss = fields.IntegerField(default=0)
    spring_2023_eggs = fields.ListField(fields.DictField(), default=list)

    pride_2023_flag_pride = fields.IntegerField(default=0)
    pride_2023_flag_nonbinary = fields.IntegerField(default=0)
    pride_2023_flag_lesbian = fields.IntegerField(default=0)
    pride_2023_flag_bisexual = fields.IntegerField(default=0)
    pride_2023_flag_transgender = fields.IntegerField(default=0)
    pride_2023_flag_gay = fields.IntegerField(default=0)
    pride_2023_flag_pansexual = fields.IntegerField(default=0)
    pride_2023_buddy = fields.ObjectIdField(default=None)
    pride_2023_buddy_progress = fields.IntegerField(default=0)
    pride_2023_quests = fields.DictField(
        fields.StringField(), fields.ListField(fields.DictField(), default=list), default=dict
    )
    pride_2023_categories = fields.DictField(fields.StringField(), fields.BooleanField(), default=dict)

    summer_2023_fishing_bait = fields.IntegerField(default=0)
    summer_2023_tokens = fields.IntegerField(default=0)

    halloween_2023_satchel_flames = fields.IntegerField(default=0)
    halloween_2023_satchel_shadows = fields.IntegerField(default=0)
    halloween_2023_satchel_foliage = fields.IntegerField(default=0)
    halloween_2023_satchel_snaring = fields.IntegerField(default=0)

    halloween_2023_sigil_flames = fields.IntegerField(default=0)
    halloween_2023_sigil_shadows = fields.IntegerField(default=0)
    halloween_2023_sigil_foliage = fields.IntegerField(default=0)
    halloween_2023_sigil_snaring = fields.IntegerField(default=0)

    halloween_2023_milestone_contribution_searching_golurk = fields.FloatField(default=0.0)
    halloween_2023_milestone_contribution_helping_flames = fields.FloatField(default=0.0)
    halloween_2023_milestone_contribution_helping_shadows = fields.FloatField(default=0.0)
    halloween_2023_milestone_contribution_helping_foliage = fields.FloatField(default=0.0)
    halloween_2023_milestone_contribution_helping_snaring = fields.FloatField(default=0.0)
    halloween_2023_milestone_contribution_saving_golurk = fields.FloatField(default=0.0)

    christmas_2023_xp = fields.IntegerField(default=0)
    christmas_2023_presents = fields.IntegerField(default=0)
    christmas_2023_quests = fields.ListField(fields.DictField(), default=list)
    christmas_2023_quests_notify = fields.BooleanField(default=True)

    valentines_2024_catches = fields.IntegerField(default=0)
    valentines_2024_boxes = fields.IntegerField(default=0)

    easter_2024_quests = fields.ListField(fields.DictField(), default=list)
    easter_2024_boxes = fields.IntegerField(default=0)
    easter_2024_boxes_opened = fields.IntegerField(default=0)
    easter_2024_bingos_awarded = fields.IntegerField(default=0)
    easter_2024_boards_completed = fields.IntegerField(default=0)

    anniversary_2024_orders = fields.DictField(fields.StringField(), fields.DictField(), default=dict)
    anniversary_2024_order_periods = fields.DictField(fields.StringField(), fields.IntegerField(), default=dict)
    anniversary_2024_order_lists = fields.DictField(
        fields.StringField(), fields.ListField(fields.DictField()), default=dict
    )
    anniversary_2024_available_orders = fields.DictField(fields.StringField(), fields.IntegerField(), default=dict)
    anniversary_2024_completed_orders = fields.DictField(fields.StringField(), fields.IntegerField(), default=dict)
    anniversary_2024_donated = fields.IntegerField(default=0)
    anniversary_2024_ingredients = fields.DictField(default=dict)
    anniversary_2024_notify = fields.BooleanField(default=True)

    summer_2024_team = fields.StringField(default=None)
    summer_2024_tickets = fields.IntegerField(default=0)
    summer_2024_tickets_total = fields.IntegerField(default=0)
    summer_2024_current_minisport = fields.DictField(allow_none=True, default=dict)
    summer_2024_minisports_played = fields.IntegerField(default=0)
    summer_2024_points = fields.DictField(fields.StringField(), fields.IntegerField(), default=dict)
    summer_2024_end_points = fields.DictField(fields.StringField(), fields.IntegerField(), default=dict)
    summer_2024_boxes = fields.DictField(fields.StringField(), fields.IntegerField(), default=dict)
    summer_2024_prizes_claimed = fields.BooleanField(default=False)
    summer_2024_prizes_notified = fields.BooleanField(default=False)

    day_of_the_dead_2024_boxes = fields.IntegerField(default=0)
    day_of_the_dead_2024_quests_metadata = fields.DictField(fields.StringField(), fields.StringField(), default=dict)
    day_of_the_dead_2024_encounters = fields.ListField(fields.DictField(), default=list)
    day_of_the_dead_2024_quests = fields.ListField(fields.DictField(), default=list)
    day_of_the_dead_2024_items = fields.DictField(fields.StringField(), fields.IntegerField(), default=dict)
    day_of_the_dead_2024_ofrenda_offerings = fields.ListField(fields.IntegerField(), default=list)
    day_of_the_dead_2024_ofrendas_completed = fields.IntField(default=0)

    christmas_2024_blueprint = fields.IntegerField(default=None)
    christmas_2024_blueprints_completed = fields.IntegerField(default=0)
    christmas_2024_quests = fields.ListField(fields.DictField(), default=list)
    christmas_2024_streak = fields.IntegerField(default=0)
    christmas_2024_board = fields.ListField(fields.ListField(fields.IntegerField()), default=list)
    christmas_2024_boxes = fields.IntegerField(default=0)
    christmas_2024_boxes_total = fields.IntegerField(default=0)
    christmas_2024_story_update = fields.StringField(default=None)

    @property
    def is_suspended(self) -> bool:
        return self.suspended or datetime.utcnow() < self.suspended_until

    @property
    def selected_pokemon(self):
        try:
            return next(filter(lambda x: x.number == int(self.selected), self.pokemon))
        except StopIteration:
            return None

    @property
    def boost_active(self):
        return datetime.utcnow() < self.boost_expires

    @property
    def shiny_charm_active(self):
        return datetime.utcnow() < self.shiny_charm_expires

    @property
    def shiny_hunt_multiplier(self):
        return 1 + math.sqrt(self.shiny_streak) / 7

    def determine_shiny(self, species, *, boost=1):
        chance = 1 / 4096 * boost
        if self.shiny_charm_active:
            chance *= 1.2
        if self.shiny_hunt == species.dex_number:
            chance *= self.shiny_hunt_multiplier
        return random.random() < chance


class Time(Enum):
    DAWN = "🌅", "dawn"
    DAY = "☀️", "day time"
    DUSK = "🌆", "dusk"
    NIGHT = "🌛", "night time"

    def __init__(self, emoji: str, text: str):
        self.emoji = emoji
        self.text = text

    def __format__(self, format_spec: str) -> str:
        name = self.qname

        if "!e" not in format_spec:
            name += f" {self.emoji}"

        return name

    def __eq__(self, other) -> bool:
        return self.name.casefold() == getattr(other, "name", str(other)).casefold()

    @property
    def qname(self) -> str:
        return self.name.capitalize()

    @classmethod
    def from_time(cls, dt: datetime, *, sunrise: datetime, sunset: datetime) -> Time:
        if sunset < sunrise:
            sunset += timedelta(days=1)

        offset = timedelta(hours=1.5)
        for add_days in range(-1, 2):  # This is necessary because sunrise/set can be previous/current/next day
            new_dt = dt + timedelta(days=add_days)
            if (sunrise - offset) < new_dt < (sunrise + offset):  # 1.5 hours around sunrise
                return cls.DAWN
            elif (sunset - offset) < new_dt < (sunset + offset):  # 1.5 hours around sunset
                return cls.DUSK
            elif sunrise < new_dt < sunset:  # After sunrise and before sunset
                return cls.DAY
        else:
            return cls.NIGHT


class Guild(Document):
    """Matrix Space/community configuration; room identifiers are Matrix room IDs."""

    class Meta:
        strict = False

    id = fields.StringField(attribute="_id")
    channel = fields.StringField(default=None)
    channels = fields.ListField(fields.StringField, default=list)
    silence = fields.BooleanField(default=False)
    display_images = fields.BooleanField(default=True)
    auction_channel = fields.StringField(default=None)

    lat = fields.FloatField(default=37.7790262)
    lng = fields.FloatField(default=-122.4199061)
    loc = fields.StringField(
        default="San Francisco, San Francisco City and County, California, United States of America"
    )

    @property
    def time(self) -> Time:
        sun = Sun(self.lat, self.lng)
        sunrise, sunset = sun.get_sunrise_time(), sun.get_sunset_time()

        now = datetime.now(timezone.utc)
        return Time.from_time(now, sunrise=sunrise, sunset=sunset)

    @property
    def is_day(self):
        return self.time in (Time.DAY, Time.DAWN)


class Channel(Document):
    """Matrix room state, optionally grouped under a Matrix Space."""

    class Meta:
        strict = False

    id = fields.StringField(attribute="_id")
    guild_id = fields.StringField(default=None)
    spawns_remaining = fields.IntegerField(default=0)
    _incense = fields.DictField(attribute="incense", default=dict)

    @property
    def incense(self):
        if self.spawns_remaining > 0:
            return Incense(
                channel_id=self.id,
                spawns_remaining=self.spawns_remaining,
                interval=DEFAULT_INTERVAL,
                old_system=True,
            )
        return Incense(channel_id=self.id, **self._incense)

    @property
    def incense_active(self):
        return (self.spawns_remaining or self.incense.spawns_remaining) > 0


class Counter(Document):
    id = fields.StringField(attribute="_id")
    next = fields.IntegerField(default=0)


class Blacklist(Document):
    id = fields.StringField(attribute="_id")


class Sponsor(Document):
    id = fields.IntegerField(attribute="_id")
    matrix_user_id = fields.StringField(default=None)
    reward_date = fields.DateTimeField()
    reward_tier = fields.IntegerField()


MODEL_NAMES = (
    "PokemonBase",
    "Pokemon",
    "EmbeddedPokemon",
    "Member",
    "Guild",
    "Channel",
    "Counter",
    "Blacklist",
    "Sponsor",
)


def register_models(database, bot_context):
    """Register the original game models against a Mongo database.

    Both the Discord and Matrix persistence adapters use this function so
    they share the same Umongo document definitions. ``bot_context`` must
    provide the services accessed by those models (currently ``data`` for
    species and move lookups).
    """
    instance = Instance(database)
    registered = {}

    for model_name in MODEL_NAMES:
        model = instance.register(globals()[model_name])
        model.bot = bot_context
        registered[model_name] = model

    return registered


class MatrixMongo:
    def __init__(self, database, client=None, game_data=None):
        self.database = database
        self.client = client
        self.models = {}

        if game_data is not None:
            # The original models need access to the shared species/move data,
            # but they should not depend on a Discord bot instance.
            self.model_context = SimpleNamespace(data=game_data)
            self.models = register_models(database, self.model_context)
            for model_name, model in self.models.items():
                setattr(self, model_name, model)

    @classmethod
    def connect(cls, uri: str, database_name: str, game_data=None):
        client = AsyncIOMotorClient(uri)
        return cls(client[database_name], client, game_data=game_data)

    async def ping(self):
        return await self.database.command("ping")

    async def fetch_member(self, matrix_user_id: str):
        return await self.database.member.find_one({"_id": matrix_user_id})

    async def fetch_selected_pokemon(self, matrix_user_id: str):
        """Load the original member and their currently selected Pokémon."""
        if not self.models:
            raise RuntimeError("MatrixMongo must register the original game models before loading selected Pokémon.")

        member = await self.Member.find_one({"_id": matrix_user_id})
        if member is None or member.selected_id is None:
            return member, None

        pokemon_document = await self.database.pokemon.find_one(
            {
                "_id": member.selected_id,
                "owner_id": matrix_user_id,
                "owned_by": "user",
            }
        )
        if pokemon_document is None:
            return member, None

        return member, self.Pokemon.build_from_mongo(pokemon_document)

    async def update_pokemon(self, pokemon, update: dict):
        """Apply an update to a Pokémon using the Matrix database handle."""
        if isinstance(pokemon, dict) and "_id" in pokemon:
            pokemon = self.Pokemon.build_from_mongo(pokemon)

        pokemon_id = getattr(pokemon, "id", None)
        if pokemon_id is None:
            pokemon_id = getattr(pokemon, "_id", None)
        if pokemon_id is None:
            raise ValueError("Cannot update a Pokémon without a database id.")

        # Match the original Mongo adapter: lazily persist the model's
        # generated gender when the Pokémon has not had one assigned yet.
        if getattr(pokemon, "_gender", None) is None and "gender" not in update:
            update.setdefault("$set", {})["gender"] = pokemon.gender

        return await self.database.pokemon.update_one({"_id": pokemon_id}, update)

    async def fetch_guild(self, room_id: str):
        """Fetch the original room settings model used by shared game mechanics."""
        if not self.models:
            raise RuntimeError("MatrixMongo must register the original game models before fetching room settings.")

        guild = await self.Guild.find_one({"_id": room_id})
        if guild is not None:
            return guild

        guild = self.Guild(id=room_id)
        try:
            await guild.commit()
        except pymongo.errors.DuplicateKeyError:
            guild = await self.Guild.find_one({"_id": room_id})
        return guild

    async def fetch_pokemon_list(self, matrix_user_id: str):
        cursor = self.database.pokemon.find(
            {
                "owner_id": matrix_user_id,
                "owned_by": "user",
            }
        ).sort("idx", 1)
        documents = await cursor.to_list(length=None)

        # Use the original Umongo Pokemon document whenever the shared game
        # models have been registered. The raw-document fallback keeps the
        # lightweight persistence tests usable without a DataManager.
        if not self.models:
            return documents

        return [self.Pokemon.build_from_mongo(document) for document in documents]

    async def select_pokemon(self, matrix_user_id: str, selection: str):
        """Select one of the player's Pokémon by collection number or latest alias."""
        selection = selection.strip().casefold()
        query = {"owner_id": matrix_user_id, "owned_by": "user"}
        if selection in {"latest", "l", "0"}:
            cursor = self.database.pokemon.find(query).sort("idx", -1)
            documents = await cursor.to_list(length=1)
            document = documents[0] if documents else None
        else:
            try:
                index = int(selection)
            except ValueError:
                return None
            if index < 1:
                return None
            document = await self.database.pokemon.find_one({**query, "idx": index})

        if document is None:
            return None

        result = await self.database.member.update_one(
            {"_id": matrix_user_id},
            {"$set": {"selected_id": document["_id"]}},
        )
        if result.matched_count == 0:
            return None

        if self.models:
            return self.Pokemon.build_from_mongo(document)
        return document

    async def ensure_member(self, matrix_user_id: str, username: Optional[str] = None):
        update = {"$setOnInsert": {"selected_id": None}}
        if username is not None:
            update["$set"] = {"username": username}
        await self.database.member.update_one({"_id": matrix_user_id}, update, upsert=True)
        return await self.fetch_member(matrix_user_id)

    async def fetch_wild_spawn(self, room_id: str):
        return await self.database.wild_spawn.find_one({"_id": room_id})

    async def set_wild_spawn(self, room_id: str, species_id: int, gender: str):
        """Replace the room's current wild spawn and return the previous spawn, if any."""
        previous = await self.fetch_wild_spawn(room_id)
        await self.database.wild_spawn.replace_one(
            {"_id": room_id},
            {
                "_id": room_id,
                "species_id": species_id,
                "gender": gender,
                "spawned_at": datetime.utcnow(),
            },
            upsert=True,
        )
        return previous

    async def catch_wild_spawn(self, room_id: str, matrix_user_id: str, species):
        """Atomically claim a room spawn, create its Pokémon, and update Pokédex rewards."""
        if not self.models:
            raise RuntimeError("MatrixMongo must register the original game models before catching Pokémon.")

        claimed = await self.database.wild_spawn.find_one_and_update(
            {
                "_id": room_id,
                "species_id": species.id,
                "caught_by": {"$exists": False},
            },
            {"$set": {"caught_by": matrix_user_id}},
            return_document=pymongo.ReturnDocument.BEFORE,
        )
        if claimed is None:
            return None

        inserted = False
        try:
            member = await self.Member.find_one({"_id": matrix_user_id})
            if member is None or member.selected_id is None:
                return None

            # Match the original Mongo adapter's atomic index reservation.
            index_record = await self.database.member.find_one_and_update(
                {"_id": matrix_user_id},
                {"$inc": {"next_idx": 1}},
                projection={"next_idx": 1},
                return_document=pymongo.ReturnDocument.BEFORE,
            )
            idx = (index_record or {}).get("next_idx", 1)
            pokemon_data = make_pokemon_data(
                member,
                species,
                owner_id=matrix_user_id,
                idx=idx,
                gender=claimed.get("gender"),
            )
            gmax = rolls_gigantamax(species)
            if gmax:
                pokemon_data["species_id"] = species.gmax.id
            pokemon_document = {
                "_id": ObjectId(),
                "timestamp": datetime.utcnow(),
                **pokemon_data,
            }
            await self.database.pokemon.insert_one(pokemon_document)
            inserted = True
            pokemon = self.Pokemon.build_from_mongo(pokemon_document)

            dex_key = str(species.dex_number)
            current_count = (member.pokedex or {}).get(dex_key, 0)
            reward = pokedex_reward(current_count)
            update = {"$inc": {f"pokedex.{dex_key}": 1}}
            increments = update["$inc"]
            if reward:
                increments["balance"] = reward
            if pokemon.shiny:
                increments["shinies_caught"] = 1
            if gmax:
                increments["gmax_caught"] = 1
            if member.shiny_hunt == species.dex_number:
                if pokemon.shiny:
                    update["$set"] = {"shiny_streak": 0}
                else:
                    increments["shiny_streak"] = 1

            await self.database.member.update_one({"_id": matrix_user_id}, update)
            await self.database.wild_spawn.delete_one({"_id": room_id, "caught_by": matrix_user_id})
            return {
                "pokemon": pokemon,
                "pokedex_reward": reward,
                "shiny_hunt": member.shiny_hunt == species.dex_number,
                "gmax": gmax,
            }
        finally:
            # Release the claim only if no Pokémon was inserted. Once saved,
            # keeping the spawn claimed prevents a retry from creating duplicates.
            if not inserted:
                await self.database.wild_spawn.update_one(
                    {"_id": room_id, "caught_by": matrix_user_id},
                    {"$unset": {"caught_by": ""}},
                )

    async def claim_pokedex_milestones(self, matrix_user_id: str):
        """Claim unlocked Pokédex milestones and award their original-game Pokémon."""
        if not self.models:
            raise RuntimeError("MatrixMongo must register the original game models before claiming milestones.")

        member = await self.Member.find_one({"_id": matrix_user_id})
        if member is None:
            return []

        milestones = get_pokedex_milestones(member.pokedex or {}, member.claimed_pokedex_rewards or {})
        claimable = [progress for progress in milestones if progress.unclaimed]
        if not claimable:
            return []

        reward_species = {}
        for progress in claimable:
            species_id = progress.milestone.reward_species_id
            species = self.model_context.data.species_by_number(species_id)
            if species is None:
                raise RuntimeError(f"Pokédex reward Pokémon {species_id} is missing from game data.")
            reward_species[progress.milestone.key] = species

        claim_fields = {
            f"claimed_pokedex_rewards.{progress.milestone.key}": True
            for progress in claimable
        }
        claim_filter = {
            "_id": matrix_user_id,
            **{
                f"claimed_pokedex_rewards.{progress.milestone.key}": {"$ne": True}
                for progress in claimable
            },
        }
        result = await self.database.member.update_one(claim_filter, {"$set": claim_fields})
        if result.matched_count == 0:
            return []

        reservation = await self.database.member.find_one_and_update(
            {"_id": matrix_user_id},
            {"$inc": {"next_idx": sum(progress.milestone.reward_count for progress in claimable)}},
            projection={"next_idx": 1},
            return_document=pymongo.ReturnDocument.BEFORE,
        )
        if reservation is None:
            await self.database.member.update_one(
                {"_id": matrix_user_id, **claim_fields},
                {"$unset": {field: "" for field in claim_fields}},
            )
            return []

        first_idx = reservation.get("next_idx", 1)
        pokemon_documents = []
        reward_rows = []
        next_idx = first_idx
        try:
            for progress in claimable:
                milestone = progress.milestone
                reward_pokemon = []
                for _ in range(milestone.reward_count):
                    pokemon_document = {
                        "_id": ObjectId(),
                        "timestamp": datetime.utcnow(),
                        **make_pokemon_data(
                            member,
                            reward_species[milestone.key],
                            owner_id=matrix_user_id,
                            idx=next_idx,
                            shiny_boost=15,
                        ),
                    }
                    next_idx += 1
                    pokemon_documents.append(pokemon_document)
                    reward_pokemon.append(self.Pokemon.build_from_mongo(pokemon_document))
                reward_rows.append({"milestone": milestone.title, "pokemon": reward_pokemon})

            if pokemon_documents:
                await self.database.pokemon.insert_many(pokemon_documents)
        except Exception:
            if pokemon_documents:
                await self.database.pokemon.delete_many(
                    {"_id": {"$in": [pokemon["_id"] for pokemon in pokemon_documents]}}
                )
            await self.database.member.update_one(
                {"_id": matrix_user_id, **claim_fields},
                {"$unset": {field: "" for field in claim_fields}},
            )
            raise

        return reward_rows

    async def start_player(
        self,
        matrix_user_id: str,
        species: models.Species,
        display_name: Optional[str] = None,
    ) -> bool:
        profile = await self.ensure_member(matrix_user_id, display_name)
        if profile.get("selected_id") is not None:
            return False
        if not hasattr(self, "Member"):
            raise RuntimeError("MatrixMongo must register the original game models before creating a starter.")

        member = await self.Member.find_one({"_id": matrix_user_id})
        if member is None:
            raise RuntimeError(f"Could not load the Matrix player profile for {matrix_user_id}.")

        # Use the same Pokémon-generation rules as the original Mongo adapter.
        # Starter level remains 1, but shiny chance, nature, IVs, gender and
        # level-eligible moves all come from the shared game logic.
        idx = member.next_idx or 1
        pokemon_id = ObjectId()
        pokemon = {
            "_id": pokemon_id,
            "timestamp": datetime.utcnow(),
            **make_pokemon_data(
                member,
                species,
                owner_id=matrix_user_id,
                idx=idx,
                fixed_level=1,
            ),
        }

        await self.database.pokemon.insert_one(pokemon)
        result = await self.database.member.update_one(
            {"_id": matrix_user_id, "selected_id": None},
            {
                "$set": {
                    "selected_id": pokemon_id,
                    "joined_at": datetime.utcnow(),
                    "next_idx": idx + 1,
                }
            },
        )
        if result.matched_count == 0:
            await self.database.pokemon.delete_one({"_id": pokemon_id})
            return False

        return True

    def close(self):
        if self.client is not None:
            self.client.close()


class Mongo(commands.Cog):
    """For database operations."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.client = AsyncIOMotorClient(bot.config.DATABASE_URI, io_loop=bot.loop)
        self.db = self.client[bot.config.DATABASE_NAME]
        registered_models = register_models(self.db, bot)
        for model_name, model in registered_models.items():
            setattr(self, model_name, model)

    @staticmethod
    def _matrix_id(value) -> str:
        identifier = value if isinstance(value, str) else getattr(value, "id", value)
        if identifier is None:
            raise ValueError("A Matrix user or room ID is required.")
        return str(identifier)

    def _member_cache(self):
        return getattr(self.bot, "redis", None)

    async def fetch_member_info(self, member, display_name: Optional[str] = None) -> Member:
        matrix_user_id = self._matrix_id(member)
        display_name = (
            display_name
            or getattr(member, "display_name", None)
            or getattr(member, "name", None)
            or getattr(member, "username", None)
        )
        cache = self._member_cache()
        val = await cache.hget("db:member", matrix_user_id) if cache is not None else None
        if val is None:
            val = await self.Member.find_one({"_id": matrix_user_id}, {"pokemon": 0, "pokedex": 0})
            v = "" if val is None else pickle.dumps(val.to_mongo())
            if cache is not None:
                await cache.hset("db:member", matrix_user_id, v)
        elif len(val) == 0:
            return None
        else:
            val = self.Member.build_from_mongo(pickle.loads(val))

        if val and display_name and val.username != display_name:
            result = await self.update_member(matrix_user_id, {"$set": {"username": display_name}})
            if result.modified_count > 0:
                val.username = display_name

        return val

    async def fetch_member_setting(self, member, setting: str):
        return (await self.Member.find_one({"_id": self._matrix_id(member)}, {setting: 1}))[setting]

    async def fetch_next_idx(self, member, reserve=1):
        matrix_user_id = self._matrix_id(member)
        result = await self.db.member.find_one_and_update(
            {"_id": matrix_user_id},
            {"$inc": {"next_idx": reserve}},
            projection={"next_idx": 1},
        )
        cache = self._member_cache()
        if cache is not None:
            await cache.hdel("db:member", matrix_user_id)
        return result["next_idx"]

    async def reset_idx(self, member, value):
        matrix_user_id = self._matrix_id(member)
        result = await self.db.member.find_one_and_update(
            {"_id": matrix_user_id},
            {"$set": {"next_idx": value}},
            projection={"next_idx": 1},
        )
        cache = self._member_cache()
        if cache is not None:
            await cache.hdel("db:member", matrix_user_id)
        return result["next_idx"]

    async def fetch_pokedex(self, member, start: int, end: int):
        filter_obj = {"claimed_pokedex_rewards": 1, "notified_milestones": 1}

        for i in range(start, end):
            filter_obj[f"pokedex.{i}"] = 1

        return await self.Member.find_one({"_id": self._matrix_id(member)}, filter_obj)

    def fetch_market_list(self, aggregations=[]):
        pipeline = [
            {"$match": {"owned_by": "market"}},
            *aggregations,
        ]
        return self.db.pokemon.aggregate(pipeline, allowDiskUse=True)

    def fetch_auction_list(self, guild, aggregations=[]):
        matrix_space_id = self._matrix_id(guild)
        pipeline = [
            {"$match": {"owned_by": "auction", "auction_data.guild_id": matrix_space_id}},
            *aggregations,
        ]
        return self.db.pokemon.aggregate(pipeline, allowDiskUse=True)

    async def fetch_auction_count(self, guild, aggregations=[]):
        matrix_space_id = self._matrix_id(guild)
        pipeline = [
            {"$match": {"owned_by": "auction", "auction_data.guild_id": matrix_space_id}},
            *aggregations,
            {"$count": "num_matches"},
        ]
        result = await self.db.pokemon.aggregate(pipeline, allowDiskUse=True).to_list(None)

        if len(result) == 0:
            return 0

        return result[0]["num_matches"]

    async def fetch_pokemon_list(self, member, aggregations=[]):
        matrix_user_id = self._matrix_id(member)
        pipeline = [
            {"$match": {"owner_id": matrix_user_id, "owned_by": "user"}},
            *aggregations,
        ]
        async for x in self.db.pokemon.aggregate(pipeline, allowDiskUse=True):
            yield self.Pokemon.build_from_mongo(x)

    async def fetch_pokemon_count(self, member, aggregations=[], *, max_time_ms=None):
        matrix_user_id = self._matrix_id(member)
        kwargs = {"maxTimeMS": max_time_ms} if max_time_ms else {}
        result = await self.db.pokemon.aggregate(
            [
                {"$match": {"owner_id": matrix_user_id, "owned_by": "user"}},
                *aggregations,
                {"$count": "num_matches"},
            ],
            allowDiskUse=True,
            **kwargs,
        ).to_list(None)

        if len(result) == 0:
            return 0

        return result[0]["num_matches"]

    async def fetch_pokedex_count(self, member, aggregations=[]):
        matrix_user_id = self._matrix_id(member)
        result = await self.db.member.aggregate(
            [
                {"$match": {"_id": matrix_user_id}},
                {"$project": {"pokedex": {"$objectToArray": "$pokedex"}}},
                {"$unwind": {"path": "$pokedex"}},
                {"$replaceRoot": {"newRoot": "$pokedex"}},
                *aggregations,
                {"$group": {"_id": "count", "result": {"$sum": 1}}},
            ],
            allowDiskUse=True,
        ).to_list(None)

        if len(result) == 0:
            return 0

        return result[0]["result"]

    async def fetch_pokedex_sum(self, member, aggregations=[]):
        matrix_user_id = self._matrix_id(member)
        result = await self.db.member.aggregate(
            [
                {"$match": {"_id": matrix_user_id}},
                {"$project": {"pokedex": {"$objectToArray": "$pokedex"}}},
                {"$unwind": {"path": "$pokedex"}},
                {"$replaceRoot": {"newRoot": "$pokedex"}},
                *aggregations,
                {"$group": {"_id": "sum", "result": {"$sum": "$v"}}},
            ],
            allowDiskUse=True,
        ).to_list(None)

        if len(result) == 0:
            return 0

        return result[0]["result"]

    async def make_pokemon(
        self,
        member,
        species: models.Species,
        *,
        shiny_boost: Optional[int] = 1,
        min_iv_percent: Optional[float] = 0,  # Minimum IV percentage 0-100
        max_iv_percent: Optional[float] = 100,  # Maximum IV percentage 0-100,
        **kwargs,
    ) -> dict[str, Any]:
        """Function to build a pokémon.

        Parameters
        ----------
        member : cogs.mongo.Member
            The Member mongo Document object representing a member.
            Used to determine shiny and idx.
        species : data.models.Species
            The species that the pokémon shousld be.
        shiny_boost : int
            How much to boost the shiny chance by (default 1).
        min_iv_percent : float
            Minimum total IV the pokémon should have (default 0).
        max_iv_percent : float
            Maximum total IV the pokémon should have (default 100).
        **kwargs
            Any other attribute of the pokémon can be passed in.
            E.g. shiny=True to guarantee shiny.

            You can pass in `member` and `idx` to make it faster as that
            removes the need to fetch them. Especially important for mass
            calls.

        Returns
        -------
        dict[str, Any]
            The dict containing all the data of the new pokémon, which can
            then be inserted into the database using `collection.insert`.
        """

        # Not sure if this instance check is the best way to do this, but isinstance does not work
        is_member_document = getattr(getattr(member, "opts", None), "template", None) == Member
        if not is_member_document:
            member = await self.fetch_member_info(member)

        idx = kwargs.pop("idx", None) or await self.fetch_next_idx(member)
        return make_pokemon_data(
            member,
            species,
            owner_id=self._matrix_id(member),
            idx=idx,
            shiny_boost=shiny_boost,
            min_iv_percent=min_iv_percent,
            max_iv_percent=max_iv_percent,
            **kwargs,
        )

    async def update_member(self, member, update):
        matrix_user_id = self._matrix_id(member)
        result = await self.db.member.update_one({"_id": matrix_user_id}, update)
        cache = self._member_cache()
        if cache is not None:
            await cache.hdel("db:member", matrix_user_id)
        return result

    async def update_pokemon(self, pokemon: Pokemon | dict, update: dict):
        if isinstance(pokemon, dict) and "_id" in pokemon:
            pokemon = self.Pokemon.build_from_mongo(pokemon)
        if hasattr(pokemon, "id"):
            pokemon_id = pokemon.id
        if hasattr(pokemon, "_id"):
            pokemon_id = pokemon._id

        gender_assigned = pokemon._gender is not None
        if not gender_assigned and ("gender" not in update):
            _set = update.setdefault("$set", {})
            _set["gender"] = pokemon.gender

        return await self.db.pokemon.update_one({"_id": pokemon_id}, update)

    async def fetch_pokemon(self, member, idx: int):
        matrix_user_id = self._matrix_id(member)
        if isinstance(idx, ObjectId):
            result = await self.db.pokemon.find_one({"_id": idx, "owned_by": "user"})
            if result is not None and result["owner_id"] != matrix_user_id:
                result = None
        elif idx == -1:
            result = await self.db.pokemon.aggregate(
                [
                    {"$match": {"owner_id": matrix_user_id, "owned_by": "user"}},
                    {"$sort": {"idx": -1}},
                    {"$limit": 1},
                ],
                allowDiskUse=True,
            ).to_list(None)

            if len(result) == 0:
                result = None
            else:
                result = result[0]
        else:
            result = await self.db.pokemon.find_one({"owner_id": matrix_user_id, "idx": idx, "owned_by": "user"})

        if result is None:
            return None

        return self.Pokemon.build_from_mongo(result)

    async def fetch_guild(self, guild):
        matrix_space_id = self._matrix_id(guild)
        g = await self.Guild.find_one({"_id": matrix_space_id})
        if g is None:
            g = self.Guild(id=matrix_space_id)
            try:
                await g.commit()
            except pymongo.errors.DuplicateKeyError:
                pass
        return g

    async def update_guild(self, guild, update):
        return await self.db.guild.update_one({"_id": self._matrix_id(guild)}, update, upsert=True)

    async def fetch_channel(self, channel):
        matrix_room_id = self._matrix_id(channel)
        c = await self.Channel.find_one({"_id": matrix_room_id})
        if c is None:
            c = self.Channel(id=matrix_room_id)
            await c.commit()
        return c

    async def update_channel(self, channel, update):
        return await self.db.channel.update_one({"_id": self._matrix_id(channel)}, update, upsert=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(Mongo(bot))
