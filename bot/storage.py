import hashlib
import re
from urllib.parse import quote
import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

MAX_FILM_BYTES = 5 * 1024**3
PART_SIZE = 64 * 1024**2
MAX_PARTS = 10000

class R2Storage:
    def __init__(self, endpoint, bucket, access_key, secret_key, region='auto'):
        self.bucket = bucket
        self.client = boto3.client(
            's3', endpoint_url=endpoint, region_name=region,
            aws_access_key_id=access_key, aws_secret_access_key=secret_key,
            config=Config(signature_version='s3v4', max_pool_connections=32),
        )

    @staticmethod
    def safe_name(name: str) -> str:
        name = name.strip().replace('\\','/').split('/')[-1]
        name = re.sub(r'[^A-Za-z0-9._ -]+', '_', name)
        return name[:180] or 'film.mp4'

    def key(self, film_id, filename):
        return f'films/{film_id}/{self.safe_name(filename)}'

    def create(self, key, content_type):
        return self.client.create_multipart_upload(
            Bucket=self.bucket, Key=key, ContentType=content_type or 'video/mp4',
            Metadata={'source':'nobar'}
        )['UploadId']

    def presign_part(self, key, upload_id, part_number, expires=3600):
        return self.client.generate_presigned_url(
            'upload_part', Params={'Bucket':self.bucket,'Key':key,'UploadId':upload_id,'PartNumber':part_number}, ExpiresIn=expires
        )

    def complete(self, key, upload_id, parts):
        normalized = sorted({'PartNumber':int(p['PartNumber']),'ETag':p['ETag']} for p in parts)
        return self.client.complete_multipart_upload(Bucket=self.bucket, Key=key, UploadId=upload_id, MultipartUpload={'Parts':normalized})

    def abort(self, key, upload_id):
        try:
            self.client.abort_multipart_upload(Bucket=self.bucket, Key=key, UploadId=upload_id)
        except ClientError:
            pass

    def head(self, key):
        return self.client.head_object(Bucket=self.bucket, Key=key)

    def presign_get(self, key, expires=21600):
        return self.client.generate_presigned_url('get_object', Params={'Bucket':self.bucket,'Key':key}, ExpiresIn=expires)
