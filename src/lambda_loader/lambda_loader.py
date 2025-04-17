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
    analytic_data = s3.get_object(
        Bucket=os.environ.get("DATA_BUCKET"), Key=os.environ.get("DATA_FILE")
    )
    vector_schema = s3.get_object(
        Bucket=os.environ.get("DATA_BUCKET"), Key=os.environ.get("VECTOR_CONFIG_FILE")
    )

    analytics_contents = analytic_data["Body"].read()
    vector_schema_contents = vector_schema["Body"].read().decode("utf-8")
    vector_schema_contents_replaced = vector_schema_contents.replace(
        "<update with secure password>", value["password"]
    )
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
        logger.info("Loading analytic data...")
        cur.execute(analytics_contents)
        conn.commit()
        logger.info("Configuring vector schema...")
        cur.execute(vector_schema_contents_replaced)
        conn.commit()
        logger.info("Closing connection to database...")
        cur.close()
        conn.close()
        logger.info("Done!")
    except Exception as e:
        logger.error(f"Unable to execute sql: {e}")
