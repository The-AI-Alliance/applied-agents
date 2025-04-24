import aws_cdk
from aws_cdk.aws_s3 import CfnBucket
from typing import List
import json

from aws_cdk import (
    aws_iam as iam,
    aws_s3 as s3,
    aws_secretsmanager as secretsmanager,
    RemovalPolicy,
    SecretValue,
)

from constructs import Construct
from config.bucket_attributes import BucketAttributes


class AnalyticsStack(aws_cdk.Stack):

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        env: aws_cdk.Environment,
        application_ci: str,
        primary_bucket: BucketAttributes,
        secondary_buckets: List[BucketAttributes],
        deploy_replication: bool,
        termination_protection: bool,
        retain_policy: bool,
        **kwargs,
    ) -> None:

        super().__init__(scope, construct_id, env=env, **kwargs)

        removal_policy = RemovalPolicy.DESTROY
        if retain_policy:
            removal_policy = RemovalPolicy.RETAIN

        replication_role = iam.Role(
            self,
            "ReplicationRole",
            assumed_by=iam.ServicePrincipal("s3.amazonaws.com"),
        )

        replication_role.assume_role_policy.add_statements(
            iam.PolicyStatement(
                actions=["sts:AssumeRole"],
                principals=[iam.ServicePrincipal("batchoperations.s3.amazonaws.com")],
            )
        )

        primary_bucket_object = s3.Bucket.from_bucket_attributes(
            self,
            id=primary_bucket["id"],
            account=primary_bucket["account"],
            bucket_name=primary_bucket["bucket_name"],
            region=primary_bucket["region"],
        )

        secondary_bucket_objects = []
        if deploy_replication:
            secondary_bucket_objects = [
                s3.Bucket.from_bucket_attributes(
                    self,
                    id=tb["id"],
                    account=tb["account"],
                    bucket_name=tb["bucket_name"],
                    region=tb["region"],
                )
                for tb in secondary_buckets
            ]

        primary_analytics_bucket = s3.Bucket(
            self,
            "PrimaryAnalyticsBucket",
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            encryption=s3.BucketEncryption.S3_MANAGED,
            bucket_name=primary_bucket["bucket_name"],
            enforce_ssl=True,
            versioned=True,
            removal_policy=removal_policy,
        )

        service_account_username = f"svc-{application_ci}-analytics"

        service_account = iam.User(
            self,
            "IAMUser",
            user_name=service_account_username,
        )

        # TODO: There does not seem to be a secure way to get the access keys
        # for an IAM user and store them in AWS Secrets Manager.
        # You can retreive the access keys as strings, but then they are not
        # "secrets"....
        # Doing this manually via the AWS UI for now.

        # service_account_access_keys = iam.CfnAccessKey(
        #    self, "AccessKeys", user_name=service_account.user_name
        # )

        service_account_access_keys_secret = secretsmanager.Secret(
            self,
            "serviceAccountSecret",
            secret_name=f"{application_ci}/{service_account_username}",
            generate_secret_string=secretsmanager.SecretStringGenerator(
                secret_string_template=(json.dumps({"aws_access_key_id": "some_junk"})),
                generate_string_key="aws_secret_access_key",
            ),
        )

        if deploy_replication:
            self.secondary_analytics_buckets = []
            self.secondary_analytics_buckets = [
                s3.Bucket(
                    self,
                    "SecondaryAnalyticsBucket",
                    block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
                    encryption=s3.BucketEncryption.S3_MANAGED,
                    bucket_name=sb["bucket_name"],
                    enforce_ssl=True,
                    versioned=True,
                    removal_policy=removal_policy,
                )
                for sb in secondary_buckets
            ]

            cfn_bucket: CfnBucket = self.primary_analytics_bucket.node.default_child

            cfn_bucket.replication_configuration = (
                s3.CfnBucket.ReplicationConfigurationProperty(
                    role=replication_role.role_arn,
                    rules=[
                        s3.CfnBucket.ReplicationRuleProperty(
                            destination=s3.CfnBucket.ReplicationDestinationProperty(
                                bucket=bucket.bucket_arn
                            ),
                            status="Enabled",
                        )
                        for bucket in secondary_bucket_objects
                    ],
                )
            )

            replication_role.add_to_policy(
                iam.PolicyStatement(
                    actions=[
                        "s3:GetObjectVersionForReplication",
                        "s3:GetObjectVersionAcl",
                        "s3:GetObjectVersionTagging",
                    ],
                    resources=[
                        self.primary_analytics_bucket.arn_for_objects("*"),
                    ],
                )
            )
            replication_role.add_to_policy(
                iam.PolicyStatement(
                    actions=["s3:ListBucket", "s3:GetReplicationConfiguration"],
                    resources=[
                        self.primary_analytics_bucket.bucket_arn,
                    ],
                ),
            )
            for bucket in secondary_bucket_objects:
                replication_role.add_to_policy(
                    iam.PolicyStatement(
                        actions=[
                            "s3:ReplicateObject",
                            "s3:ReplicateDelete",
                            "s3:ReplicateTags",
                        ],
                        resources=[
                            bucket.arn_for_objects("*"),
                        ],
                    ),
                )

        service_account_policy = iam.Policy(self, "ServiceAccountBuckerReadWrite")

        service_account_policy.add_statements(
            iam.PolicyStatement(
                actions=[
                    "s3:PutObject",
                    "s3:GetObject",
                    "s3:GetObjectTagging",
                    "s3:DeleteObject",
                    "s3:DeleteObjectVersion",
                    "s3:GetObjectVersion",
                    "s3:GetObjectVersionTagging",
                    "s3:GetObjectACL",
                    "s3:PutObjectACL",
                ],
                resources=[primary_analytics_bucket.arn_for_objects("*")],
            )
        )
        service_account_policy.add_statements(
            iam.PolicyStatement(
                actions=["s3:ListBucket"],
                resources=[primary_analytics_bucket.bucket_arn],
            )
        )

        service_account.attach_inline_policy(service_account_policy)
