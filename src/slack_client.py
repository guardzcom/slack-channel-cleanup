import os
from dotenv import load_dotenv
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

def validate_client(client: WebClient) -> None:
    """
    Validate that the client can connect and has necessary permissions.
    """
    try:
        print("Testing Slack connection...")
        auth_response = client.auth_test()
        print(f"Connected as: {auth_response['user']} to workspace: {auth_response['team']}")
        
        # Test channel listing with a single call for both public and private channels
        print("Testing channel access...")
        channels_response = client.conversations_list(
            types="public_channel,private_channel",
            limit=1  # We only need to test access, not get all channels
        )
        
        print("✓ Successfully validated channel read permissions")
        
    except SlackApiError as e:
        error = e.response["error"]
        if error == "missing_scope":
            print("\nError: Missing required scopes!")
            print("Please add these scopes to your Slack app configuration:")
            print("- channels:write - For managing public channels")
            print("- groups:write - For managing private channels")
            print("- channels:read - For listing public channels")
            print("- groups:read - For listing private channels")
            print("- chat:write - For posting messages")
        else:
            print(f"\nDebug information:")
            print(f"Error type: {error}")
            print(f"Full response: {e.response}")
        raise ValueError(f"Failed to validate Slack access: {error}")

def get_slack_client() -> WebClient:
    """
    Create and return a Slack WebClient instance.
    
    Required Scopes:
    - channels:write: For managing public channels
    - groups:write: For managing private channels
    - channels:read: For listing public channels
    - groups:read: For listing private channels
    - chat:write: For posting messages
    
    Returns:
        WebClient: Configured Slack client
    
    Raises:
        ValueError: If token is missing, invalid, or has insufficient permissions
    """
    print("\nInitializing Slack client...")
    load_dotenv()
    token = os.getenv("SLACK_TOKEN")
    
    if not token:
        raise ValueError("SLACK_TOKEN environment variable is not set in .env file")
    
    print(f"Token prefix: {token[:10]}...")
    client = WebClient(token=token)
    
    # Validate client
    validate_client(client)
    
    return client 