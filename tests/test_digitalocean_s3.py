import os

from mfethuls.storage import S3ParquetStorage


class FakeClient:
    def __init__(self):
        # provide minimal interface used by S3ParquetStorage in other tests
        self.objects = {}

    def put_object(self, **kwargs):
        key = kwargs.get("Key")
        bucket = kwargs.get("Bucket")
        self.objects[(bucket, key)] = kwargs.get("Body")


def test_s3_storage_uses_client_and_endpoint():
    fake = FakeClient()
    endpoint = "https://nyc3.digitaloceanspaces.com"
    s3 = S3ParquetStorage(bucket="mybucket", region="nyc3", client=fake, endpoint_url=endpoint)

    # Ensure constructor stored endpoint and region
    assert s3.endpoint_url == endpoint
    assert s3.region == "nyc3"

    # Check that dataset_paths produces an s3:// URI using the configured bucket
    class E:
        experiment_id = "EXP123"
        sample_id = None
        run_id = None
        instrument_name = "ftir"
        name = "Test Experiment"

    parquet_path, meta_path = s3.dataset_paths(E)
    assert parquet_path.startswith("s3://mybucket/")
    assert parquet_path.endswith(".parquet")
