import os
from dotenv import load_dotenv
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

def validate_token_type(client: WebClient) -> None:
    """
    Validate that we're using a user token (xoxp) and not a bot token (xoxb).
    Raises ValueError if the token is not a user token.
    """
    try:
        print("Validating token with auth.test...")
        response = client.auth_test()
        print(f"Auth test response: {response}")
        token_type = response.get("token_type")
        
        if "user" not in str(token_type).lower():
            raise ValueError(
                "Invalid token type. Please use a user token (xoxp) instead of a bot token. "
                "User tokens are required for channel management operations."
            )
    except SlackApiError as e:
        error_response = e.response.get("error", "unknown")
        error_detail = {
            "invalid_auth": "Token is invalid or expired",
            "not_authed": "No authentication token provided",
            "account_inactive": "Authentication token is for a deleted user or workspace",
            "token_revoked": "Authentication token has been revoked",
            "token_expired": "Authentication token has expired"
        }.get(error_response, f"Unknown error: {error_response}")
        
        print(f"\nDebug information:")
        print(f"Error code: {error_response}")
        print(f"Full response: {e.response}")
        print(f"\nToken information:")
        token = os.getenv("SLACK_TOKEN", "")
        print(f"Token prefix: {token[:10]}..." if token else "No token found")
        print(f"Token length: {len(token)}" if token else "No token found")
        
        raise ValueError(f"Failed to validate token: {error_detail}")

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
    
    Required Token Type:
    - User token (xoxp) is required, bot tokens are not supported
    
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
    
    if not token.startswith("xoxp-"):
        raise ValueError(
            "Invalid token format. Token must be a user token (starts with 'xoxp-'). "
            "Bot tokens are not supported for channel management operations."
        )
    
    print(f"Token format check: {'✓' if token.startswith('xoxp-') else '✗'}")
    client = WebClient(token=token)
    
    # Validate token type and scopes
    validate_token_type(client)
    validate_scopes(client)
    
    return client 