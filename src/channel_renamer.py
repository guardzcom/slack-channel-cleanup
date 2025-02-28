import asyncio
import argparse
import os
from typing import List, Dict, Optional
from slack_sdk.errors import SlackApiError
from .slack_client import get_slack_client
from .channel_csv import export_channels_to_csv, read_channels_from_csv
from .channel_actions import ChannelActionHandler, ChannelAction

async def get_all_channels() -> List[Dict]:
    """
    Fetch all channels (public and private) from Slack workspace.
    Returns a list of channel dictionaries.
    
    Note: Requires both channels:read and groups:read scopes.
    """
    client = get_slack_client()
    channels = []
    cursor = None
    
    while True:
        try:
            # Get both public and private channels
            response = client.conversations_list(
                types="public_channel,private_channel",
                exclude_archived=True,
                limit=200,  # Maximum allowed by Slack API
                cursor=cursor
            )
            
            if not response["ok"]:
                raise SlackApiError("Failed to fetch channels", response)
                
            channels.extend(response["channels"])
            
            # Handle pagination
            cursor = response.get("response_metadata", {}).get("next_cursor")
            if not cursor:
                break
                
            # Respect rate limits (Tier 2: 20+ per minute)
            await asyncio.sleep(1)
            
        except SlackApiError as e:
            error_code = e.response.get("error", "unknown_error")
            if error_code in ["missing_scope", "invalid_auth"]:
                raise ValueError(
                    "Missing required scopes or invalid authentication. "
                    "Ensure your token has channels:read and groups:read scopes."
                )
            raise
    
    return channels

async def get_channel_info(client, channel_id: str) -> Dict:
    """Get detailed channel information."""
    try:
        response = client.conversations_info(channel=channel_id)
        return response["channel"]
    except SlackApiError:
        return {}

