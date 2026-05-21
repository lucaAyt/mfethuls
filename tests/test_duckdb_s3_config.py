from mfethuls import storage


class FakeDuckDBConnection:
    def __init__(self):
        self.statements = []

    def execute(self, sql, params=None):
        self.statements.append(sql)
        return self

    def fetchall(self):
        return []

    def fetch_df(self):
        raise AssertionError("fetch_df should not be called in this test")

    def unregister(self, name):
        return None

    def register(self, name, relation):
        return None

    def from_parquet(self, storage_path):
        return {"relation": storage_path}


def test_duckdb_query_backend_applies_s3_settings(monkeypatch):
    fake_conn = FakeDuckDBConnection()

    monkeypatch.setenv("MFETHULS_S3_REGION", "nyc3")
    monkeypatch.setenv("MFETHULS_S3_ENDPOINT", "nyc3.digitaloceanspaces.com")
    monkeypatch.setenv("MFETHULS_S3_ACCESS_KEY", "access")
    monkeypatch.setenv("MFETHULS_S3_SECRET_KEY", "secret")

    monkeypatch.setattr(storage.duckdb, "connect", lambda *args, **kwargs: fake_conn)

    backend = storage.DuckDBQueryBackend(db_path=":memory:")
    backend.register_parquet("s3://mybucket/prefix/exp.parquet", table_name="exp")

    assert backend.db_path == ":memory:"
    assert any("LOAD httpfs" in stmt for stmt in fake_conn.statements)
    assert any("CREATE OR REPLACE SECRET do_spaces_secret" in stmt for stmt in fake_conn.statements)
    assert any("REGION 'nyc3'" in stmt for stmt in fake_conn.statements)
    assert any("ENDPOINT 'nyc3.digitaloceanspaces.com'" in stmt for stmt in fake_conn.statements)
    assert any("URL_STYLE 'vhost'" in stmt for stmt in fake_conn.statements)
    assert any("USE_SSL TRUE" in stmt for stmt in fake_conn.statements)
