import json
import aws_cdk
import subprocess
import sys
import shutil
import os
import random
from aws_cdk import (
    aws_iam as iam,
    aws_rds as rds,
    aws_secretsmanager as secretsmanager,
    aws_s3 as s3,
    aws_ec2 as ec2,
    aws_lambda,
    triggers,
)

from constructs import Construct


class DatabaseStack(aws_cdk.Stack):

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        env: aws_cdk.Environment,
        data_bucket: s3.Bucket,
        application_ci: str,
        **kwargs,
    ) -> None:

        super().__init__(scope, construct_id, env=env, **kwargs)

        # TODO: replace this with a dedicated VPC instead of using the default?
        vpc = ec2.Vpc.from_lookup(
            self,
            "Vpc",
            owner_account_id=env.account,
            region=env.region,
            is_default=True,
        )
        r = random.randint(0, 10000)
        secret_db_creds = secretsmanager.Secret(
            self,
            "rds_creds",
            secret_name=f"{application_ci}/db_creds",
            generate_secret_string=secretsmanager.SecretStringGenerator(
                secret_string_template=json.dumps(
                    {"username": f"{application_ci}admin{r}"}
                ),
                exclude_punctuation=True,
                generate_string_key="password",
            ),
        )

        serverless_security_group = ec2.SecurityGroup(
            self,
            "serverless-sg",
            vpc=vpc,
            allow_all_outbound=True,
            security_group_name="rds-connectivity",
            description=f"Security group for {application_ci} serverless",
        )

        # TODO: check for these...
        private_link_secrets_security_group_id_default = os.environ.get("DEFAULT_SG")
        private_link_s3_security_group_id = os.environ.get("S3_SG")

        # TODO: do something about this...
        privatelink_s3_sg = ec2.SecurityGroup.from_lookup_by_id(
            self, "s3_privatelink", security_group_id=private_link_s3_security_group_id
        )
        privatelink_secrets_sg = ec2.SecurityGroup.from_lookup_by_id(
            self,
            "secrets_privatelink",
            security_group_id=private_link_secrets_security_group_id_default,
        )

        privatelink_s3_sg.connections.allow_from(
            serverless_security_group,
            ec2.Port.all_traffic(),
            "Allows S3 Connectivity",
        )

        privatelink_secrets_sg.connections.allow_from(
            serverless_security_group,
            ec2.Port.all_traffic(),
            "Allows AWS Secrets Manager Connectivity",
        )

        rds_security_group = ec2.SecurityGroup(
            self,
            "rds-sg",
            vpc=vpc,
            allow_all_outbound=True,
            security_group_name=f"{application_ci}-sg-for-rds",
            description=f"Security group for {application_ci} rds database",
        )

        # Aurora Security group allow all traffic from lambda's security group
        rds_security_group.add_ingress_rule(
            serverless_security_group,
            ec2.Port.tcp(5432),
            "Allow lambda connectivity to rds Postgres database",
        )

        database = rds.DatabaseCluster(
            self,
            "rds_database",
            engine=rds.DatabaseClusterEngine.aurora_postgres(
                version=rds.AuroraPostgresEngineVersion.VER_16_2
            ),
            credentials=rds.Credentials.from_secret(secret_db_creds),
            writer=rds.ClusterInstance.serverless_v2(
                "writer", publicly_accessible=True
            ),
            readers=[
                rds.ClusterInstance.serverless_v2("reader1", publicly_accessible=True),
                rds.ClusterInstance.serverless_v2("reader2", publicly_accessible=True),
            ],
            vpc_subnets=ec2.SubnetSelection(
                subnet_type=ec2.SubnetType.PUBLIC  # Private with Egress?
            ),
            vpc=vpc,
            default_database_name="default_db",
            security_groups=[rds_security_group],
        )

        # TODO: handle this better
        temp_build_root = "/tmp/build"
        python_runtime_version = "python3.12"
        src_home = "../src/lambda_loader"
        src_root = "../src"
        command = f"../scripts/build_lambda.sh {temp_build_root} {python_runtime_version.replace("python","")} {application_ci} {src_home} {src_root}"
        try:
            process = subprocess.Popen(
                command, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE
            )
            stdout, stderr = process.communicate()

            if process.returncode == 0:
                self.built_archive = stdout.decode("utf-8").replace("\n", "")
            else:
                raise RuntimeError(stderr.decode("utf-8"))

        except Exception as e:
            error = f"Error creating .zip archive. {e}"
            print(error)
            sys.exit()

        lambda_s3_function = aws_lambda.Function(
            self,
            "rds_data_loader",
            runtime=aws_lambda.Runtime.PYTHON_3_12,
            architecture=aws_lambda.Architecture.X86_64,
            handler="lambda_loader.lambda_loader.handler",
            timeout=aws_cdk.Duration.minutes(5),
            code=aws_lambda.Code.from_asset(self.built_archive),
            environment={
                "DATA_BUCKET": data_bucket.bucket_name,
                "AURORA_SECRET_NAME": secret_db_creds.secret_name,
                "DATA_FILE": "chinook.sql",
            },
            vpc=vpc,
            vpc_subnets=ec2.SubnetSelection(subnet_type=ec2.SubnetType.PUBLIC),
            allow_public_subnet=True,
            security_groups=[serverless_security_group],
        )

        ### the below permissions are essential
        data_bucket.grant_read(lambda_s3_function.role)
        secret_db_creds.grant_read(lambda_s3_function)
        lambda_s3_function.role.add_managed_policy(
            iam.ManagedPolicy.from_aws_managed_policy_name("AmazonS3ReadOnlyAccess")
        )

        trigger = triggers.Trigger(
            self, "LambdaTrigger", handler=lambda_s3_function, execute_after=[database]
        )

        # Clean up the .zip archive build
        try:
            shutil.rmtree(temp_build_root)
        except OSError as e:
            error = f"Error deleting temporary build directory {temp_build_root}: {e}"
            print(error)
            pass
