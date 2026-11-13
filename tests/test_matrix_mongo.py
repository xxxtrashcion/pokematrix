import asyncio
from types import SimpleNamespace

from bson import ObjectId

from cogs.mongo import MatrixMongo


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
            return SimpleNamespace(matched_count=1)

        return SimpleNamespace(matched_count=0)

    async def insert_one(self, document):
        self.documents.append(document)

    async def delete_one(self, query):
        self.documents = [document for document in self.documents if document["_id"] != query["_id"]]


class FakeDatabase:
    def __init__(self, member_collection, pokemon_collection=None):
        self.member = member_collection
        self.pokemon = pokemon_collection or FakeCollection(None)
        self.command_name = None

    async def command(self, name):
        self.command_name = name
        return {"ok": 1}


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
    species = game_data.species_by_name("Bulbasaur")

    created = asyncio.run(store.start_player(matrix_user_id, species, "Player"))

    assert created is True
    assert member_collection.result["_id"] == matrix_user_id
    assert member_collection.result["username"] == "Player"
    assert member_collection.result["selected_id"] == pokemon_collection.documents[0]["_id"]
    assert pokemon_collection.documents[0]["owner_id"] == matrix_user_id
    assert pokemon_collection.documents[0]["species_id"] == species.id
    assert pokemon_collection.documents[0]["idx"] == 1


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
