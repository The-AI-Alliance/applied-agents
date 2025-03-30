import builtins
from typing import List

import aws_cdk

from database_stack.database_stack import DatabaseStack
from data_stack.data_stack import DataStack


class RegionalStack(aws_cdk.Stack):
    def __init__(
        self,
        scope,
        application_ci: builtins.str,
        runtime_environment: str,
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
