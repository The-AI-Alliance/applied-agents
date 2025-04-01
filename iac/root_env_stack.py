import os

import aws_cdk
import builtins

from regional_stack import RegionalStack
from constructs import Construct

account_ids = {
    "dev": os.environ.get("AWS_DEV_ACCOUNT"),
    "qa": os.environ.get("AWS_QA_ACCOUNT"),
    "prd": os.environ.get("AWS_PRD_ACCOUNT"),
}


class RootEnvStack(aws_cdk.Stack):
    def __init__(
        self,
        scope: Construct,
        runtime_environment: str,
        id: builtins.str,
        application_ci: builtins.str,
        **kwargs
    ):

        super().__init__(scope, id)

        primary_region = "us-east-1"
        primary_stack = RegionalStack(
            self,
            id=primary_region,
            runtime_environment=runtime_environment,
            env=aws_cdk.Environment(
                account=account_ids[runtime_environment], region=primary_region
            ),
            application_ci=application_ci,
        )

        # When we are production ready and need fault tolerance...
        """
        secondary_stack = RegionalStack(
            self,
            id="us-east-2",
            runtime_environment=runtime_environment,
            env=aws_cdk.Environment(
                account=account_ids[runtime_environment], region="us-east-2"
            ),
            application_ci=application_ci,
        )
        """
