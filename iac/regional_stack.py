import builtins
from typing import List

import aws_cdk

from database_stack.database_stack import DatabaseStack
from data_stack.data_stack import DataStack
from knowledge_base_stack.knowledge_base_stack import KnowledgeBaseStack
from context_stack.context_stack import ContextStack


class RegionalStack(aws_cdk.Stack):
    def __init__(
        self,
        scope,
        application_ci: builtins.str,
        env: aws_cdk.Environment,
        id: builtins.str,
        **kwargs
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
