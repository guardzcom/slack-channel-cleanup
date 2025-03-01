import os
import asyncio
from typing import List, Dict, Optional
from slack_sdk.errors import SlackApiError
from .slack_client import get_slack_client
from .channel_data import (
    read_channels_from_csv,
    create_csv_writer,
    write_channel_to_csv
)
from .sheet_manager import SheetManager
from .channel_actions import ChannelActionHandler, ChannelAction

async def fetch_channel_history(client, channel: Dict) -> None:
    """Fetch history for a single channel."""
    try:
        history = client.conversations_history(
            channel=channel["id"],
            limit=1  # Just get the most recent message
        )
        if history["messages"]:
            channel["latest"] = history["messages"][0]
    except SlackApiError:
        print(f"    ⚠️  Could not fetch history for #{channel['name']}")

async def get_all_channels(csv_writer=None) -> List[Dict]:
    """
    Fetch all active channels (public and private) from Slack workspace.
    Returns a list of channel dictionaries.
    
    Args:
        csv_writer: Optional CSV writer to write channels as they're fetched
    """
    client = get_slack_client()
    channels = []
    cursor = None
    page = 1
    
    print("\nFetching channels (200 per page)...")
    while True:
        try:
            print(f"Fetching page {page}...")
            response = client.conversations_list(
                types="public_channel,private_channel",
                exclude_archived=True,
                limit=200,
                cursor=cursor,
                include_num_members=True
            )
            
            if not response["ok"]:
                raise SlackApiError("Failed to fetch channels", response)
            
            new_channels = response["channels"]
            print(f"\nFetching last activity for {len(new_channels)} channels...")
            
            # Create tasks for concurrent history fetching
            tasks = []
            for i, channel in enumerate(new_channels, 1):
                print(f"  Queuing #{channel['name']}...")
                tasks.append(fetch_channel_history(client, channel))
                if len(tasks) >= 10:  # Process in batches of 10
                    await asyncio.gather(*tasks)
                    tasks = []
                    await asyncio.sleep(0.2)  # Small delay between batches
            
            # Process any remaining tasks
            if tasks:
                await asyncio.gather(*tasks)
            
            channels.extend(new_channels)
            
            if csv_writer:
                for channel in new_channels:
                    write_channel_to_csv(csv_writer, channel)
            
            print(f"Found {len(new_channels)} channels on page {page} (Total: {len(channels)})")
            
            cursor = response.get("response_metadata", {}).get("next_cursor")
            if not cursor:
                break
            
            page += 1
            await asyncio.sleep(0.2)  # Small delay between pages
            
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
        response = client.conversations_info(
            channel=channel_id,
            include_num_members=True  # Request member count in response
        )
        return response["channel"]
    except SlackApiError:
        return {}

