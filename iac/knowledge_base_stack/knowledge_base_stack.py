import aws_cdk
from aws_cdk import aws_s3 as s3, aws_bedrock as bedrock, aws_iam as iam

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
        **kwargs,
    ) -> None:

        super().__init__(scope, construct_id, env=env, **kwargs)

        bedrock_kb_role = iam.Role(
            self,
            "BedrockKBRole",
            assumed_by=iam.ServicePrincipal("bedrock.amazonaws.com"),
        )

        account_id = 843382705282
        region_name = "us-east-1"
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

        embeddingModelArn = f"arn:aws:bedrock:{region_name}::foundation-model/amazon.titan-embed-text-v1"

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
