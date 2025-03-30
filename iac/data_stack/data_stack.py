import aws_cdk
from aws_cdk import aws_s3 as s3
from aws_cdk import aws_s3_deployment

from constructs import Construct


class DataStack(aws_cdk.Stack):

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        env: aws_cdk.Environment,
        **kwargs,
    ) -> None:

        super().__init__(scope, construct_id, env=env, **kwargs)

        self.data_bucket = s3.Bucket(
            self,
            "data_bucket",
            bucket_name=self.stack_name.lower(),
            access_control=s3.BucketAccessControl.BUCKET_OWNER_FULL_CONTROL,
            encryption=s3.BucketEncryption.S3_MANAGED,
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            versioned=True,
            removal_policy=aws_cdk.RemovalPolicy.DESTROY,
            auto_delete_objects=True,
        )

        # https://github.com/lerocha/chinook-database/blob/master/LICENSE.md
        aws_s3_deployment.BucketDeployment(
            self,
            "DataLoader",
            sources=[aws_s3_deployment.Source.asset("../data")],
            destination_bucket=self.data_bucket,
            destination_key_prefix="",
        )
