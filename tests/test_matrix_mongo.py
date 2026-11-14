import asyncio
from types import SimpleNamespace

from bson import ObjectId

from cogs.mongo import MatrixMongo
from game.pokemon import make_pokemon_data


class FakeCollection:
    def __init__(self, result):
        self.result = result
        self.query = None
        self.update_query = None
        self.update = None
        self.upsert = None
        self.documents = []

    async def find_one(self, query):
        self.query = query
        return self.result

    async def update_one(self, query, update, upsert=False):
        self.update_query = query
        self.update = update
        self.upsert = upsert
        if self.result is None and upsert:
            self.result = {"_id": query["_id"], **update.get("$setOnInsert", {}), **update.get("$set", {})}
            return SimpleNamespace(matched_count=0)

        if self.result is not None and all(self.result.get(key) == value for key, value in query.items()):
            self.result.update(update.get("$set", {}))
            for key, value in update.get("$inc", {}).items():
                if "." in key:
                    parent, child = key.split(".", 1)
                    self.result.setdefault(parent, {})[child] = self.result.setdefault(parent, {}).get(child, 0) + value
                else:
                    self.result[key] = self.result.get(key, 0) + value
            for key in update.get("$unset", {}):
                self.result.pop(key, None)
            return SimpleNamespace(matched_count=1)

        return SimpleNamespace(matched_count=0)

    async def find_one_and_update(self, query, update, projection=None, return_document=None):
        if self.result is None or any(
            key in self.result and self.result.get(key) != value
            for key, value in query.items()
            if not isinstance(value, dict)
        ):
            return None
        for key, condition in query.items():
            if isinstance(condition, dict) and "$exists" in condition:
                if (key in self.result) != condition["$exists"]:
                    return None
        before = dict(self.result)
        for key, value in update.get("$set", {}).items():
            self.result[key] = value
        for key, value in update.get("$inc", {}).items():
            self.result[key] = self.result.get(key, 0) + value
        for key in update.get("$unset", {}):
            self.result.pop(key, None)
        return before

    async def replace_one(self, query, document, upsert=False):
        self.result = dict(document)
        return SimpleNamespace(matched_count=1)

    async def insert_one(self, document):
        self.documents.append(document)

    async def delete_one(self, query):
        self.documents = [document for document in self.documents if document.get("_id") != query["_id"]]
        if self.result is not None and all(self.result.get(key) == value for key, value in query.items()):
            self.result = None


class FakeCursor:
    def __init__(self, documents):
        self.documents = documents
        self.sort_args = None

    def sort(self, field, direction):
        self.sort_args = (field, direction)
        return self

    async def to_list(self, length=None):
        return self.documents


class FakePokemonCollection(FakeCollection):
    def __init__(self, documents):
        super().__init__(None)
        self.cursor = FakeCursor(documents)

    def find(self, query):
        self.query = query
        return self.cursor


class FakeDatabase:
    def __init__(self, member_collection, pokemon_collection=None, wild_spawn_collection=None):
        self.member = member_collection
        self.pokemon = pokemon_collection or FakeCollection(None)
        self.wild_spawn = wild_spawn_collection or FakeCollection(None)
        self.command_name = None

    async def command(self, name):
        self.command_name = name
        return {"ok": 1}


class FakeMemberDocument:
    def __init__(self, document):
        self.next_idx = document.get("next_idx", 1)
        self.selected_id = document.get("selected_id")
        self.pokedex = document.get("pokedex", {})
        self.shiny_hunt = document.get("shiny_hunt")
        self.shiny_streak = document.get("shiny_streak", 0)
        self.shiny_calls = []

    def determine_shiny(self, species, *, boost=1):
        self.shiny_calls.append((species.id, boost))
        return True


class FakeMemberModel:
    def __init__(self, collection):
        self.collection = collection
        self.last_document = None

    async def find_one(self, query):
        document = await self.collection.find_one(query)
        if document is None:
            return None
        self.last_document = FakeMemberDocument(document)
        return self.last_document


def test_ping_checks_database_connection():
    database = FakeDatabase(FakeCollection(None))
    store = MatrixMongo(database)

    response = asyncio.run(store.ping())

    assert response == {"ok": 1}
    assert database.command_name == "ping"


def test_fetch_member_queries_existing_member_collection_by_mxid():
    matrix_user_id = "@player:example.org"
    member = {"_id": matrix_user_id, "username": "Player"}
    collection = FakeCollection(member)
    store = MatrixMongo(FakeDatabase(collection))

    result = asyncio.run(store.fetch_member(matrix_user_id))

    assert result == member
    assert collection.query == {"_id": matrix_user_id}


