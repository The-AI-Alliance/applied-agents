import aws_cdk
from aws_cdk import (
    aws_bedrock as bedrock,
    aws_iam as iam,
    custom_resources as cr,
)
from constructs import Construct


class KnowledgeBaseStack(aws_cdk.Stack):

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        env: aws_cdk.Environment,
        application_ci: str,
        database_cluster_secret_arn: str,
        database_cluster_arn: str,
        database_name: str,
        bucket_arn: str,
        bucket_name: str,
        **kwargs,
    ) -> None:

        super().__init__(scope, construct_id, env=env, **kwargs)
        account_id = env.account
        region_name = "us-east-1"
        embeddingModelArn = f"arn:aws:bedrock:{region_name}::foundation-model/amazon.titan-embed-text-v1"

        bedrock_kb_role = iam.Role(
            self,
            "BedrockKBRole",
            assumed_by=iam.ServicePrincipal("bedrock.amazonaws.com"),
            inline_policies={
                "RDSPolicies": iam.PolicyDocument(
                    statements=[
                        iam.PolicyStatement(
                            actions=["rds:DescribeDBClusters"],
                            resources=[database_cluster_arn],
                            effect=iam.Effect.ALLOW,
                        ),
                        iam.PolicyStatement(
                            actions=[
                                "rds-data:BatchExecuteStatement",
                                "rds-data:ExecuteStatement",
                            ],
                            resources=[database_cluster_arn],
                            effect=iam.Effect.ALLOW,
                        ),
                        iam.PolicyStatement(
                            actions=["secretsmanager:GetSecretValue"],
                            resources=[database_cluster_secret_arn],
                            effect=iam.Effect.ALLOW,
                        ),
                        iam.PolicyStatement(
                            actions=["s3:GetObject", "s3:ListBucket"],
                            resources=[
                                f"arn:aws:s3:::{bucket_name}",
                                f"arn:aws:s3:::{bucket_name}/*",
                            ],
                            effect=iam.Effect.ALLOW,
                        ),
                        iam.PolicyStatement(
                            actions=[
                                "bedrock:ListFoundationModels",
                                "bedrock:ListCustomModels",
                            ],
                            resources=["*"],
                            effect=iam.Effect.ALLOW,
                        ),
                        iam.PolicyStatement(
                            actions=["bedrock:InvokeModel"],
                            resources=[embeddingModelArn],
                            effect=iam.Effect.ALLOW,
                        ),
                    ]
                )
            },
        )
        bedrock_kb_role.assume_role_policy.add_statements(
            iam.PolicyStatement(
                principals=[iam.ServicePrincipal("bedrock.amazonaws.com")],
                actions=["sts:AssumeRole"],
                conditions={
                    "StringEquals": {"aws:SourceAccount": account_id},
                    "ArnLike": {
                        "AWS:SourceArn": f"arn:aws:bedrock:{region_name}:{account_id}:knowledge-base/*"
                    },
                },
            )
        )

        rds_configuration = bedrock.CfnKnowledgeBase.RdsConfigurationProperty(
            credentials_secret_arn=database_cluster_secret_arn,
            database_name=database_name,
            field_mapping=bedrock.CfnKnowledgeBase.RdsFieldMappingProperty(
                metadata_field="metadata",
                primary_key_field="id",
                text_field="chunks",
                vector_field="embedding",
            ),
            resource_arn=database_cluster_arn,
            table_name="aws_managed.kb",
        )

        storage_configuration = {"type": "RDS", "rdsConfiguration": rds_configuration}

        knowledge_base = bedrock.CfnKnowledgeBase(
            self,
            id="knowledge_base",
            name=f"{application_ci}_kb",
            role_arn=bedrock_kb_role.role_arn,
            knowledge_base_configuration=bedrock.CfnKnowledgeBase.KnowledgeBaseConfigurationProperty(
                type="VECTOR",
                vector_knowledge_base_configuration=bedrock.CfnKnowledgeBase.VectorKnowledgeBaseConfigurationProperty(
                    embedding_model_arn=embeddingModelArn
                ),
            ),
            storage_configuration=storage_configuration,
        )

        data_source = bedrock.CfnDataSource(
            self,
            "S3DataSource",
            knowledge_base_id=knowledge_base.attr_knowledge_base_id,
            name="S3DataSource",
            data_source_configuration=bedrock.CfnDataSource.DataSourceConfigurationProperty(
                type="S3",
                s3_configuration=bedrock.CfnDataSource.S3DataSourceConfigurationProperty(
                    bucket_arn=bucket_arn,
                    bucket_owner_account_id=account_id,
                    inclusion_prefixes=["NSF"],
                ),
            ),
            vector_ingestion_configuration=bedrock.CfnDataSource.VectorIngestionConfigurationProperty(
                chunking_configuration=bedrock.CfnDataSource.ChunkingConfigurationProperty(
                    chunking_strategy="FIXED_SIZE",
                    fixed_size_chunking_configuration=bedrock.CfnDataSource.FixedSizeChunkingConfigurationProperty(
                        max_tokens=300, overlap_percentage=20
                    ),
                )
            ),
        )

        data_source.node.add_dependency(knowledge_base)

        dataSourceIngestionParams = {
            "dataSourceId": data_source.attr_data_source_id,
            "knowledgeBaseId": knowledge_base.attr_knowledge_base_id,
        }

        ingestion_job_cr = cr.AwsCustomResource(
            self,
            "IngestionCustomResource",
            on_create=cr.AwsSdkCall(
                service="bedrock-agent",
                action="startIngestionJob",
                parameters=dataSourceIngestionParams,
                physical_resource_id=cr.PhysicalResourceId.of("Parameter.ARN"),
            ),
            policy=cr.AwsCustomResourcePolicy.from_sdk_calls(
                resources=cr.AwsCustomResourcePolicy.ANY_RESOURCE
            ),
        )

        ingestion_job_cr.grant_principal.add_to_principal_policy(
            iam.PolicyStatement(
                effect=iam.Effect.ALLOW,
                actions=["bedrock:*", "iam:CreateServiceLinkedRole", "iam:PassRole"],
                resources=["*"],
            )
        )

        ingestion_job_cr.node.add_dependency(data_source)
