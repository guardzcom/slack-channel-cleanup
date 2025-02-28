import os
from dotenv import load_dotenv
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

def validate_scopes(client: WebClient) -> None:
    """
    Validate that the token has the required scopes for channel management.
    Required scopes: channels:write (public channels), groups:write (private channels)
    Raises ValueError if required scopes are missing.
    """
    try:
        print("Checking token scopes...")
        response = client.auth_test()
        scopes = response.get("scope", "").split(",")
        print(f"Available scopes: {scopes}")
        
        required_scopes = {"channels:write", "groups:write", "channels:read", "groups:read", "chat:write"}
        missing_scopes = required_scopes - set(scopes)
        
        if missing_scopes:
            raise ValueError(
                f"Missing required scopes: {', '.join(missing_scopes)}. "
                "Please add these scopes to your Slack app configuration."
            )
    except SlackApiError as e:
        print(f"\nDebug information:")
        print(f"Error response: {e.response}")
        raise ValueError(f"Failed to validate scopes: {str(e)}")

def get_slack_client() -> WebClient:
    """
    Create and return a Slack WebClient instance with validated token and scopes.
    
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
    
    # Validate scopes
    validate_scopes(client)
    
    return client 