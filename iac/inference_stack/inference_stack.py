import aws_cdk
from aws_cdk import (
    aws_dynamodb as dynamodb,
    aws_iam as iam,
    aws_ec2 as ec2,
    aws_lambda,
    aws_stepfunctions as step_functions,
    aws_logs as logs,
)
from constructs import Construct
import os


class InferenceStack(aws_cdk.Stack):

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        env: aws_cdk.Environment,
        application_ci: str,
        knowledge_base_id: str,
        knowledge_base_arn: str,
        bedrock_model_id: str,
        bedrock_model_version: str,
        **kwargs,
    ) -> None:

        super().__init__(scope, construct_id, env=env, **kwargs)

        vpc = ec2.Vpc.from_lookup(
            self,
            "Vpc",
            owner_account_id=env.account,
            region=env.region,
            is_default=True,
        )
        serverless_security_group = ec2.SecurityGroup(
            self,
            "serverless-sg",
            vpc=vpc,
            allow_all_outbound=True,
            security_group_name="bedrock-context",
            description=f"Security group for {application_ci} bedrock context serverless",
        )

        # TODO: check for these...
        private_link_security_group_id_default = os.environ.get("DEFAULT_SG")

        # TODO: do something about this...
        privatelink_secrets_sg = ec2.SecurityGroup.from_lookup_by_id(
            self,
            "secrets_privatelink",
            security_group_id=private_link_security_group_id_default,
        )

        privatelink_secrets_sg.connections.allow_from(
            serverless_security_group,
            ec2.Port.all_traffic(),
            "Allows bedrock context connectivity",
        )

        lambda_inference_function = aws_lambda.Function(
            self,
            "bedrock_function",
            runtime=aws_lambda.Runtime.PYTHON_3_12,
            architecture=aws_lambda.Architecture.X86_64,
            handler="bedrock_interface.handler",
            timeout=aws_cdk.Duration.minutes(2),
            code=aws_lambda.Code.from_asset("../src/bedrock_interface"),
            environment={
                "ANTHROPIC_VERSION": bedrock_model_version,  # "bedrock-2023-05-31",
                "BEDROCK_MODEL_ID": bedrock_model_id,  # "anthropic.claude-3-sonnet-20240229-v1:0",
                "KNOWLEDGE_BASE_ID": knowledge_base_id,
                "MAX_TOKENS": "1024",
            },
            vpc=vpc,
            vpc_subnets=ec2.SubnetSelection(subnet_type=ec2.SubnetType.PUBLIC),
            allow_public_subnet=True,
            # role=lambda_inference_role,
            security_groups=[serverless_security_group],
        )

        lambda_inference_function.role.attach_inline_policy(
            iam.Policy(
                self,
                "BedrockPolicy",
                document=iam.PolicyDocument(
                    statements=[
                        iam.PolicyStatement(
                            actions=["bedrock:Retrieve"],
                            resources=[knowledge_base_arn],
                            effect=iam.Effect.ALLOW,
                        ),
                        iam.PolicyStatement(
                            actions=[
                                "bedrock:InvokeModel",
                                "bedrock:InvokeModelWithResponseStream",
                            ],
                            resources=[
                                f"arn:aws:bedrock:{env.region}::foundation-model/{bedrock_model_id}"
                            ],
                            effect=iam.Effect.ALLOW,
                        ),
                    ],
                ),
            )
        )
        lambda_inference_function.add_layers(
            aws_lambda.LayerVersion.from_layer_version_arn(
                self,
                "awsLambdaPowerTools",
                f"arn:aws:lambda:{env.region}:017000801446:layer:AWSLambdaPowertoolsPythonV3-python312-x86_64:11",
            )
        )
