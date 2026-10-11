"""Replace this fixture for a future backend; lifecycle/ranking expectations stay fixed."""
import pytest
from matn_rag.sqlite import SQLiteRepository


@pytest.fixture
def repository_factory():
    return SQLiteRepository
