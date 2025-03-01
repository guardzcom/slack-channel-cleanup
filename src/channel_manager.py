import os
import asyncio
from typing import List, Dict, Optional
from slack_sdk.errors import SlackApiError
from .slack_client import get_slack_client
from .channel_csv import (
    export_channels_to_csv,
    read_channels_from_csv,
    create_csv_writer,
    write_channel_to_csv,
    update_sheet_from_active_channels as update_csv
)
from .sheet_manager import SheetManager
from .channel_actions import ChannelActionHandler, ChannelAction

async def get_all_channels(csv_writer=None) -> List[Dict]:
    """
    Fetch all channels (public and private) from Slack workspace.
    Returns a list of channel dictionaries.
    
    Args:
        csv_writer: Optional CSV writer to write channels as they're fetched
    
    Note: Requires both channels:read and groups:read scopes.
    """
    client = get_slack_client()
    channels = []
    cursor = None
    page = 1
    
    print("\nFetching channels (200 per page)...")
    while True:
        try:
            print(f"Fetching page {page}...")
            # Get both public and private channels
            response = client.conversations_list(
                types="public_channel,private_channel",
                exclude_archived=True,
                limit=200,  # Maximum allowed by Slack API
                cursor=cursor
            )
            
            if not response["ok"]:
                raise SlackApiError("Failed to fetch channels", response)
                
            new_channels = response["channels"]
            channels.extend(new_channels)
            
            # Write new channels to CSV if writer provided
            if csv_writer:
                for channel in new_channels:
                    write_channel_to_csv(csv_writer, channel)
            
            print(f"Found {len(new_channels)} channels on page {page} (Total: {len(channels)})")
            
            # Handle pagination
            cursor = response.get("response_metadata", {}).get("next_cursor")
            if not cursor:
                break
                
            # Respect rate limits (Tier 2: 20+ per minute)
            print("Waiting for rate limit...")
            await asyncio.sleep(1)
            page += 1
            
        except SlackApiError as e:
            error_code = e.response.get("error", "unknown_error")
            if error_code in ["missing_scope", "invalid_auth"]:
                raise ValueError(
                    "Missing required scopes or invalid authentication. "
                    "Ensure your token has channels:read and groups:read scopes."
                )
            raise
    
    print(f"\nFetched {len(channels)} total channels")
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
        target_value: Target value for rename action or target channel for archive
    """
    action_desc = {
        ChannelAction.KEEP.value: "keep as is",
        ChannelAction.ARCHIVE.value: target_value and f"archive (with notice to join #{target_value})" or "archive",
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
    
    # For archive actions with target channel, show target channel info
    if action == ChannelAction.ARCHIVE.value and target_value:
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
                    
                # Warn about redirecting to a smaller channel
                source_members = int(channel.get("member_count", 0))
                target_members = int(target.get("num_members", 0))
                if target_members < source_members:
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
    
    # Extra warning for destructive actions
    if action == ChannelAction.ARCHIVE.value:
        print("\n⚠️  WARNING: This is a destructive action that cannot be easily undone!")
        print("The channel will be archived and members will need to be manually re-added if restored.")
        if target_value:
            print("Members will need to manually join the target channel.")
    
    while True:
        response = input("\nPress 'y' to approve, 'n' to skip, or 'q' to quit: ").lower()
        if response == 'q':
            raise KeyboardInterrupt("User requested to quit")
        if response in ['y', 'n']:
            return response == 'y'

async def execute_channel_actions(channels: List[Dict], dry_run: bool = False) -> List[str]:
    """Execute actions specified in the CSV file.
    
    Returns:
        List of channel IDs that were successfully processed
    """
    client = get_slack_client()
    handler = ChannelActionHandler(client)
    
    successful = 0
    failed = 0
    skipped = 0
    last_action = None
    successful_channel_ids = []  # Track successful channels
    
    # Action descriptions for messages
    action_desc = {
        ChannelAction.KEEP.value: "keep as is",
        ChannelAction.ARCHIVE.value: "archive",
        ChannelAction.RENAME.value: "rename to"
    }
    
    print("\nExecuting channel actions:")
    print("=" * 80)
    print("For each action, you can:")
    print("- Press 'y' to approve")
    print("- Press 'n' to skip")
    print("- Press 'q' to quit the process")
    print("\nNotes:")
    print("- Destructive actions (archive) require additional confirmation")
    print("- Actions are sorted to process renames before archives")
    if dry_run:
        print("\n🔍 DRY RUN MODE - No changes will be made to channels")
    print("=" * 80)
    
    try:
        # Sort channels by action type (renames first, then archives)
        def action_priority(channel):
            action = channel["action"]
            if action == ChannelAction.KEEP.value:
                return 2
            elif action == ChannelAction.RENAME.value:
                return 0
            elif action == ChannelAction.ARCHIVE.value:
                return 1
            return 3
        
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
            if dry_run:
                successful += 1
                channel_name = f"#{channel['name']}"
                if channel.get("is_private"):
                    channel_name = f"🔒 {channel_name}"
                
                action_message = action_desc[action]
                if action in [ChannelAction.ARCHIVE.value, ChannelAction.RENAME.value]:
                    action_message = f"{action_message} {channel['target_value']}"
                    
                print(f"✅ Would {action_message}: {channel_name}")
                continue
                
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
                successful_channel_ids.append(channel["channel_id"])  # Add to successful list
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
        
        if last_action and last_action[1] == ChannelAction.ARCHIVE.value:
            print("\nNote: To undo the last archive action, use the Slack UI:")
            print(f"1. Go to channel #{last_action[0]['name']}")
            print("2. Click the gear icon ⚙️")
            print("3. Select 'Additional options'")
            print("4. Choose 'Unarchive channel'")
        
        return successful_channel_ids  # Return the list of successful channel IDs 