def test_select_pokemon_updates_selected_id_for_collection_number():
    matrix_user_id = "@player:example.org"
    pokemon_id = ObjectId()
    pokemon = {"_id": pokemon_id, "owner_id": matrix_user_id, "owned_by": "user", "idx": 2}
    member_collection = FakeCollection({"_id": matrix_user_id, "selected_id": None})
    pokemon_collection = FakeCollection(pokemon)
    store = MatrixMongo(FakeDatabase(member_collection, pokemon_collection))

    result = asyncio.run(store.select_pokemon(matrix_user_id, "2"))

    assert result == pokemon
    assert pokemon_collection.query == {"owner_id": matrix_user_id, "owned_by": "user", "idx": 2}
    assert member_collection.result["selected_id"] == pokemon_id


def test_select_pokemon_rejects_invalid_collection_number():
    store = MatrixMongo(FakeDatabase(FakeCollection({"_id": "@player:example.org"})))

    result = asyncio.run(store.select_pokemon("@player:example.org", "not-a-number"))

    assert result is None


def test_fetch_pokemon_list_builds_original_pokemon_models():
    matrix_user_id = "@player:example.org"
    document = {"_id": ObjectId(), "owner_id": matrix_user_id, "idx": 1}
    collection = FakePokemonCollection([document])
    store = MatrixMongo(FakeDatabase(FakeCollection(None), collection))

    class FakePokemonModel:
        @staticmethod
        def build_from_mongo(raw_document):
            return {"original_model": raw_document}

    store.models = {"Pokemon": FakePokemonModel}
    store.Pokemon = FakePokemonModel

    result = asyncio.run(store.fetch_pokemon_list(matrix_user_id))

    assert result == [{"original_model": document}]
    assert collection.query == {"owner_id": matrix_user_id, "owned_by": "user"}
    assert collection.cursor.sort_args == ("idx", 1)


def test_ensure_member_upserts_a_fresh_matrix_profile():
    matrix_user_id = "@player:example.org"
    collection = FakeCollection(None)
    store = MatrixMongo(FakeDatabase(collection))

    result = asyncio.run(store.ensure_member(matrix_user_id, "Player"))

    assert collection.update_query == {"_id": matrix_user_id}
    assert collection.update == {"$setOnInsert": {"selected_id": None}, "$set": {"username": "Player"}}
    assert collection.upsert is True
    assert result == {"_id": matrix_user_id, "selected_id": None, "username": "Player"}


def test_start_player_saves_starter_and_selects_it(game_data):
    matrix_user_id = "@player:example.org"
    member_collection = FakeCollection(None)
    pokemon_collection = FakeCollection(None)
    store = MatrixMongo(FakeDatabase(member_collection, pokemon_collection))
    member_model = FakeMemberModel(member_collection)
    store.Member = member_model
    species = game_data.species_by_name("Bulbasaur")

    created = asyncio.run(store.start_player(matrix_user_id, species, "Player"))

    assert created is True
    assert member_collection.result["_id"] == matrix_user_id
    assert member_collection.result["username"] == "Player"
    assert member_collection.result["selected_id"] == pokemon_collection.documents[0]["_id"]
    assert pokemon_collection.documents[0]["owner_id"] == matrix_user_id
    saved_pokemon = pokemon_collection.documents[0]
    assert saved_pokemon["species_id"] == species.id
    assert saved_pokemon["idx"] == 1
    assert saved_pokemon["level"] == 1
    assert saved_pokemon["shiny"] is True
    assert member_model.last_document.shiny_calls == [(species.id, 1)]
    assert member_collection.result["next_idx"] == 2


def test_start_player_preserves_the_members_next_collection_index(game_data):
    matrix_user_id = "@player:example.org"
    member_collection = FakeCollection({"_id": matrix_user_id, "selected_id": None, "next_idx": 8})
    pokemon_collection = FakeCollection(None)
    store = MatrixMongo(FakeDatabase(member_collection, pokemon_collection))
    store.Member = FakeMemberModel(member_collection)
    species = game_data.species_by_name("Bulbasaur")

    created = asyncio.run(store.start_player(matrix_user_id, species))

    assert created is True
    assert pokemon_collection.documents[0]["idx"] == 8
    assert member_collection.result["next_idx"] == 9


def test_make_pokemon_data_uses_member_shiny_logic_and_level_eligible_moves(game_data):
    species = game_data.species_by_name("Bulbasaur")
    member = FakeMemberDocument({"next_idx": 1})

    pokemon = make_pokemon_data(
        member,
        species,
        owner_id="@player:example.org",
        idx=1,
        fixed_level=1,
    )

    eligible_moves = {move.move.id for move in species.moves if move.method.level <= 1}
    assert pokemon["shiny"] is True
    assert pokemon["level"] == 1
    assert set(pokemon["moves"]).issubset(eligible_moves)
    assert pokemon["iv_total"] == sum(
        pokemon[f"iv_{stat}"] for stat in ("hp", "atk", "defn", "satk", "sdef", "spd")
    )


