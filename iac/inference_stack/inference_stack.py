import aws_cdk
from aws_cdk import (
    aws_dynamodb as dynamodb,
    aws_iam as iam,
    aws_ec2 as ec2,
    aws_lambda,
    aws_logs as logs,
    aws_apigatewayv2 as apigwv2,
    aws_stepfunctions as sfn,
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
        contexttable_table_name: str,
        contexttable_table_arn: str,
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

        step_function_log_group = logs.LogGroup(
            self,
            "StepFunctionLogGroup",
            log_group_name=f"/applications/{application_ci}/{application_ci}-step-function",
            removal_policy=aws_cdk.RemovalPolicy.DESTROY,
        )

        step_function_execution_role = iam.Role(
            self,
            "StepFunctionExecutionRole",
            assumed_by=iam.ServicePrincipal("apigateway.amazonaws.com"),
        )

        websocket_api_log_group = logs.LogGroup(
            self,
            "WebSocketAPILogGroup",
            log_group_name=f"/applications/{application_ci}/{application_ci}-websocket-api",
            removal_policy=aws_cdk.RemovalPolicy.DESTROY,
        )

        inference_function_log_group = logs.LogGroup(
            self,
            "InferenceFunctionLogGroup",
            log_group_name=f"/applications/{application_ci}/{application_ci}-inference-function",
            removal_policy=aws_cdk.RemovalPolicy.DESTROY,
        )

        websocket_api_gateway = apigwv2.CfnApi(
            self,
            "WebSocketAPI",
            name=f"{application_ci}-websocket-api",
            protocol_type="WEBSOCKET",
            route_selection_expression="$request.body.action",
        )

        api_endpoint_prefix = f"arn:aws:execute-api:{env.region}:{env.account}:{websocket_api_gateway.attr_api_id}/{websocket_api_gateway.name}/POST/@connections/"
        api_endpoint_arn = api_endpoint_prefix + "{connectionId}"

        # TODO: Need the stateMachineArn here. Situation is state machine needs the API Gateway,
        # and the API Gateway needs the state machine...
        request_template = {
            "$default": """#set($sfn_input=$util.escapeJavaScript($input.body).replaceAll("\\'","'")) {
        "input": "{\\"data\\":$sfn_input, \\"timestamp\\":\\"$context.requestTimeEpoch\\", \\"ConnectionID\\":\\"$context.connectionId\\"}",
        "stateMachineArn": "arn"   
        }"""
        }

        websocket_api_gateway_default_integration = apigwv2.CfnIntegration(
            self,
            "WebSocketAPIGatewayIntegration",
            api_id=websocket_api_gateway.attr_api_id,
            integration_type="AWS",
            integration_method="POST",
            integration_uri=f"arn:aws:apigateway:{env.region}:states:action/StartExecution",
            credentials_arn=step_function_execution_role.role_arn,
            template_selection_expression="\\$default",
            request_templates=request_template,
        )

        websocket_api_gateway_default_route = apigwv2.CfnRoute(
            self,
            "WebSocketAPIDefaultRoute",
            api_id=websocket_api_gateway.attr_api_id,
            route_key="$default",
            authorization_type="NONE",
            target=f"integrations/{websocket_api_gateway_default_integration.ref}",  # TODO: fix this
        )

        websocket_api_gateway_default_route.node.add_dependency(
            websocket_api_gateway_default_integration
        )

        websocket_api_gateway_deployment = apigwv2.CfnDeployment(
            self, "WebSocketAPIDeployment", api_id=websocket_api_gateway.attr_api_id
        )
        websocket_api_gateway_deployment.node.add_dependency(
            websocket_api_gateway_default_route
        )

        websocket_api_gateway_stage = apigwv2.CfnStage(
            self,
            "WebSocketAPIStage",
            stage_name=f"{application_ci}-websocket-api",
            deployment_id=websocket_api_gateway_deployment.attr_deployment_id,
            api_id=websocket_api_gateway.attr_api_id,
            default_route_settings=apigwv2.CfnStage.RouteSettingsProperty(
                data_trace_enabled=False,
                detailed_metrics_enabled=True,
                logging_level="ERROR",
            ),
            access_log_settings=apigwv2.CfnStage.AccessLogSettingsProperty(
                destination_arn=websocket_api_log_group.log_group_arn,
                format="$context.status $context.responseLength $context.requestId $context.error.messageString",
            ),
        )

        websocket_api_gateway_route_response = apigwv2.CfnRouteResponse(
            self,
            "WebSocketAPIGatewayDfltRtRsp",
            api_id=websocket_api_gateway.attr_api_id,
            route_id=websocket_api_gateway_default_route.attr_route_id,
            route_response_key="$default",
        )

        websocket_api_gateway_integration_response = apigwv2.CfnIntegrationResponse(
            self,
            "WebSocketAPIGatewayIntgrRsp",
            api_id=websocket_api_gateway.attr_api_id,
            integration_id=websocket_api_gateway_default_integration.ref,  # TODO fix
            integration_response_key="$default",
        )

        websocket_api_gateway_integration_response.node.add_dependency(
            websocket_api_gateway_default_integration
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
                "MAX_TOKENS": "8000",  #  Verify this
                "API_GATEWAY_ENDPOINT_URL": f"https://{websocket_api_gateway.attr_api_id}.execute-api.{env.region}.amazonaws.com/{websocket_api_gateway_stage.stage_name}",
            },
            log_group=inference_function_log_group,
            # TODO: Problems accessing a public API from a lambda in a VPC, even on a publci subnet.
            # See: https://repost.aws/knowledge-center/api-gateway-vpc-connections
            #
            # vpc=vpc,
            # vpc_subnets=ec2.SubnetSelection(subnet_type=ec2.SubnetType.PUBLIC),
            # allow_public_subnet=True,
            # security_groups=[serverless_security_group],
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
                        iam.PolicyStatement(
                            actions=["execute-api:ManageConnections"],
                            # TODO: Resouce below should be variable 'api_endpoint_arn' but
                            # this is not working. Might be due to the {connectionId} notation?
                            resources=["*"],
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

        self.inference_function_name = lambda_inference_function.function_name
        self.inference_function_arn = lambda_inference_function.function_arn

        step_function = sfn.StateMachine(
            self,
            "WebSocketAPIStateMachine",
            state_machine_type=sfn.StateMachineType.EXPRESS,
            tracing_enabled=True,
            logs=sfn.LogOptions(
                destination=step_function_log_group, level=sfn.LogLevel.ALL
            ),
            definition_body=sfn.DefinitionBody.from_file(
                path="./statemachine.asl.json"
            ),
            definition_substitutions={
                "WSApi": f"{websocket_api_gateway.attr_api_id}.execute-api.{env.region}.amazonaws.com",
                "WSApiStage": websocket_api_gateway_stage.stage_name,
                "PromptFunction": self.inference_function_name,
                "ContextTable": contexttable_table_name,
            },
        )

        step_function.role.attach_inline_policy(
            iam.Policy(
                self,
                "StepFunctionsDynamoDb",
                statements=[
                    iam.PolicyStatement(
                        effect=iam.Effect.ALLOW,
                        actions=[
                            "dynamodb:GetItem",
                            "dynamodb:DeleteItem",
                            "dynamodb:PutItem",
                            "dynamodb:Scan",
                            "dynamodb:Query",
                            "dynamodb:UpdateItem",
                            "dynamodb:BatchWriteItem",
                            "dynamodb:BatchGetItem",
                            "dynamodb:DescribeTable",
                            "dynamodb:ConditionCheckItem",
                        ],
                        resources=[
                            contexttable_table_arn,
                            f"{contexttable_table_arn}/index/*",
                        ],
                    ),
                ],
            )
        )

        step_function.role.attach_inline_policy(
            iam.Policy(
                self,
                "StepFunctionsLambdaExecution",
                statements=[
                    iam.PolicyStatement(
                        effect=iam.Effect.ALLOW,
                        actions=["lambda:InvokeFunction"],
                        resources=[f"{self.inference_function_arn}*"],
                    )
                ],
            )
        )

        step_function.role.attach_inline_policy(
            iam.Policy(
                self,
                "StepFunctionsApiManageConnections",
                statements=[
                    iam.PolicyStatement(
                        effect=iam.Effect.ALLOW,
                        actions=["execute-api:ManageConnections"],
                        resources=[api_endpoint_arn],
                    ),
                ],
            )
        )

        step_function.role.add_managed_policy(
            iam.ManagedPolicy.from_aws_managed_policy_name("AWSXrayWriteOnlyAccess")
        )

        step_function_execution_role.attach_inline_policy(
            iam.Policy(
                self,
                "StepFunctionsStateExecution",
                statements=[
                    iam.PolicyStatement(
                        effect=iam.Effect.ALLOW,
                        actions=["states:StartExecution"],
                        resources=[step_function.state_machine_arn],
                    ),
                ],
            )
        )
