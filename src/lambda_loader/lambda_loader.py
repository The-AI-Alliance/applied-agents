import os
import json
import boto3
import psycopg2

from aws_lambda_powertools import Logger
from aws_lambda_powertools.utilities import parameters

logger = Logger()


@logger.inject_lambda_context(log_event=True)
def handler(event, context):
    logger.info("Starting execution...")
    secret_name = os.environ.get("AURORA_SECRET_NAME")
    logger.info("Getting secrets...")
    value = json.loads(parameters.get_secret(secret_name))
    logger.info("Getting data to load...")
    s3 = boto3.client("s3")
    data = s3.get_object(
        Bucket=os.environ.get("DATA_BUCKET"), Key=os.environ.get("DATA_FILE")
    )
    contents = data["Body"].read()
    try:
        logger.info("Connecting to database...")
        conn = psycopg2.connect(
            database=value["dbname"],
            user=value["username"],
            password=value["password"],
            host=value["host"],
            port=value["port"],
        )
        cur = conn.cursor()
        logger.info("Loading database...")
        cur.execute(contents)
        conn.commit()
        logger.info("Closing connection to database...")
        cur.close()
        conn.close()
        logger.info("Done!")
    except Exception as e:
        logger.error(f"Unable to execute sql: {e}")