def test_start_player_does_not_replace_existing_starter(game_data):
    matrix_user_id = "@player:example.org"
    selected_id = ObjectId()
    member_collection = FakeCollection({"_id": matrix_user_id, "selected_id": selected_id})
    pokemon_collection = FakeCollection(None)
    store = MatrixMongo(FakeDatabase(member_collection, pokemon_collection))
    species = game_data.species_by_name("Bulbasaur")

    created = asyncio.run(store.start_player(matrix_user_id, species))

    assert created is False
    assert member_collection.result["selected_id"] == selected_id
    assert pokemon_collection.documents == []


class FakeBuiltPokemon:
    @staticmethod
    def build_from_mongo(document):
        return SimpleNamespace(shiny=document["shiny"], gender=document["gender"], idx=document["idx"], raw=document)


def test_set_wild_spawn_replaces_the_previous_room_spawn():
    wild_collection = FakeCollection({"_id": "!room", "species_id": 1, "gender": "male"})
    store = MatrixMongo(FakeDatabase(FakeCollection(None), wild_spawn_collection=wild_collection))

    previous = asyncio.run(store.set_wild_spawn("!room", 2, "female"))

    assert previous["species_id"] == 1
    assert wild_collection.result["species_id"] == 2
    assert wild_collection.result["gender"] == "female"


def test_catch_wild_spawn_saves_original_pokemon_and_awards_pokedex_entry(game_data):
    matrix_user_id = "@player:example.org"
    member_collection = FakeCollection({
        "_id": matrix_user_id,
        "selected_id": ObjectId(),
        "next_idx": 2,
        "pokedex": {},
        "shiny_hunt": None,
    })
    pokemon_collection = FakeCollection(None)
    wild_collection = FakeCollection({"_id": "!room", "species_id": 1, "gender": "male"})
    store = MatrixMongo(FakeDatabase(member_collection, pokemon_collection, wild_collection))
    store.Member = FakeMemberModel(member_collection)
    store.Pokemon = FakeBuiltPokemon
    store.models = {"Member": store.Member, "Pokemon": store.Pokemon}
    species = game_data.species_by_number(1)

    result = asyncio.run(store.catch_wild_spawn("!room", matrix_user_id, species))

    assert result["pokemon"].idx == 2
    assert result["pokemon"].gender == "male"
    assert result["pokedex_reward"] == 35
    assert member_collection.result["next_idx"] == 3
    assert member_collection.result["pokedex"][str(species.dex_number)] == 1
    assert member_collection.result["balance"] == 35
    assert wild_collection.result is None
    assert len(pokemon_collection.documents) == 1


def test_catch_wild_spawn_refuses_already_claimed_spawn(game_data):
    matrix_user_id = "@player:example.org"
    member_collection = FakeCollection({"_id": matrix_user_id, "selected_id": ObjectId(), "next_idx": 2})
    wild_collection = FakeCollection({
        "_id": "!room",
        "species_id": 1,
        "gender": "male",
        "caught_by": "@other:example.org",
    })
    store = MatrixMongo(FakeDatabase(member_collection, FakeCollection(None), wild_collection))
    store.Member = FakeMemberModel(member_collection)
    store.Pokemon = FakeBuiltPokemon
    store.models = {"Member": store.Member, "Pokemon": store.Pokemon}

    result = asyncio.run(store.catch_wild_spawn("!room", matrix_user_id, game_data.species_by_number(1)))

    assert result is None
    assert store.database.pokemon.documents == []


def test_catch_wild_spawn_does_not_consume_spawn_for_unstarted_player(game_data):
    matrix_user_id = "@player:example.org"
    member_collection = FakeCollection({"_id": matrix_user_id, "selected_id": None, "next_idx": 1})
    wild_collection = FakeCollection({"_id": "!room", "species_id": 1, "gender": "male"})
    store = MatrixMongo(FakeDatabase(member_collection, FakeCollection(None), wild_collection))
    store.Member = FakeMemberModel(member_collection)
    store.Pokemon = FakeBuiltPokemon
    store.models = {"Member": store.Member, "Pokemon": store.Pokemon}

    result = asyncio.run(store.catch_wild_spawn("!room", matrix_user_id, game_data.species_by_number(1)))

    assert result is None
    assert wild_collection.result is not None
    assert "caught_by" not in wild_collection.result
    assert store.database.pokemon.documents == []