async def get_user_approval(client, channel: Dict, action: str, target_value: Optional[str] = None) -> bool:
    """
    Get user approval for an action.
    
    Args:
        client: Slack client
        channel: Channel dictionary
        action: Action to perform
        target_value: Target value for merge/rename actions
    
    Returns:
        bool: True if approved, False if skipped
    """
    action_desc = {
        ChannelAction.KEEP.value: "keep as is",
        ChannelAction.ARCHIVE.value: "archive",
        ChannelAction.MERGE.value: f"merge into #{target_value}",
        ChannelAction.RENAME.value: f"rename to '{target_value}'"
    }
    
    desc = action_desc.get(action, action)
    channel_name = f"#{channel['name']}"
    if channel.get("is_private"):
        channel_name = f"🔒 {channel_name}"
    
    # Get detailed channel info
    channel_info = await get_channel_info(client, channel["channel_id"])
    
    print("\n" + "=" * 80)
    print(f"Channel: {channel_name}")
    print(f"Members: {channel.get('member_count', 'unknown')}")
    print(f"Created: {channel.get('created_date', 'unknown')}")
    if channel_info.get("purpose", {}).get("value"):
        print(f"Purpose: {channel_info['purpose']['value']}")
    if channel_info.get("topic", {}).get("value"):
        print(f"Topic: {channel_info['topic']['value']}")
    
    # Show last activity if available
    if channel_info.get("last_read"):
        from datetime import datetime
        last_read = datetime.fromtimestamp(float(channel_info["last_read"]))
        print(f"Last Activity: {last_read.strftime('%Y-%m-%d')}")
    
    print(f"\nProposed Action: {desc}")
    
    # For merge actions, show target channel info and validate
    if action == ChannelAction.MERGE.value and target_value:
        try:
            # Try to get target channel info
            target_channels = client.conversations_list(
                types="public_channel,private_channel",
                exclude_archived=True
            )["channels"]
            target = next((ch for ch in target_channels if ch["name"] == target_value.lstrip('#')), None)
            
            if target:
                print("\nTarget Channel Information:")
                print(f"Members: {target.get('num_members', 'unknown')}")
                if target.get("purpose", {}).get("value"):
                    print(f"Purpose: {target['purpose']['value']}")
                if target.get("topic", {}).get("value"):
                    print(f"Topic: {target['topic']['value']}")
                    
                # Warn about merging into a smaller channel
                if target.get("num_members", 0) < channel.get("member_count", 0):
                    print("\n⚠️  Warning: Target channel has fewer members than source channel!")
            else:
                print(f"\n⚠️  Warning: Target channel #{target_value} not found!")
                return False
        except SlackApiError:
            print(f"\n⚠️  Warning: Could not fetch target channel information")
            return False
    
    # For rename actions, validate the new name
    if action == ChannelAction.RENAME.value and target_value:
        if not target_value.islower() or ' ' in target_value or '.' in target_value:
            print("\n❌ Error: Invalid channel name format!")
            print("Channel names must:")
            print("- Be lowercase")
            print("- Not contain spaces or periods")
            print("- Only use letters, numbers, and hyphens")
            return False
            
        # Check if name is already taken
        try:
            existing = client.conversations_list(
                types="public_channel,private_channel",
                exclude_archived=True
            )["channels"]
            if any(ch["name"] == target_value for ch in existing):
                print(f"\n❌ Error: Channel name '{target_value}' is already taken!")
                return False
        except SlackApiError:
            print("\n⚠️  Warning: Could not validate channel name availability")
    
    if channel.get("notes"):
        print(f"\nNotes: {channel['notes']}")
    print("-" * 80)
    
    # Extra confirmation for destructive actions
    if action in [ChannelAction.ARCHIVE.value, ChannelAction.MERGE.value]:
        print("\n⚠️  WARNING: This is a destructive action that cannot be easily undone!")
        print("The channel will be archived and members will need to be manually re-added if restored.")
        if action == ChannelAction.MERGE.value:
            print("Members will need to manually join the target channel.")
            print(f"Consider posting an announcement in #{channel['name']} before proceeding.")
        
        confirm = input("Type the channel name to confirm: ")
        if confirm != channel["name"]:
            print("Channel name does not match. Action cancelled.")
            return False
    
    while True:
        response = input("\nApprove this action? (y/n/q to quit): ").lower()
        if response == 'q':
            raise KeyboardInterrupt("User requested to quit")
        if response in ['y', 'n']:
            return response == 'y'

async def execute_channel_actions(channels: List[Dict]) -> None:
    """Execute actions specified in the CSV file."""
    client = get_slack_client()
    handler = ChannelActionHandler(client)
    
    successful = 0
    failed = 0
    skipped = 0
    last_action = None
    
    print("\nExecuting channel actions:")
    print("=" * 80)
    print("For each action, you can:")
    print("- Press 'y' to approve")
    print("- Press 'n' to skip")
    print("- Press 'q' to quit the process")
    print("\nNotes:")
    print("- Destructive actions (archive/merge) require additional confirmation")
    print("- Actions are sorted to process renames before archives/merges")
    print("- A backup of your CSV file will be created before processing")
    print("=" * 80)
    
    try:
        # Sort channels by action type (renames first, then archives/merges)
        def action_priority(channel):
            action = channel["action"]
            if action == ChannelAction.KEEP.value:
                return 3
            elif action == ChannelAction.RENAME.value:
                return 0
            elif action == ChannelAction.ARCHIVE.value:
                return 1
            elif action == ChannelAction.MERGE.value:
                return 2
            return 4
        
        channels = sorted(channels, key=action_priority)
        
        for channel in channels:
            action = channel["action"]
            
            # Skip if action is "keep"
            if action == ChannelAction.KEEP.value:
                continue
            
            # Get user approval
            try:
                approved = await get_user_approval(client, channel, action, channel["target_value"])
                if not approved:
                    print("⏭️  Action skipped")
                    skipped += 1
                    continue
            except KeyboardInterrupt:
                print("\n⛔ Process interrupted by user")
                break
            
            # Execute the approved action
            result = await handler.execute_action(
                channel_id=channel["channel_id"],
                channel_name=channel["name"],
                action=action,
                target_value=channel["target_value"]
            )
            
            if result.success:
                successful += 1
                print(f"✅ {result.message}")
                last_action = (channel, action, channel["target_value"])
            else:
                failed += 1
                print(f"❌ {result.message}")
            
            # Respect rate limits
            await asyncio.sleep(1)
    
    except KeyboardInterrupt:
        print("\n⛔ Process interrupted by user")
    
    finally:
        print("\nExecution Summary:")
        print(f"Successful actions: {successful}")
        print(f"Failed actions: {failed}")
        print(f"Skipped actions: {skipped}")
        print(f"Total channels processed: {successful + failed + skipped}")
        
        if last_action and last_action[1] in [ChannelAction.ARCHIVE.value, ChannelAction.MERGE.value]:
            print("\nNote: To undo the last archive action, use the Slack UI:")
            print(f"1. Go to channel #{last_action[0]['name']}")
            print("2. Click the gear icon ⚙️")
            print("3. Select 'Additional options'")
            print("4. Choose 'Unarchive channel'")