async def get_user_approval(client, channel: Dict, action: str, target_value: Optional[str] = None, current_channels: Optional[List[Dict]] = None) -> bool:
    """
    Get user approval for an action.
    
    Args:
        client: Slack client
        channel: Channel dictionary
        action: Action to perform
        target_value: Target value for rename action or target channel for archive
        current_channels: Optional list of current channels to validate against
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
    print(f"Members: {channel_info.get('num_members', 'unknown')}")
    print(f"Created: {channel.get('created_date', 'unknown')}")
    if channel_info.get("purpose", {}).get("value"):
        print(f"Purpose: {channel_info['purpose']['value']}")
    if channel_info.get("topic", {}).get("value"):
        print(f"Topic: {channel_info['topic']['value']}")
    
    # Show last activity if available
    if channel_info.get("last_read"):
        try:
            from datetime import datetime
            last_read = datetime.fromtimestamp(float(channel_info["last_read"]))
            # Skip if date is Unix epoch (indicates no activity)
            if last_read.year > 1970:
                print(f"Last Activity: {last_read.strftime('%Y-%m-%d')}")
            else:
                print("Last Activity: No activity recorded")
        except ValueError:
            print("Last Activity: Unable to parse timestamp")
    
    print(f"\nProposed Action: {desc}")
    
    # For archive actions with target channel, show target channel info
    if action == ChannelAction.ARCHIVE.value and target_value:
        try:
            # Get target channel info by name from current_channels if available
            target = None
            target_name = target_value.lstrip('#')
            
            if current_channels:
                target = next((ch for ch in current_channels if ch["name"] == target_name), None)
            else:
                # Fallback to API call if current_channels not provided
                target_channels = client.conversations_list(
                    types="public_channel,private_channel",
                    exclude_archived=True
                )["channels"]
                target = next((ch for ch in target_channels if ch["name"] == target_name), None)
            
            if target:
                # Now get detailed info using the correct channel ID
                target_info = await get_channel_info(client, target["id"])
                print("\nTarget Channel Information:")
                print(f"Members: {target_info.get('num_members', 'unknown')}")
                if target_info.get("purpose", {}).get("value"):
                    print(f"Purpose: {target_info['purpose']['value']}")
                if target_info.get("topic", {}).get("value"):
                    print(f"Topic: {target_info['topic']['value']}")
                    
                # Warn about redirecting to a smaller channel
                source_members = int(channel.get("num_members", 0))
                target_members = int(target_info.get('num_members', 0))
                if target_members < source_members:
                    print("\n⚠️  Warning: Target channel has fewer members than source channel!")
            else:
                print(f"\n⚠️  Warning: Target channel #{target_value} not found!")
                while True:
                    response = input("\nPress 'r' to try a different target channel, 'n' to skip, or 'q' to quit: ").lower()
                    if response == 'q':
                        raise KeyboardInterrupt("User requested to quit")
                    if response == 'n':
                        return False
                    if response == 'r':
                        new_target = input("\nEnter new target channel name (without #): ").strip().lower()
                        if not new_target:
                            print("Name cannot be empty")
                            continue
                        if ' ' in new_target or '.' in new_target:
                            print("Name cannot contain spaces or periods")
                            continue
                        channel["target_value"] = new_target
                        return await get_user_approval(client, channel, action, new_target, current_channels)
        except SlackApiError:
            print(f"\n⚠️  Warning: Could not fetch target channel information")
            while True:
                response = input("\nPress 'n' to skip, or 'q' to quit: ").lower()
                if response == 'q':
                    raise KeyboardInterrupt("User requested to quit")
                if response == 'n':
                    return False
    
    # For rename actions, validate the new name
    if action == ChannelAction.RENAME.value and target_value:
        # Check length
        if len(target_value) > 80:
            print("\n❌ Error: Channel name is too long!")
            print("Channel names must be 80 characters or less")
            while True:
                response = input("\nPress 'r' to try a different name, 'n' to skip, or 'q' to quit: ").lower()
                if response == 'q':
                    raise KeyboardInterrupt("User requested to quit")
                if response == 'n':
                    return False
                if response == 'r':
                    new_name = input("\nEnter new channel name (without #): ").strip().lower()
                    if not new_name:
                        print("Name cannot be empty")
                        continue
                    channel["target_value"] = new_name
                    return await get_user_approval(client, channel, action, new_name, current_channels)
            
        # Check format
        if not target_value.islower() or ' ' in target_value or '.' in target_value:
            print("\n❌ Error: Invalid channel name format!")
            print("Channel names must:")
            print("- Be lowercase")
            print("- Not contain spaces or periods")
            print("- Only use letters, numbers, hyphens, and underscores")
            while True:
                response = input("\nPress 'r' to try a different name, 'n' to skip, or 'q' to quit: ").lower()
                if response == 'q':
                    raise KeyboardInterrupt("User requested to quit")
                if response == 'n':
                    return False
                if response == 'r':
                    new_name = input("\nEnter new channel name (without #): ").strip().lower()
                    if not new_name:
                        print("Name cannot be empty")
                        continue
                    channel["target_value"] = new_name
                    return await get_user_approval(client, channel, action, new_name, current_channels)
            
        # Check valid characters
        if not all(c.islower() or c.isdigit() or c in '-_' for c in target_value):
            print("\n❌ Error: Channel name contains invalid characters!")
            print("Only lowercase letters, numbers, hyphens, and underscores are allowed")
            while True:
                response = input("\nPress 'r' to try a different name, 'n' to skip, or 'q' to quit: ").lower()
                if response == 'q':
                    raise KeyboardInterrupt("User requested to quit")
                if response == 'n':
                    return False
                if response == 'r':
                    new_name = input("\nEnter new channel name (without #): ").strip().lower()
                    if not new_name:
                        print("Name cannot be empty")
                        continue
                    channel["target_value"] = new_name
                    return await get_user_approval(client, channel, action, new_name, current_channels)
        
        # Check if name is already taken (using current_channels if available)
        if current_channels:
            if any(ch["name"] == target_value for ch in current_channels):
                print(f"\n❌ Error: Channel name '{target_value}' is already taken!")
                while True:
                    response = input("\nPress 'r' to try a different name, 'n' to skip, or 'q' to quit: ").lower()
                    if response == 'q':
                        raise KeyboardInterrupt("User requested to quit")
                    if response == 'n':
                        return False
                    if response == 'r':
                        new_name = input("\nEnter new channel name (without #): ").strip().lower()
                        if not new_name:
                            print("Name cannot be empty")
                            continue
                        if ' ' in new_name or '.' in new_name:
                            print("Name cannot contain spaces or periods")
                            continue
                        channel["target_value"] = new_name
                        return await get_user_approval(client, channel, action, new_name, current_channels)
        else:
            try:
                existing = client.conversations_list(
                    types="public_channel,private_channel",
                    exclude_archived=True
                )["channels"]
                if any(ch["name"] == target_value for ch in existing):
                    print(f"\n❌ Error: Channel name '{target_value}' is already taken!")
                    while True:
                        response = input("\nPress 'r' to try a different name, 'n' to skip, or 'q' to quit: ").lower()
                        if response == 'q':
                            raise KeyboardInterrupt("User requested to quit")
                        if response == 'n':
                            return False
                        if response == 'r':
                            new_name = input("\nEnter new channel name (without #): ").strip().lower()
                            if not new_name:
                                print("Name cannot be empty")
                                continue
                            if ' ' in new_name or '.' in new_name:
                                print("Name cannot contain spaces or periods")
                                continue
                            channel["target_value"] = new_name
                            return await get_user_approval(client, channel, action, new_name, current_channels)
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
    """Process pending actions for the specified channels.
    
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
            action = channel.get("action", "")
            if not action:  # Handle missing action
                return 3
            action = action.lower()
            if action == ChannelAction.KEEP.value:
                return 2
            elif action == ChannelAction.RENAME.value:
                return 0
            elif action == ChannelAction.ARCHIVE.value:
                return 1
            return 3
        
        channels = sorted(channels, key=action_priority)
        
        # Get current channels once for validation
        current_channels = await get_all_channels()
        
        for channel in channels:
            # Skip invalid channels
            if not channel.get("channel_id") or not channel.get("name"):
                print(f"⚠️  Skipping invalid channel: {channel}")
                skipped += 1
                continue
                
            action = channel.get("action", "").lower()
            
            # Skip if action is "keep" or invalid
            if not action or action == ChannelAction.KEEP.value:
                continue
                
            # Validate action is supported
            if action not in ChannelAction.values():
                print(f"⚠️  Skipping unsupported action '{action}' for channel {channel['name']}")
                skipped += 1
                continue
            
            # Get user approval
            try:
                approved = await get_user_approval(client, channel, action, channel.get("target_value"), current_channels)
                if not approved:
                    print("⏭️  Action skipped")
                    skipped += 1
                    continue
            except KeyboardInterrupt:
                print("\n⛔ Process interrupted by user")
                break
            except Exception as e:
                print(f"❌ Error getting approval for {channel['name']}: {str(e)}")
                failed += 1
                continue
            
            # Execute the approved action
            if dry_run:
                successful += 1
                channel_name = f"#{channel['name']}"
                if channel.get("is_private"):
                    channel_name = f"🔒 {channel_name}"
                
                action_message = action_desc.get(action, action)
                if action in [ChannelAction.ARCHIVE.value, ChannelAction.RENAME.value]:
                    action_message = f"{action_message} {channel.get('target_value', '')}"
                    
                print(f"✅ Would {action_message}: {channel_name}")
                continue
            
            # Verify channel still exists and is in expected state before executing
            try:
                channel_info = await get_channel_info(client, channel["channel_id"])
                if not channel_info:
                    print(f"❌ Channel {channel['name']} no longer exists!")
                    while True:
                        response = input("\nPress 'n' to skip, or 'q' to quit: ").lower()
                        if response == 'q':
                            raise KeyboardInterrupt("User requested to quit")
                        if response == 'n':
                            skipped += 1
                            break
                    continue
                if channel_info.get("is_archived"):
                    print(f"❌ Channel {channel['name']} is already archived!")
                    while True:
                        response = input("\nPress 'n' to skip, or 'q' to quit: ").lower()
                        if response == 'q':
                            raise KeyboardInterrupt("User requested to quit")
                        if response == 'n':
                            skipped += 1
                            break
                    continue
                if channel_info.get("name") != channel["name"]:
                    print(f"❌ Channel has been renamed from {channel['name']} to {channel_info['name']}!")
                    while True:
                        response = input("\nPress 'n' to skip, or 'q' to quit: ").lower()
                        if response == 'q':
                            raise KeyboardInterrupt("User requested to quit")
                        if response == 'n':
                            skipped += 1
                            break
                    continue
                    
                # Now execute the action
                result = await handler.execute_action(
                    channel_id=channel["channel_id"],
                    channel_name=channel["name"],
                    action=action,
                    target_value=channel.get("target_value", "")
                )
                
                if result.success:
                    successful += 1
                    print(f"✅ {result.message}")
                    
                    # Update channel name in our data after successful rename
                    if action == ChannelAction.RENAME.value:
                        channel["name"] = channel.get("target_value")
                    
                    last_action = (channel, action, channel.get("target_value"))
                    successful_channel_ids.append(channel["channel_id"])  # Add to successful list
                else:
                    failed += 1
                    print(f"❌ {result.message}")
            except Exception as e:
                print(f"❌ Error processing {channel['name']}: {str(e)}")
                while True:
                    response = input("\nPress 'n' to skip, or 'q' to quit: ").lower()
                    if response == 'q':
                        raise KeyboardInterrupt("User requested to quit")
                    if response == 'n':
                        skipped += 1
                        break
                continue
            
            # Respect rate limits
            await asyncio.sleep(1)
    
    except KeyboardInterrupt:
        print("\n⛔ Process interrupted by user")
    except Exception as e:
        print(f"\n❌ Unexpected error: {str(e)}")
    
    finally:
        print("\nExecution Summary:")
        print(f"Successful actions: {successful}")
        print(f"Failed actions: {failed}")
        print(f"Skipped actions: {skipped}")
        print(f"Total channels processed: {successful + failed + skipped}")
        
        # Add summary of what was done
        if successful > 0:
            action_counts = {}
            for channel in channels:
                if channel.get("channel_id") in successful_channel_ids:
                    action = channel.get("action", "").lower()
                    action_counts[action] = action_counts.get(action, 0) + 1
            
            summary_parts = []
            for action, count in action_counts.items():
                if action == ChannelAction.ARCHIVE.value:
                    summary_parts.append(f"{count} archived")
                elif action == ChannelAction.RENAME.value:
                    summary_parts.append(f"{count} renamed")
            
            if summary_parts:
                print(f"\nCompleted: {', '.join(summary_parts)}")
        
        if last_action and last_action[1] == ChannelAction.ARCHIVE.value:
            print("\nNote: To undo the last archive action, use the Slack UI:")
            print("1. Go to channel #" + last_action[0]['name'])
            print("2. Click the gear icon ⚙️")
            print("3. Select 'Additional options'")
            print("4. Choose 'Unarchive channel'")
        
        return successful_channel_ids  # Return the list of successful channel IDs 