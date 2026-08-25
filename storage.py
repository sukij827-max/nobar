import boto3
from botocore.client import Config
from config import settings
s3=boto3.client('s3',endpoint_url=settings.b2_endpoint,aws_access_key_id=settings.b2_key_id,aws_secret_access_key=settings.b2_application_key,region_name=settings.b2_region,config=Config(signature_version='s3v4'))
def presigned_put(key,content_type): return s3.generate_presigned_url('put_object',Params={'Bucket':settings.b2_bucket,'Key':key,'ContentType':content_type},ExpiresIn=900)
def presigned_get(key): return s3.generate_presigned_url('get_object',Params={'Bucket':settings.b2_bucket,'Key':key},ExpiresIn=3600)