# Add backup functionality
def backup_csv(filepath: str) -> str:
    """Create a backup of the CSV file before processing."""
    if not os.path.exists(filepath):
        return ""
        
    backup_path = f"{filepath}.bak"
    try:
        import shutil
        shutil.copy2(filepath, backup_path)
        return backup_path
    except Exception:
        return ""

async def main():
    """Main function to run the channel management script."""
    parser = argparse.ArgumentParser(description="Slack Channel Management Tool")
    parser.add_argument(
        "mode",
        choices=["export", "execute"],
        help="Mode of operation: 'export' to create CSV, 'execute' to run actions"
    )
    parser.add_argument(
        "--file",
        "-f",
        help="CSV file path (output for export, input for execute)"
    )
    parser.add_argument(
        "--yes",
        "-y",
        action="store_true",
        help="Skip initial confirmation prompt"
    )
    parser.add_argument(
        "--dry-run",
        "-d",
        action="store_true",
        help="Show what would be done without making any changes"
    )
    
    args = parser.parse_args()
    
    try:
        if args.mode == "export":
            print("Fetching channels...")
            channels = await get_all_channels()
            print(f"Found {len(channels)} channels")
            
            filename = export_channels_to_csv(channels, args.file)
            print(f"\nChannels exported to: {filename}")
            print("\nNext steps:")
            print("1. Open the CSV file in your preferred spreadsheet application")
            print("2. Review the channels and set the 'action' column to one of:")
            print("   - keep: Keep the channel as is (default)")
            print("   - archive: Archive the channel")
            print("   - merge: Merge into another channel (specify target in 'target_value')")
            print("   - rename: Rename the channel (specify new name in 'target_value')")
            print("3. Save the CSV and run the script with 'execute' mode")
            
        else:  # execute mode
            if not args.file:
                parser.error("CSV file path is required for execute mode")
            
            # Create backup of CSV file
            backup_path = backup_csv(args.file)
            if backup_path:
                print(f"Created backup of CSV file: {backup_path}")
            
            print(f"Reading actions from: {args.file}")
            channels = read_channels_from_csv(args.file)
            print(f"Found {len(channels)} channels to process")
            
            # Show summary of actions
            actions = {}
            for channel in channels:
                action = channel["action"]
                actions[action] = actions.get(action, 0) + 1
            
            print("\nAction Summary:")
            for action, count in actions.items():
                print(f"{action}: {count} channels")
            
            if args.dry_run:
                print("\nDRY RUN MODE - No changes will be made")
            
            # Ask for confirmation to start
            if not args.yes:
                response = input("\nStart processing channels? (yes/no): ")
                if response.lower() != "yes":
                    print("Operation cancelled.")
                    return
            
            await execute_channel_actions(channels)
            
    except ValueError as e:
        print(f"Configuration error: {str(e)}")
    except SlackApiError as e:
        print(f"Slack API error: {str(e)}")
    except Exception as e:
        print(f"Unexpected error: {str(e)}")

if __name__ == "__main__":
    asyncio.run(main()) 