import builtins
from typing import List

import aws_cdk

from database_stack.database_stack import DatabaseStack
from data_stack.data_stack import DataStack
from knowledge_base_stack.knowledge_base_stack import KnowledgeBaseStack
from context_stack.context_stack import ContextStack
from inference_stack.inference_stack import InferenceStack
from config.bucket_attributes import BucketAttributes


class RegionalStack(aws_cdk.Stack):
    def __init__(
        self,
        scope,
        application_ci: builtins.str,
        env: aws_cdk.Environment,
        id: builtins.str,
        runtime_environment: builtins.str,
        **kwargs,
    ):

        super().__init__(scope, id, **kwargs)

        # Stack 1 - data stack: S3 bucket with the data files loaded
        data_stack = DataStack(self, "data", env=env)

        # Stack 2 - database stack: Serverless Aurora Postgres + lambda to load data files from S3
        database_stack = DatabaseStack(
            self,
            "database",
            env=env,
            data_bucket=data_stack.data_bucket,
            application_ci=application_ci,
        )

        # Stack 3 - knowledge base stack
        knowledge_base_stack = KnowledgeBaseStack(
            self,
            "knowledge_base",
            env=env,
            application_ci=application_ci,
            database_cluster_secret_arn=database_stack.database_cluster_secret_arn,
            database_cluster_arn=database_stack.database_cluster_arn,
            database_name=database_stack.database_name,
            bucket_arn=data_stack.data_bucket.bucket_arn,
            bucket_name=data_stack.data_bucket.bucket_name,
        )

        # Stack 4 - Context stack. May move this to app side.
        context_stack = ContextStack(
            self,
            "context_stack",
            env=env,
            application_ci=application_ci,
        )

        bedrock_model_version = "bedrock-2023-05-31"
        bedrock_model_id = "anthropic.claude-3-sonnet-20240229-v1:0"

        inference_stack = InferenceStack(
            self,
            "inference_stack",
            env=env,
            application_ci=application_ci,
            knowledge_base_id=knowledge_base_stack.knowledge_base_id,
            bedrock_model_id=bedrock_model_id,
            bedrock_model_version=bedrock_model_version,
            knowledge_base_arn=knowledge_base_stack.knowledge_base_arn,
            contexttable_table_name=context_stack.contexttable_table_name,
            contexttable_table_arn=context_stack.contexttable_table_arn,
        )

        bucket_base_name = f"{application_ci}-analytics"

        secondary_bucket = BucketAttributes(
            bucket_name=f"{bucket_base_name}-us-east-2",
            region="us-east-2",
            account=env.account,
            id="aaa-analytics-secondary",
        )

        primary_bucket = BucketAttributes(
            bucket_name=f"{bucket_base_name}-us-east-1",
            region="us-east-1",
            account=env.account,
            id="aaa-analytics-primary",
        )
