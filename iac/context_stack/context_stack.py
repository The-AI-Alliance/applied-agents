import aws_cdk
from aws_cdk import (
    aws_dynamodb as dynamodb,
)
from constructs import Construct


class ContextStack(aws_cdk.Stack):

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        env: aws_cdk.Environment,
        application_ci: str,
        **kwargs,
    ) -> None:

        super().__init__(scope, construct_id, env=env, **kwargs)

        table = dynamodb.TableV2(
            self,
            "context_table",
            table_name=f"{application_ci}-context",
            billing=dynamodb.Billing.on_demand(),
            removal_policy=aws_cdk.RemovalPolicy.DESTROY,
            partition_key=dynamodb.Attribute(
                name="PK", type=dynamodb.AttributeType.STRING
            ),
            sort_key=dynamodb.Attribute(name="SK", type=dynamodb.AttributeType.NUMBER),
            # stream=dynamodb.StreamViewType.NEW_AND_OLD_IMAGES,  # is this obsolete?
        )

        self.contexttable_table_name = table.table_name
        self.contexttable_table_arn = table.table_arn
