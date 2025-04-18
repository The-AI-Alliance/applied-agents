# Import necessary libraries
import json
import boto3
import os
from typing import List, Dict, Any

# Initialize AWS clients for Kendra, Bedrock, and API Gateway Management API
# These clients are used for interacting with respective AWS services
bedrock_client = boto3.client("bedrock-runtime")
bedrock_agent_runtime = boto3.client(service_name="bedrock-agent-runtime")

# api_gateway_endpoint_url = os.getenv('API_GATEWAY_ENDPOINT_URL')
# apigatewaymanagementapi_client = boto3.client('apigatewaymanagementapi', endpoint_url=api_gateway_endpoint_url)


def vector_db_retrieve(query, kbId, numberOfResults=5):
    response = bedrock_agent_runtime.retrieve(
        retrievalQuery={"text": query},
        knowledgeBaseId=kbId,
        retrievalConfiguration={
            "vectorSearchConfiguration": {"numberOfResults": numberOfResults}
        },
    )

    return response


def handler(event: List[Dict[str, Any]], context: Any) -> str:
    """
    The main handler function for processing incoming events.
    - event: The event dictionary containing data and context from the triggering source.
    - context: Provides information about the invocation, function, and execution environment.
    """

    # Initialize a variable to accumulate the full response text
    full_response = ""

    # Retrieve necessary configurations from environment variables
    # These are set in the Lambda function's configuration and are essential for the operation
    model_id = os.getenv("BEDROCK_MODEL_ID")
    anthropic_version = os.getenv("ANTHROPIC_VERSION")
    max_tokens = os.getenv("MAX_TOKENS")
    knowledge_base_id = os.getenv("KNOWLEDGE_BASE_ID")

    # Extract historical conversation records for context
    history = get_history_from_records(event["contentResults"][0]["Items"])
    question = event["data"]["message"]
    connection_id = event["ConnectionID"]

    # Extract search results and process them for context
    vector_db_context = vector_db_retrieve(
        question, knowledge_base_id, numberOfResults=10
    )

    # Prepare the request body for the Bedrock AI model invocation
    body = json.dumps(
        {
            "anthropic_version": anthropic_version,
            "max_tokens": int(max_tokens),
            "system": generate_system_prompt(vector_db_context, history),
            "messages": [{"role": "user", "content": question}],
        }
    )

    # Invoke the Bedrock AI model and process the streaming response
    response = bedrock_client.invoke_model_with_response_stream(
        body=body, modelId=model_id
    )
    full_response = process_response(response, connection_id, full_response)
    print(f"FULL RESPONSE: {full_response}")
    # Return the full response text after processing all chunks
    return full_response


def process_response(
    response: Dict[str, Any], connection_id: str, full_response: str
) -> str:
    """
    Processes the streaming response from the Bedrock AI model invocation.
    - response: The response object from the model invocation.
    - connection_id: The ID used for the connection in API Gateway.
    - full_response: The accumulated full response text.
    """
    # Iterate through the response events
    for event in response.get("body"):
        chunk = json.loads(event["chunk"]["bytes"])

        # Check for message completion indicator
        if chunk["type"] == "message_delta":
            # Signal the end of the message to the API Gateway
            # apigatewaymanagementapi_client.post_to_connection(Data="[[END]]", ConnectionId=connection_id)
            True

        # Check for text content and append it to the full response
        if (
            chunk["type"] == "content_block_delta"
            and chunk["delta"]["type"] == "text_delta"
        ):
            # Send the text chunk to the API Gateway and accumulate it
            # apigatewaymanagementapi_client.post_to_connection(Data=chunk['delta']['text'], ConnectionId=connection_id)
            full_response += chunk["delta"]["text"]
    return full_response


def generate_system_prompt(
    docs: List[Dict[str, Any]], history: List[Dict[str, str]]
) -> str:
    """
    Generates a prompt for the AI model to guide its response generation.
    - docs: A list of documents from Kendra for context.
    - history: A list of past Q&A pairs for context.
    """
    # Construct the system prompt with context and instructions for the AI model
    system_prompt = "For this query, please prioritize the context I will give and try to ground your response as much as possible in just that information including links where possible. Minimizing pulling from other background knowledge unless absolutely necessary. The context provided will be in the form of docs provided on the topic and a history of question and answers. If you don't know the answer, say 'I'm sorry, I don't know'. Return all answers in markdown."

    # Add documents to the prompt for additional context
    if docs:
        system_prompt += "\n\n<docs>\n"
        for doc in docs["retrievalResults"]:
            system_prompt += f"<doc>\n<title>{doc['location']['s3Location']['uri']}</title>\n<content>{doc['content']['text']}</content>\n<link>{doc['location']['s3Location']['uri']}</link>\n</doc>"
        system_prompt += "\n<docs>"

    # Add conversation history to the prompt for contextual grounding
    if history:
        system_prompt += "\n\n<history>\n"
        for h in history:
            system_prompt += f"<item>\n<question>{h['question']}</question>\n<answer>{h['answer']}</answer>\n</item>"
        system_prompt += "\n<history>"

    return system_prompt


def get_history_from_records(records: List[Dict[str, Any]]) -> List[Dict[str, str]]:
    """
    Extracts and formats the conversation history from DynamoDB records.
    - records: The list of records from DynamoDB representing past interactions.
    """
    # Compile a list of past Q&A pairs from the records
    history = []
    for record in records:
        question = record["question"]["S"]
        answer = record["answer"]["S"]
        history.append({"question": question, "answer": answer})
    return history
